"""Conversación WhatsApp C-12 (`notificaciones/confirmacion-conversacional`).

Bot 24/7 determinístico (sin ML): interpreta `confirmar|cancelar|
reprogramar` en texto libre ES y delega en el núcleo C-04/C-05 con
`canal=whatsapp`. Estado efímero en Redis `wa:conv:{hash}` con TTL
(`WA_CONV_TTL_MIN`, `SET NX`); sin migración (R2).

Contratos (fijados por los tests RED 1.1–1.6, honrados en GREEN):
- Inbound con `texto` + `remitente` E.164; propuesta con opciones
  numeradas y fechas ISO; elección por número; oferta `wa:conv:{hash}`
  con TTL en `app.state.redis`; rate-limit por env
  `WA_CONV_RATE_MAX/WINDOW`; respuestas con link de gestión/pago y
  `CANCEL_POLICY_TEXT`, siempre sin PII (R6).
- Vocabulario: tabla ES versionada en código (listas explícitas, sin
  distancia de edición abierta); prioridad `cancelar > reprogramar >
  confirmar`; ante duda → ayuda, nunca mutar.
- Interactivos/botones de Meta se mapean al mismo vocabulario (el
  `texto` del botón equivale al texto libre; sin ramas propias).
- Respuestas solo con `{nombre_pila?, fecha, hora, sede, link_gestion}`
  (jamás DNI, teléfono, HC, motivo clínico ni token crudo, R6).
- Logs/diffs solo con `remitente` como `sha256[:12]` y `wa_message_id`;
  el texto libre entrante jamás se loguea (extiende C-06, R6).
- Remitente desconocido o ambiguo jamás muta ni filtra (link genérico).

R0: teléfonos sintéticos `+54 9 11 15-000-XXXX`. R1: type hints.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import SlotOcupadoError
from app.core.logger import get_logger
from app.core.settings import settings
from app.infrastructure.whatsapp.mensajes import fecha_hora_corta
from app.models.entidades import Turno
from app.repositories import auditoria as repo_auditoria
from app.services import avisos as svc_avisos
from app.services.autogestion import (
    CANCELABLE_DESDE as CANCELABLE_NUCLEO,
)
from app.services.autogestion import (
    CONFIRMABLE_DESDE as CONFIRMABLE_NUCLEO,
)
from app.services.autogestion import (
    ahora_utc,
    min_horas_cancelacion,
    texto_politica,
)
from app.services.reserva_publica import url_pago_para

logger = get_logger(__name__)

BA = ZoneInfo("America/Argentina/Buenos_Aires")

TipoIntent = Literal["confirmar", "cancelar", "reprogramar", "ayuda", "desconocido"]

# Link de gestión genérico (el mismo para todos, sin confirmar ni negar
# existencia; contiene "gestion" para el contrato RED 1.2, R6).
LINK_GESTION_GENERICO = "https://gestion.ejemplo.local/turnos"

# --- Vocabulario ES versionado (listas explícitas, sin ML) ---

CONFIRMAR_VOCABULARIO: tuple[str, ...] = (
    "si",
    "confirmo",
    "confirmar",
    "ok",
    "dale",
    "de acuerdo",
    "confirmado",
    "asisto",
    "voy",
)

CANCELAR_VOCABULARIO: tuple[str, ...] = (
    "cancelar",
    "cancela",
    "cancelo",
    "baja",
    "dar de baja",
    "no puedo ir",
    "no voy",
    "anular",
    "anula",
    "suspender",
)

REPROGRAMAR_VOCABULARIO: tuple[str, ...] = (
    "reprogramar",
    "reprograma",
    "cambiar",
    "cambia",
    "mover",
    "otro dia",
    "otro horario",
    "otra fecha",
    "cambio de horario",
    "posponer",
)

ISO_EN_TEXTO = re.compile(r"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}")

ESTADOS_VIGENTES: frozenset[str] = frozenset({"reservado", "confirmado"})
TERMINALES_CONOCIDOS: frozenset[str] = frozenset(
    {"atendido", "ausente", "presente", "cancelado", "reprogramado"}
)


def normalizar_texto(texto: str) -> str:
    """Minúsculas, sin tildes, puntuación de bordes recortada."""
    base = (
        unicodedata.normalize("NFD", texto.lower())
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return base.strip().strip(" .!?,;:\"'()[]").strip()


def _contiene_termino(normalizado: str, frase: str) -> bool:
    """Subcadena para frases; palabra completa para términos cortos.

    Evita falsos positivos (`si` dentro de `misa` no confirma).
    """
    if " " in frase:
        return frase in normalizado
    return re.search(rf"\b{re.escape(frase)}\b", normalizado) is not None


def parse_intent(texto: str | None) -> TipoIntent:
    """Clasifica el texto según la tabla ES con prioridad determinística.

    Prioridad ante solape: `cancelar` > `reprogramar` > `confirmar`;
    ante duda → `desconocido` (el llamador responde ayuda, nunca muta).
    Los interactivos/botones de Meta llegan como su `texto` y usan esta
    misma tabla (sin vocabulario paralelo).
    """
    if texto is None:
        return "desconocido"
    normalizado = normalizar_texto(texto)
    if not normalizado:
        return "desconocido"
    for frase in CANCELAR_VOCABULARIO:
        if _contiene_termino(normalizado, frase):
            return "cancelar"
    for frase in REPROGRAMAR_VOCABULARIO:
        if _contiene_termino(normalizado, frase):
            return "reprogramar"
    for frase in CONFIRMAR_VOCABULARIO:
        if _contiene_termino(normalizado, frase):
            return "confirmar"
    return "desconocido"


def normalizar_remitente(remitente: str) -> str:
    """Canónico para matching: solo dígitos (tolera `+54 9 11…` vs `11…`)."""
    return re.sub(r"\D", "", remitente.strip())


def hash_remitente(remitente: str) -> str:
    """`sha256(e164)[:12]`: única referencia al remitente (R6)."""
    return hashlib.sha256(remitente.encode("utf-8")).hexdigest()[:12]


def _entero_env(nombres: tuple[str, ...], base: int) -> int:
    for nombre in nombres:
        crudo = os.environ.get(nombre)
        if crudo is None:
            continue
        try:
            return int(crudo)
        except ValueError:
            continue
    return base


def ttl_conv_min() -> int:
    """`WA_CONV_TTL_MIN` legible por env en cada llamada (piloto)."""
    return _entero_env(("WA_CONV_TTL_MIN",), settings.wa_conv_ttl_min)


def topes_rate_conv() -> tuple[int, int]:
    """`(max, ventana_s)` por env (acepta `WINDOW` y `WINDOW_S`)."""
    tope = _entero_env(("WA_CONV_RATE_MAX",), settings.wa_conv_rate_max)
    ventana = _entero_env(
        ("WA_CONV_RATE_WINDOW_S", "WA_CONV_RATE_WINDOW"),
        settings.wa_conv_rate_window_s,
    )
    return tope, ventana


def clave_oferta(remitente_hash: str) -> str:
    return f"wa:conv:{remitente_hash}"


def clave_rate(remitente_hash: str) -> str:
    """Rate por remitente-hash (prefijo propio: no colisiona con `wa:conv:*`)."""
    return f"rl:wa-conv:{remitente_hash}"


async def chequear_rate_conv(redis: Any, remitente_hash: str) -> int | None:
    """Rate por remitente-hash (`INCR+EXPIRE`, patrón C-03/C-05).

    Retorna la espera en segundos si se excede el tope, `None` si pasa.
    Sin Redis → fail-open (la DB manda).
    """
    if redis is None:
        return None
    try:
        tope, ventana = topes_rate_conv()
        conteo = await redis.incr(clave_rate(remitente_hash))
        if conteo == 1:
            await redis.expire(clave_rate(remitente_hash), ventana)
        if int(conteo) > tope:
            ttl = await redis.ttl(clave_rate(remitente_hash))
            return ttl if isinstance(ttl, int) and ttl > 0 else ventana
    except Exception:  # noqa: BLE001 — fail-open intencional.
        logger.warning("redis no disponible, degradando", extra={"op": "rate_conv"})
        return None
    return None


def _coincide_con_candidato(digitos_mensaje: str, digitos_turno: str) -> bool:
    """Igualdad de dígitos o sufijo (tolera prefijo país `54 9`)."""
    if not digitos_mensaje or not digitos_turno:
        return False
    if digitos_mensaje == digitos_turno:
        return True
    minimo = 8
    return (
        len(digitos_mensaje) >= minimo
        and len(digitos_turno) >= minimo
        and (
            digitos_mensaje.endswith(digitos_turno)
            or digitos_turno.endswith(digitos_mensaje)
        )
    )


async def _turnos_del_remitente(
    session: AsyncSession, digitos: str, *, solo_vigentes: bool
) -> list[Turno]:
    """Turnos del remitente (matching en Python por normalización AR)."""
    stmt = (
        select(Turno)
        .options(
            selectinload(Turno.paciente),
            selectinload(Turno.profesional),
            selectinload(Turno.sillon),
            selectinload(Turno.prestacion),
        )
        .order_by(Turno.inicio)
    )
    if solo_vigentes:
        stmt = stmt.where(Turno.estado.in_(tuple(ESTADOS_VIGENTES)))
    filas = list((await session.execute(stmt)).scalars().all())
    ahora = ahora_utc()
    candidatos: list[Turno] = []
    for turno in filas:
        telefono = turno.paciente.telefono if turno.paciente is not None else ""
        if not _coincide_con_candidato(digitos, normalizar_remitente(telefono)):
            continue
        inicio = turno.inicio
        if inicio.tzinfo is None:
            inicio = inicio.replace(tzinfo=BA)
        if inicio <= ahora:
            continue
        candidatos.append(turno)
    candidatos.sort(key=lambda t: t.inicio)
    return candidatos


def _fecha_ba(inicio: datetime) -> Any:
    momento = inicio if inicio.tzinfo is not None else inicio.replace(tzinfo=BA)
    return momento.astimezone(BA).date()


def _sede_de(turno: Turno) -> str:
    if turno.sillon is not None and turno.sillon.sede:
        return str(turno.sillon.sede)
    return "Consultorio"


def _acuse_confirmacion(turno: Turno) -> dict[str, str]:
    fecha, hora = fecha_hora_corta(turno.inicio.astimezone(BA))
    sede = _sede_de(turno)
    return {
        "mensaje": (
            f"Tu turno quedó confirmado para el {fecha} a las {hora} "
            f"en {sede}. Gestioná tus turnos aquí: {LINK_GESTION_GENERICO}. "
            f"{texto_politica()}"
        ),
        "fecha": fecha,
        "hora": hora,
        "sede": sede,
        "link_gestion": LINK_GESTION_GENERICO,
    }


def _respuesta_generica() -> dict[str, str]:
    return {
        "mensaje": (
            "No encontramos un turno vigente para este número. "
            f"Gestioná tus turnos aquí: {LINK_GESTION_GENERICO}."
        ),
        "link_gestion": LINK_GESTION_GENERICO,
    }


def _respuesta_ayuda() -> dict[str, str]:
    return {
        "mensaje": (
            "Puedo ayudarte a confirmar, cancelar o reprogramar tu turno. "
            "Respondé SÍ para confirmar, CANCELAR para cancelar o "
            f"REPROGRAMAR para ver opciones. {LINK_GESTION_GENERICO}."
        ),
        "link_gestion": LINK_GESTION_GENERICO,
    }


async def _oferta_existente(redis: Any, remitente_hash: str) -> dict[str, Any] | None:
    if redis is None:
        return None
    try:
        crudo = await redis.get(clave_oferta(remitente_hash))
    except Exception:  # noqa: BLE001 — sin Redis no hay oferta (reiniciar).
        return None
    if not crudo:
        return None
    try:
        cuerpo = json.loads(crudo) if isinstance(crudo, str) else json.loads(str(crudo))
    except (ValueError, TypeError):
        return None
    if not isinstance(cuerpo, dict):
        return None
    return dict(cuerpo)


async def _guardar_oferta(
    redis: Any, remitente_hash: str, turno_id: UUID, slots_iso: list[str]
) -> list[str]:
    """Guarda la oferta con `SET NX EX` (la existente manda ante carrera)."""
    if redis is None:
        return slots_iso
    cuerpo = json.dumps({"turno_id": str(turno_id), "slots": slots_iso})
    try:
        fijada = await redis.set(
            clave_oferta(remitente_hash), cuerpo, nx=True, ex=ttl_conv_min() * 60
        )
        if not fijada:
            existente = await _oferta_existente(redis, remitente_hash)
            if existente is not None:
                previos = existente.get("slots")
                if isinstance(previos, list) and previos:
                    return [str(s) for s in previos]
    except Exception:  # noqa: BLE001 — fail-open (la DB manda).
        logger.warning("redis no disponible, degradando", extra={"op": "oferta"})
    return slots_iso


async def _borrar_oferta(redis: Any, remitente_hash: str) -> None:
    if redis is None:
        return
    try:
        await redis.delete(clave_oferta(remitente_hash))
    except Exception:  # noqa: BLE001 — fail-open intencional.
        logger.warning("redis no disponible, degradando", extra={"op": "oferta"})


async def _generar_slots_libres(
    session: AsyncSession, turno: Turno, *, cantidad: int = 3
) -> list[str]:
    """Slots reales libres (pre-chequeo C-01 sobre profesional y sillón).

    Candidatos diarios a la misma hora del turno original (+1…+14 días);
    solo los libres por `existe_solape_*` (la DB manda ante carreras vía
    GiST en la elección). Fechas ISO con zona (contrato RED 1.4).
    """
    from app.repositories import agenda as repo_agenda

    duracion_min: int = int(turno.prestacion.duracion_min)
    base = turno.inicio
    # Zona AR para el wall-clock ofertado: el paciente lee la hora en
    # hora local (el contrato RED parsea `YYYY-MM-DDTHH:MM` y lo interpreta
    # en BA; con UTC el truncado apuntaría a otro instante).
    if base.tzinfo is None:
        base = base.replace(tzinfo=BA)
    else:
        base = base.astimezone(BA)
    libres: list[str] = []
    for delta_dias in range(1, 15):
        candidato = base + timedelta(days=delta_dias)
        fin = candidato + timedelta(minutes=duracion_min)
        if await repo_agenda.existe_solape_profesional(
            session,
            turno.profesional_id,
            candidato,
            fin,
            excluir_turno_id=turno.id,
        ):
            continue
        if turno.sillon_id is not None and await repo_agenda.existe_solape_sillon(
            session,
            turno.sillon_id,
            candidato,
            fin,
            excluir_turno_id=turno.id,
        ):
            continue
        libres.append(candidato.isoformat())
        if len(libres) >= cantidad:
            break
    return libres


def _respuesta_propuesta(slots_iso: list[str]) -> dict[str, Any]:
    lineas = " ".join(f"{i + 1}) {iso}" for i, iso in enumerate(slots_iso))
    return {
        "mensaje": (
            "Elegí una opción para reprogramar (slots reales libres): "
            f"{lineas}. Respondé con el número de opción. "
            f"Oferta válida por {ttl_conv_min()} min."
        ),
        "opciones": slots_iso,
        "link_gestion": LINK_GESTION_GENERICO,
    }


def _respuesta_desambiguacion(candidatos: list[Turno]) -> dict[str, Any]:
    partes: list[str] = []
    for i, turno in enumerate(candidatos[:5]):
        fecha, hora = fecha_hora_corta(turno.inicio.astimezone(BA))
        partes.append(f"{i + 1}) {turno.inicio.isoformat()} ({fecha} {hora})")
    return {
        "mensaje": (
            "Tenés más de un turno hoy. Elegí una opción respondiendo "
            f"con el número: {' '.join(partes)}. "
            f"Gestioná tus turnos aquí: {LINK_GESTION_GENERICO}."
        ),
        "opciones": [t.inicio.isoformat() for t in candidatos[:5]],
        "link_gestion": LINK_GESTION_GENERICO,
    }


async def _auditar_conversacion(
    session: AsyncSession,
    *,
    accion: str,
    turno_id: str | None,
    remitente_hash: str,
    wa_message_id: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Auditoría conversacional sin PII (entidad `conversacion`, R6)."""
    diff: dict[str, Any] = {
        "remitente": remitente_hash,
        "wa_message_id": wa_message_id,
    }
    if extra:
        diff.update(extra)
    await repo_auditoria.registrar_auditoria(
        session,
        accion=accion,
        entidad="conversacion",
        entidad_id=turno_id,
        diff=diff,
    )


