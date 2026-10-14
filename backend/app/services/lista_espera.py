"""Servicio de lista de espera inteligente (C-14).

La oferta NO reserva el slot (decisión madre del design): el turno recién
se inserta al acreditarse la seña, bajo el GiST vigente (R3). Todo dato
sintético en tests (R0); type hints siempre (R1); jamás PII en diffs,
mensajes ni logs (R6, Ley 25.326).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.core.settings import settings
from app.infrastructure.whatsapp.mensajes import huella_destino
from app.models.entidades import Paciente, Prestacion, Profesional, Sillon, Turno
from app.models.lista_espera import ListaEspera, OfertaEspera
from app.repositories import auditoria as repo_auditoria
from app.core.exceptions import (
    EntidadNoEncontradaError,
    ValidacionARError,
)

# Top-N de ofertados por hueco (design §5; default 3).
TOP_N_DEFAULT: int = 3
# TTL de cada oferta pendiente en minutos (default 30).
OFERTA_TTL_MIN_DEFAULT: int = 30
# Pesos del scoring (design: ventana + historial + valor).
W_VENT: float = 0.5
W_HIST: float = 0.3
W_VALOR: float = 0.2
# Plantilla utility de oferta (4.º tipo; el alta en TIPOS_UTILITY la
# registra el módulo de mensajes al cablear C-14).
PLANTILLA_OFERTA_DEFAULT: str = "oferta_lista_espera_utility"

logger = get_logger(__name__)


def _top_n() -> int:
    return int(getattr(settings, "lista_espera_top_n", TOP_N_DEFAULT))


def _ttl_min() -> int:
    return int(getattr(settings, "lista_espera_oferta_ttl_min", OFERTA_TTL_MIN_DEFAULT))


def _plantilla_oferta() -> str:
    return str(getattr(settings, "wa_template_oferta", PLANTILLA_OFERTA_DEFAULT))


def calcular_score(
    ventana_desde: datetime,
    ventana_hasta: datetime,
    historial_ratio: float = 0.5,
    valor_prestacion: float = 10000.0,
) -> tuple[float, dict[str, Any]]:
    """Score 0-100 normalizado: `100*(p_vent*w_vent + p_hist*w_hist + p_valor*w_valor)`.

    - `p_vent`: ventana angosta ⇒ más flexible ⇒ mayor prioridad.
    - `p_hist`: ratio de asistencia (0-1; sin historial ⇒ 0.5 neutral).
    - `p_valor`: valor relativo de la prestación (0-1, tope 1.0).
    """
    dias_ventana = max(
        1.0, (ventana_hasta - ventana_desde).total_seconds() / 86400.0
    )
    p_vent = 1.0 / (1.0 + dias_ventana / 7.0)
    p_hist = min(1.0, max(0.0, float(historial_ratio)))
    p_valor = min(1.0, max(0.0, float(valor_prestacion) / 20000.0))
    total = 100.0 * (p_vent * W_VENT + p_hist * W_HIST + p_valor * W_VALOR)
    componentes = {
        "p_vent": round(p_vent, 4),
        "p_hist": round(p_hist, 4),
        "p_valor": round(p_valor, 4),
        "w_vent": W_VENT,
        "w_hist": W_HIST,
        "w_valor": W_VALOR,
    }
    return round(total, 4), componentes


async def _ratio_historial(
    sesion: AsyncSession, paciente_id: uuid.UUID
) -> float:
    """Ratio de asistencia del paciente (atendidos / totales con historial)."""
    total = await sesion.scalar(
        select(func.count(Turno.id)).where(
            Turno.paciente_id == paciente_id,
            Turno.estado.in_(("atendido", "ausente")),
        )
    )
    if not total:
        return 0.5
    atendidos = await sesion.scalar(
        select(func.count(Turno.id)).where(
            Turno.paciente_id == paciente_id,
            Turno.estado == "atendido",
        )
    )
    return float(atendidos or 0) / float(total)


async def crear_entrada_lista_espera(
    sesion: AsyncSession,
    *,
    paciente_id: uuid.UUID,
    prestacion_id: uuid.UUID,
    profesional_id: uuid.UUID | None,
    ventana_desde: datetime,
    ventana_hasta: datetime,
) -> ListaEspera:
    if ventana_desde >= ventana_hasta:
        raise ValidacionARError("La ventana desde debe ser anterior a hasta.")

    ahora = datetime.now(timezone.utc)
    if ventana_hasta < ahora:
        raise ValidacionARError("La ventana no puede estar en el pasado.")

    paciente = await sesion.get(Paciente, paciente_id)
    if paciente is None:
        raise EntidadNoEncontradaError("Paciente no encontrado.")
    prestacion = await sesion.get(Prestacion, prestacion_id)
    if prestacion is None:
        raise EntidadNoEncontradaError("Prestación no encontrada.")
    if profesional_id is not None:
        prof = await sesion.get(Profesional, profesional_id)
        if prof is None:
            raise EntidadNoEncontradaError("Profesional no encontrado.")

    ratio = await _ratio_historial(sesion, paciente_id)
    score, componentes = calcular_score(
        ventana_desde,
        ventana_hasta,
        historial_ratio=ratio,
        valor_prestacion=float(prestacion.precio_base or 10000.0),
    )

    entrada = ListaEspera(
        paciente_id=paciente_id,
        prestacion_id=prestacion_id,
        profesional_id=profesional_id,
        ventana_desde=ventana_desde,
        ventana_hasta=ventana_hasta,
        score=score,
        score_componentes=componentes,
        estado="activa",
    )
    sesion.add(entrada)
    await sesion.flush()
    await sesion.refresh(entrada)
    return entrada


async def dar_de_baja_lista_espera(
    sesion: AsyncSession,
    espera_id: uuid.UUID,
) -> ListaEspera:
    entrada = await sesion.get(ListaEspera, espera_id)
    if entrada is None:
        raise EntidadNoEncontradaError("Entrada de lista de espera no encontrada.")

    entrada.estado = "expirada"
    pendientes = (
        await sesion.execute(
            select(OfertaEspera).where(
                OfertaEspera.lista_espera_id == espera_id,
                OfertaEspera.estado == "pendiente",
            )
        )
    ).scalars().all()
    for oferta in pendientes:
        oferta.estado = "expirada"
    await sesion.flush()
    await sesion.refresh(entrada)
    return entrada


async def _elegibles(
    sesion: AsyncSession,
    *,
    prestacion_id: uuid.UUID,
    profesional_id: uuid.UUID | None,
    inicio: datetime,
    excluidas: set[uuid.UUID] | None = None,
    limite: int,
) -> list[ListaEspera]:
    """Entradas `activa` que cubren el hueco, ordenadas por score + antigüedad."""
    stmt = (
        select(ListaEspera)
        .where(
            ListaEspera.estado == "activa",
            ListaEspera.prestacion_id == prestacion_id,
            ListaEspera.ventana_desde <= inicio,
            ListaEspera.ventana_hasta >= inicio,
        )
        .order_by(ListaEspera.score.desc(), ListaEspera.creado_en.asc())
        .limit(limite)
    )
    if profesional_id is not None:
        stmt = stmt.where(
            (ListaEspera.profesional_id.is_(None))
            | (ListaEspera.profesional_id == profesional_id)
        )
    filas = (await sesion.execute(stmt)).scalars().all()
    if excluidas:
        filas = [f for f in filas if f.id not in excluidas]
    return list(filas)


def _link_sena(preference_id: str) -> str:
    base = str(settings.pago_link_base).rstrip("/")
    return f"{base}/{preference_id}"


async def _enviar_oferta(
    sesion: AsyncSession,
    entrada: ListaEspera,
    oferta: OfertaEspera,
    inicio: datetime,
    transporte: Any,
) -> None:
    """Blast 1-a-1 con SOLO el slot propio; caídas ⇒ aviso a recepción."""
    paciente = await sesion.get(Paciente, entrada.paciente_id)
    sede = "Consultorio"
    if oferta.sillon_id is not None:
        sillon = await sesion.get(Sillon, oferta.sillon_id)
        if sillon is not None and sillon.sede:
            sede = str(sillon.sede)
    # Solo el slot propio del destinatario (R6): claves dentro del
    # vocabulario permitido; el nombre identifica 1-a-1 sin datos de otros.
    variables: dict[str, str] = {
        "fecha": inicio.strftime("%Y-%m-%d"),
        "hora": inicio.strftime("%H:%M"),
        "sede": sede,
        "link_gestion": _link_sena(str(oferta.mp_preference_id or oferta.id)),
    }
    if paciente is not None:
        variables["nombre_pila"] = paciente.nombre
    try:
        if paciente is None or paciente.sin_whatsapp:
            raise RuntimeError("sin_canal_whatsapp")
        await transporte.enviar(
            destino_hash=huella_destino(paciente.telefono),
            plantilla=_plantilla_oferta(),
            variables=variables,
        )
        await repo_auditoria.registrar_auditoria(
            sesion,
            accion="oferta_enviada",
            entidad="oferta_espera",
            entidad_id=str(oferta.id),
            diff={
                "lista_espera_id": str(entrada.id),
                "hueco_origen_id": str(oferta.hueco_origen_id),
                "expira_at": oferta.expira_at.isoformat(),
                "score": float(entrada.score or 0.0),
            },
        )
    except Exception as exc:
        # Fallback: la oferta queda registrada (el TTL corre) y el hueco
        # sigue libre; recepción lo ve en su grilla.
        logger.warning(
            "oferta sin blast directo, deriva a recepción",
            extra={"oferta_id": str(oferta.id), "error": type(exc).__name__},
        )
        await repo_auditoria.registrar_auditoria(
            sesion,
            accion="aviso_a_recepcion",
            entidad="oferta_espera",
            entidad_id=str(oferta.id),
            diff={
                "lista_espera_id": str(entrada.id),
                "hueco_origen_id": str(oferta.hueco_origen_id),
                "motivo": "transporte_whatsapp_no_disponible",
            },
        )


async def ofertar_hueco_liberado(
    sesion: AsyncSession,
    hueco: dict[str, Any],
    transporte: Any,
) -> list[OfertaEspera]:
    """Ranquea elegibles del hueco y blastea al top-N (worker C-14).

    `hueco`: `{hueco_origen_id, profesional_id, sillon_id?,
    prestacion_id, inicio, fin}`. Las entradas con ventana vencida pasan
    a `expirada` sin blast ni mensajes.
    """
    ahora = datetime.now(timezone.utc)
    inicio = hueco["inicio"]
    if isinstance(inicio, str):
        inicio = datetime.fromisoformat(inicio)
    fin = hueco["fin"]
    if isinstance(fin, str):
        fin = datetime.fromisoformat(fin)

    # Ventanas vencidas: expiran sin blast.
    vencidas = (
        await sesion.execute(
            select(ListaEspera).where(
                ListaEspera.estado == "activa",
                ListaEspera.ventana_hasta < ahora,
            )
        )
    ).scalars().all()
    for entrada in vencidas:
        entrada.estado = "expirada"
    await sesion.flush()

    prestacion_id = hueco["prestacion_id"]
    if isinstance(prestacion_id, str):
        prestacion_id = uuid.UUID(prestacion_id)
    profesional_id = hueco.get("profesional_id")
    if isinstance(profesional_id, str):
        profesional_id = uuid.UUID(profesional_id)
    sillon_id = hueco.get("sillon_id")
    if isinstance(sillon_id, str):
        sillon_id = uuid.UUID(sillon_id)
    hueco_origen_id = hueco["hueco_origen_id"]
    if isinstance(hueco_origen_id, str):
        hueco_origen_id = uuid.UUID(hueco_origen_id)

    elegibles = await _elegibles(
        sesion,
        prestacion_id=prestacion_id,
        profesional_id=profesional_id,
        inicio=inicio,
        limite=_top_n(),
    )
    creadas: list[OfertaEspera] = []
    for entrada in elegibles:
        prof_oferta = profesional_id or entrada.profesional_id
        if prof_oferta is None:
            continue
        oferta = OfertaEspera(
            lista_espera_id=entrada.id,
            hueco_origen_id=hueco_origen_id,
            profesional_id=prof_oferta,
            sillon_id=sillon_id,
            inicio=inicio,
            fin=fin,
            expira_at=ahora + timedelta(minutes=_ttl_min()),
            estado="pendiente",
            mp_preference_id=f"oferta-{uuid.uuid4().hex}",
        )
        try:
            async with sesion.begin_nested():
                sesion.add(oferta)
                await sesion.flush()
        except IntegrityError:
            # Doble blast concurrente del mismo hueco: la DB manda
            # (UNIQUE parcial pendiente por entrada+hueco).
            continue
        entrada.estado = "ofertada"
        await sesion.flush()
        await _enviar_oferta(sesion, entrada, oferta, inicio, transporte)
        await sesion.flush()
        creadas.append(oferta)
    await sesion.flush()
    return creadas


async def barrer_ofertas_expiradas(
    sesion: AsyncSession,
    transporte: Any,
) -> int:
    """Barredor de TTL: `pendiente` vencida ⇒ `expirada` + re-oferta al siguiente.

    Devuelve la cantidad de ofertas expiradas. Cada entrada vencida vuelve
    a `activa` y el hueco se re-oferta al siguiente elegible aún no
    ofertado para ese hueco.
    """
    ahora = datetime.now(timezone.utc)
    vencidas = (
        await sesion.execute(
            select(OfertaEspera).where(
                OfertaEspera.estado == "pendiente",
                OfertaEspera.expira_at <= ahora,
            )
        )
    ).scalars().all()
    if not vencidas:
        return 0

    por_hueco: dict[str, OfertaEspera] = {}
    for oferta in vencidas:
        oferta.estado = "expirada"
        await repo_auditoria.registrar_auditoria(
            sesion,
            accion="oferta_expirada",
            entidad="oferta_espera",
            entidad_id=str(oferta.id),
            diff={
                "lista_espera_id": str(oferta.lista_espera_id),
                "hueco_origen_id": str(oferta.hueco_origen_id),
            },
        )
        entrada = await sesion.get(ListaEspera, oferta.lista_espera_id)
        if entrada is not None and entrada.estado == "ofertada":
            entrada.estado = "activa"
        por_hueco.setdefault(str(oferta.hueco_origen_id), oferta)
    await sesion.flush()

    for oferta_ref in por_hueco.values():
        ya_ofertadas = {
            row
            for row in (
                await sesion.execute(
                    select(OfertaEspera.lista_espera_id).where(
                        OfertaEspera.hueco_origen_id == oferta_ref.hueco_origen_id,
                    )
                )
            ).scalars().all()
        }
        pendientes = await sesion.scalar(
            select(func.count(OfertaEspera.id)).where(
                OfertaEspera.hueco_origen_id == oferta_ref.hueco_origen_id,
                OfertaEspera.estado == "pendiente",
            )
        )
        cupo = _top_n() - int(pendientes or 0)
        if cupo <= 0:
            continue
        entrada_ref = await sesion.get(ListaEspera, oferta_ref.lista_espera_id)
        prestacion_id = (
            entrada_ref.prestacion_id if entrada_ref is not None else None
        )
        if prestacion_id is None:
            continue
        siguientes = await _elegibles(
            sesion,
            prestacion_id=prestacion_id,
            profesional_id=oferta_ref.profesional_id,
            inicio=oferta_ref.inicio,
            excluidas={uuid.UUID(str(e)) for e in ya_ofertadas},
            limite=cupo,
        )
        for entrada in siguientes:
            nueva = OfertaEspera(
                lista_espera_id=entrada.id,
                hueco_origen_id=oferta_ref.hueco_origen_id,
                profesional_id=oferta_ref.profesional_id,
                sillon_id=oferta_ref.sillon_id,
                inicio=oferta_ref.inicio,
                fin=oferta_ref.fin,
                expira_at=ahora + timedelta(minutes=_ttl_min()),
                estado="pendiente",
                mp_preference_id=f"oferta-{uuid.uuid4().hex}",
            )
            try:
                async with sesion.begin_nested():
                    sesion.add(nueva)
                    await sesion.flush()
            except IntegrityError:
                continue
            entrada.estado = "ofertada"
            await sesion.flush()
            await _enviar_oferta(
                sesion, entrada, nueva, oferta_ref.inicio, transporte
            )
            await sesion.flush()
    await sesion.flush()
    return len(vencidas)