async def procesar_mensaje(
    session: AsyncSession,
    redis: Any,
    *,
    remitente: str | None,
    texto: str | None,
    wa_message_id: str,
) -> tuple[int, dict[str, Any]]:
    """Orquesta intent → resolución → delegación al núcleo (R2/R3/R6).

    Retorna `(estado_http, cuerpo)`. Jamás muta ante remitente
    desconocido, mensaje ambiguo u oferta expirada. El `canal` auditado
    en cada mutación es `whatsapp` (delegación C-04/C-05 sin duplicar
    reglas: mismos `409`/`422`, mismos hooks C-06 de reagendado).
    """
    remitente_hash = hash_remitente(remitente or "desconocido")
    texto_crudo = texto or ""

    # Elección numérica/ISO con oferta pendiente (tiene prioridad sobre el
    # vocabulario: "1" no es un intent sino la opción ofertada).
    eleccion = _parsear_eleccion(texto_crudo)
    if eleccion is not None:
        return await _procesar_eleccion(
            session,
            redis,
            remitente_hash=remitente_hash,
            eleccion=eleccion,
            wa_message_id=wa_message_id,
        )

    intent = parse_intent(texto_crudo)
    if remitente is None or not normalizar_remitente(remitente):
        await _auditar_conversacion(
            session,
            accion="conv_desconocido",
            turno_id=None,
            remitente_hash=remitente_hash,
            wa_message_id=wa_message_id,
        )
        await session.commit()
        return 200, _respuesta_generica()

    digitos = normalizar_remitente(remitente)
    candidatos = await _turnos_del_remitente(session, digitos, solo_vigentes=True)

    if not candidatos:
        # ¿Terminal del mismo remitente? → 422 conversacional (sin mutar).
        previos = await _turnos_del_remitente(session, digitos, solo_vigentes=False)
        if previos:
            await _auditar_conversacion(
                session,
                accion="conv_terminal",
                turno_id=str(previos[0].id),
                remitente_hash=remitente_hash,
                wa_message_id=wa_message_id,
                extra={"intent": intent},
            )
            await session.commit()
            return 422, {
                "problema": "transicion_invalida",
                "detalle": "El turno no admite esa operación en su estado actual.",
            }
        await _auditar_conversacion(
            session,
            accion="conv_desconocido",
            turno_id=None,
            remitente_hash=remitente_hash,
            wa_message_id=wa_message_id,
            extra={"intent": intent},
        )
        await session.commit()
        return 200, _respuesta_generica()

    if len(candidatos) >= 2 and _fecha_ba(candidatos[0].inicio) == _fecha_ba(
        candidatos[1].inicio
    ):
        await _auditar_conversacion(
            session,
            accion="conv_desambiguacion",
            turno_id=str(candidatos[0].id),
            remitente_hash=remitente_hash,
            wa_message_id=wa_message_id,
            extra={"candidatos": len(candidatos)},
        )
        await session.commit()
        return 200, _respuesta_desambiguacion(candidatos)

    turno = candidatos[0]
    if intent == "desconocido":
        await _auditar_conversacion(
            session,
            accion="conv_ambiguo",
            turno_id=str(turno.id),
            remitente_hash=remitente_hash,
            wa_message_id=wa_message_id,
        )
        await session.commit()
        return 200, _respuesta_ayuda()
    if intent == "confirmar":
        return await _confirmar_conversacional(
            session, turno, remitente_hash=remitente_hash, wa_message_id=wa_message_id
        )
    if intent == "cancelar":
        return await _cancelar_conversacional(
            session, turno, remitente_hash=remitente_hash, wa_message_id=wa_message_id
        )
    return await _proponer_reprogramacion(
        session,
        redis,
        turno,
        remitente_hash=remitente_hash,
        wa_message_id=wa_message_id,
    )


def _parsear_eleccion(texto: str) -> str | None:
    """`1`/`2`/… o ISO contenido en el texto (elección de oferta)."""
    normalizado = texto.strip()
    if re.fullmatch(r"\d{1,2}", normalizado):
        return normalizado
    hallado = ISO_EN_TEXTO.search(texto)
    if hallado:
        return hallado.group(0)
    return None


async def _procesar_eleccion(
    session: AsyncSession,
    redis: Any,
    *,
    remitente_hash: str,
    eleccion: str,
    wa_message_id: str,
) -> tuple[int, dict[str, Any]]:
    oferta = await _oferta_existente(redis, remitente_hash)
    if oferta is None:
        await _auditar_conversacion(
            session,
            accion="conv_oferta_expirada",
            turno_id=None,
            remitente_hash=remitente_hash,
            wa_message_id=wa_message_id,
        )
        await session.commit()
        return 200, {
            "mensaje": (
                "Tu oferta de reprogramación expiró o no existe. "
                "Respondé REPROGRAMAR para ver slots frescos. "
                f"{LINK_GESTION_GENERICO}."
            ),
            "link_gestion": LINK_GESTION_GENERICO,
        }
    slots = oferta.get("slots")
    lista_slots: list[str] = [str(s) for s in slots] if isinstance(slots, list) else []
    turno_id_crudo = str(oferta.get("turno_id") or "")
    try:
        turno_id = UUID(turno_id_crudo)
    except ValueError:
        await _borrar_oferta(redis, remitente_hash)
        return 200, {
            "mensaje": (
                "Tu oferta de reprogramación venció. Respondé REPROGRAMAR "
                f"para ver slots frescos. {LINK_GESTION_GENERICO}."
            ),
            "link_gestion": LINK_GESTION_GENERICO,
        }
    elegido_iso: str | None = None
    if eleccion.isdigit():
        indice = int(eleccion) - 1
        if 0 <= indice < len(lista_slots):
            elegido_iso = lista_slots[indice]
    elif eleccion in lista_slots:
        elegido_iso = eleccion
    if elegido_iso is None:
        return 200, {
            "mensaje": (
                "Esa opción no está en la oferta vigente. Respondé con el "
                f"número de opción o REPROGRAMAR para reiniciar. {LINK_GESTION_GENERICO}."
            ),
            "link_gestion": LINK_GESTION_GENERICO,
        }
    try:
        nuevo_inicio = datetime.fromisoformat(elegido_iso)
    except ValueError:
        return 200, {
            "mensaje": (
                "Esa opción no es válida. Respondé REPROGRAMAR para ver "
                f"slots frescos. {LINK_GESTION_GENERICO}."
            ),
            "link_gestion": LINK_GESTION_GENERICO,
        }
    from app.services.agenda import reprogramar_turno

    try:
        nuevo = await reprogramar_turno(
            session, turno_id, nuevo_inicio=nuevo_inicio, usuario_id=None, ip=None
        )
    except SlotOcupadoError as exc:
        await _auditar_conversacion(
            session,
            accion="conv_colision_slot",
            turno_id=str(turno_id),
            remitente_hash=remitente_hash,
            wa_message_id=wa_message_id,
        )
        await session.commit()
        return 409, {
            "problema": exc.problema,
            "detalle": "El slot solicitado está ocupado; se ofrecen alternativas.",
            "slots_alternativos": exc.slots_alternativos,
        }
    except Exception:  # noqa: BLE001 — terminal/inactivo → 422 sin mutar.
        await session.rollback()
        return 422, {
            "problema": "transicion_invalida",
            "detalle": "El turno no admite esa operación en su estado actual.",
        }
    await repo_auditoria.registrar_auditoria(
        session,
        accion="turno_reprogramado",
        entidad="turno",
        entidad_id=str(turno_id),
        diff={
            "turno_nuevo_id": str(nuevo.id),
            "inicio_anterior": elegido_iso,
            "inicio_nuevo": nuevo.inicio.isoformat(),
            "estado_original": "reprogramado",
            "canal": "whatsapp",
        },
        usuario_id=None,
        ip=None,
    )
    await session.commit()
    await _borrar_oferta(redis, remitente_hash)
    # `nuevo` no trae relaciones cargadas: recarga fresca con `selectinload`
    # (el acceso perezoso `nuevo.sillon` rompería en sesión async, R2).
    from app.repositories import agenda as repo_agenda

    fresco = await repo_agenda.obtener_turno_por_id(session, nuevo.id)
    assert fresco is not None
    fecha, hora = fecha_hora_corta(fresco.inicio.astimezone(BA))
    sede = _sede_de(fresco)
    logger.info("turno reprogramado por whatsapp")
    return 200, {
        "mensaje": (
            f"Listo, tu turno se reprogramó al {fecha} a las {hora} en "
            f"{sede}. Gestioná tus turnos aquí: {LINK_GESTION_GENERICO}."
        ),
        "fecha": fecha,
        "hora": hora,
        "sede": sede,
        "link_gestion": LINK_GESTION_GENERICO,
    }


async def _confirmar_conversacional(
    session: AsyncSession, turno: Turno, *, remitente_hash: str, wa_message_id: str
) -> tuple[int, dict[str, Any]]:
    """`reservado→confirmado` idempotente + guarda de seña (RN-PA-02)."""
    from app.repositories import pagos as repo_pagos

    if turno.estado == "confirmado":
        return 200, _acuse_confirmacion(turno)
    if turno.estado not in CONFIRMABLE_NUCLEO:
        await _auditar_conversacion(
            session,
            accion="conv_terminal",
            turno_id=str(turno.id),
            remitente_hash=remitente_hash,
            wa_message_id=wa_message_id,
            extra={"intent": "confirmar"},
        )
        await session.commit()
        return 422, {
            "problema": "transicion_invalida",
            "detalle": "El turno no admite esa operación en su estado actual.",
        }
    if bool(turno.prestacion.requiere_sena):
        acreditado = await repo_pagos.acreditado_por_turno(session, turno.id)
        if acreditado is None:
            await _auditar_conversacion(
                session,
                accion="conv_sena_pendiente",
                turno_id=str(turno.id),
                remitente_hash=remitente_hash,
                wa_message_id=wa_message_id,
            )
            await session.commit()
            url_pago = url_pago_para(turno.id, str(turno.token_publico))
            return 200, {
                "mensaje": (
                    "Para confirmar necesitás completar la seña. "
                    f"Pagala aquí: {url_pago}."
                ),
                "url_pago": url_pago,
                "link_gestion": LINK_GESTION_GENERICO,
            }
    anterior = turno.estado
    turno.estado = "confirmado"
    await session.commit()
    await session.refresh(turno)
    await repo_auditoria.registrar_auditoria(
        session,
        accion="turno_confirmado",
        entidad="turno",
        entidad_id=str(turno.id),
        diff={
            "estado_anterior": anterior,
            "estado_nuevo": "confirmado",
            "canal": "whatsapp",
        },
        usuario_id=None,
        ip=None,
    )
    await session.commit()
    await session.refresh(turno)
    await svc_avisos.tras_confirmar(session, turno)
    await session.refresh(turno)
    logger.info("turno confirmado por whatsapp")
    return 200, _acuse_confirmacion(turno)


async def _cancelar_conversacional(
    session: AsyncSession, turno: Turno, *, remitente_hash: str, wa_message_id: str
) -> tuple[int, dict[str, Any]]:
    """`reservado|confirmado→cancelado` en término; tardía → 200+política."""
    if turno.estado == "cancelado":
        fecha, hora = fecha_hora_corta(turno.inicio.astimezone(BA))
        return 200, {
            "mensaje": (
                f"Tu turno del {fecha} a las {hora} ya está cancelado. "
                f"{LINK_GESTION_GENERICO}."
            ),
            "link_gestion": LINK_GESTION_GENERICO,
        }
    if turno.estado not in CANCELABLE_NUCLEO:
        await _auditar_conversacion(
            session,
            accion="conv_terminal",
            turno_id=str(turno.id),
            remitente_hash=remitente_hash,
            wa_message_id=wa_message_id,
            extra={"intent": "cancelar"},
        )
        await session.commit()
        return 422, {
            "problema": "transicion_invalida",
            "detalle": "El turno no admite esa operación en su estado actual.",
        }
    min_horas = min_horas_cancelacion()
    restante = turno.inicio - ahora_utc()
    if restante < timedelta(hours=min_horas):
        await _auditar_conversacion(
            session,
            accion="conv_cancelacion_tardia",
            turno_id=str(turno.id),
            remitente_hash=remitente_hash,
            wa_message_id=wa_message_id,
        )
        await session.commit()
        return 200, {
            "mensaje": texto_politica(),
            "politica": texto_politica(),
            "link_gestion": LINK_GESTION_GENERICO,
        }
    anterior = turno.estado
    turno.estado = "cancelado"
    turno.cancelado_at = ahora_utc()
    turno_id: UUID = turno.id
    await session.commit()
    await session.refresh(turno)
    await repo_auditoria.registrar_auditoria(
        session,
        accion="turno_cancelado",
        entidad="turno",
        entidad_id=str(turno.id),
        diff={
            "estado_anterior": anterior,
            "estado_nuevo": "cancelado",
            "canal": "whatsapp",
        },
        usuario_id=None,
        ip=None,
    )
    await session.commit()
    await session.refresh(turno)
    await svc_avisos.tras_cancelar(session, turno_id=turno_id, motivo="turno_cancelado")
    await session.refresh(turno)
    fecha, hora = fecha_hora_corta(turno.inicio.astimezone(BA))
    logger.info("turno cancelado por whatsapp")
    return 200, {
        "mensaje": (
            f"Tu turno del {fecha} a las {hora} quedó cancelado. "
            f"Gestioná tus turnos aquí: {LINK_GESTION_GENERICO}."
        ),
        "fecha": fecha,
        "hora": hora,
        "sede": _sede_de(turno),
        "link_gestion": LINK_GESTION_GENERICO,
    }


async def _proponer_reprogramacion(
    session: AsyncSession,
    redis: Any,
    turno: Turno,
    *,
    remitente_hash: str,
    wa_message_id: str,
) -> tuple[int, dict[str, Any]]:
    """Propone slots reales y guarda la oferta `wa:conv:*` con TTL."""
    if turno.estado not in {"reservado", "confirmado"}:
        await _auditar_conversacion(
            session,
            accion="conv_terminal",
            turno_id=str(turno.id),
            remitente_hash=remitente_hash,
            wa_message_id=wa_message_id,
            extra={"intent": "reprogramar"},
        )
        await session.commit()
        return 422, {
            "problema": "transicion_invalida",
            "detalle": "El turno no admite esa operación en su estado actual.",
        }
    slots = await _generar_slots_libres(session, turno)
    if not slots:
        return 200, {
            "mensaje": (
                "No hay slots libres próximos. Escribinos más tarde o "
                f"gestioná tu turno aquí: {LINK_GESTION_GENERICO}."
            ),
            "link_gestion": LINK_GESTION_GENERICO,
        }
    vigentes = await _guardar_oferta(redis, remitente_hash, turno.id, slots)
    await _auditar_conversacion(
        session,
        accion="conv_propuesta_slots",
        turno_id=str(turno.id),
        remitente_hash=remitente_hash,
        wa_message_id=wa_message_id,
        extra={"opciones": len(vigentes)},
    )
    await session.commit()
    return 200, _respuesta_propuesta(vigentes)
