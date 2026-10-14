"""Reserva pública sin cuenta C-03 (verificación + idempotencia + rate limit).

Reutiliza el núcleo de creación de C-01 (mismo `fin`, misma exclusión,
mismo shape 409): la DB manda ante carreras (R3). Solo hashes anti-spam
en DB/Redis, jamás PII en claro fuera de la fila `Paciente` (R6).

Deuda explícita: cobro/acreditación real de la seña → C-08 (aquí solo el
link opaco); recurrencias ricas de agenda → C-04; slug `/reservar` → C-10.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.core.settings import settings
from app.models.disponibilidad import ClaveIdempotencia, VerificacionPublica
from app.models.entidades import Paciente
from app.repositories import agenda as repo_agenda
from app.repositories import auditoria as repo_auditoria
from app.schemas.publicos import TurnoPublicoCreate
from app.schemas.turno import TurnoCreate
from app.services.crear_turno import crear_turno

logger = get_logger(__name__)

# Mensajes genéricos idénticos exista o no el par (anti-enumeración, R6).
DETALLE_VERIFICACION = "Se requiere un código de verificación válido."
DETALLE_RATELIMIT = "Demasiados intentos. Reintentá más tarde."
PROBLEMA_VERIFICACION = "verificacion"


def sha_hex(valor: str) -> str:
    """SHA-256 hex del valor canónico (contrato fijado por los tests RED)."""
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def normalizar_telefono(telefono: str) -> str:
    """Canónico para hash y rate: E.164 sin espacios (contrato RED)."""
    return telefono.strip().replace(" ", "")


def _entero_env(nombre: str, base: int) -> int:
    """Tope legible por env en cada llamada (piloto sin cambiar código)."""
    try:
        return int(os.environ.get(nombre, str(base)))
    except ValueError:
        return base


def topes_rate() -> tuple[int, int, int, int]:
    return (
        _entero_env("RATE_PUBLIC_IP_MAX", settings.rate_public_ip_max),
        _entero_env("RATE_PUBLIC_IP_WINDOW_S", settings.rate_public_ip_window_s),
        _entero_env("RATE_PUBLIC_TEL_MAX", settings.rate_public_tel_max),
        _entero_env("RATE_PUBLIC_TEL_WINDOW_S", settings.rate_public_tel_window_s),
    )


def max_intentos_verif() -> int:
    return _entero_env("VERIF_MAX_INTENTOS", settings.verif_max_intentos)


def bloqueo_verif_s() -> int:
    return _entero_env("VERIF_LOCK_S", settings.verif_lock_s)


def ttl_idempotencia_h() -> int:
    return _entero_env("IDEMPOTENCIA_TTL_H", settings.idempotencia_ttl_h)


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _contar_rate(
    redis: Any, clave: str, ventana_s: int
) -> tuple[int | None, int]:
    """INCR+EXPIRE (patrón C-02); `(None, _)` si Redis cae (fail-open)."""
    try:
        conteo = await redis.incr(clave)
        if conteo == 1:
            await redis.expire(clave, ventana_s)
        ttl = await redis.ttl(clave)
        espera = ttl if isinstance(ttl, int) and ttl > 0 else ventana_s
        return int(conteo), espera
    except Exception:  # noqa: BLE001 — fail-open intencional (la DB manda).
        logger.warning("redis no disponible, degradando", extra={"op": "rate"})
        return None, ventana_s


async def chequear_rate(
    redis: Any, *, ip: str | None, telefono_norm: str
) -> tuple[str, int] | None:
    """Rate por IP y por teléfono (hash en la clave, R6). Rate antes de
    procesar: cuenta todos los intentos, exista o no el par.

    Sin `client` (tests ASGI) se usa `"desconocida"` como C-02 (patrón
    `auth._ip`): la dimensión IP sigue contando en ese caso.
    """
    ip_max, ip_win, tel_max, tel_win = topes_rate()
    conteo, espera = await _contar_rate(
        redis, f"rl:publico:ip:{ip or 'desconocida'}", ip_win
    )
    if conteo is not None and conteo > ip_max:
        return DETALLE_RATELIMIT, espera
    conteo, espera = await _contar_rate(
        redis, f"rl:publico:tel:{sha_hex(telefono_norm)}", tel_win
    )
    if conteo is not None and conteo > tel_max:
        return DETALLE_RATELIMIT, espera
    return None


async def _fallo_verificacion(
    session: AsyncSession, fila: VerificacionPublica | None
) -> tuple[dict[str, str], int, int | None]:
    """Fallo genérico: suma intento y bloquea al agotar (→ 422 o 429)."""
    if fila is None:
        return (
            {"problema": PROBLEMA_VERIFICACION, "detalle": DETALLE_VERIFICACION},
            422,
            None,
        )
    fila.intentos = int(fila.intentos) + 1
    if fila.intentos >= max_intentos_verif():
        bloqueo_s = bloqueo_verif_s()
        fila.bloqueada_hasta = ahora_utc() + timedelta(seconds=bloqueo_s)
        await session.commit()
        return {"detalle": DETALLE_RATELIMIT}, 429, bloqueo_s
    await session.commit()
    return (
        {"problema": PROBLEMA_VERIFICACION, "detalle": DETALLE_VERIFICACION},
        422,
        None,
    )


async def chequear_verificacion(
    session: AsyncSession,
    *,
    dni_norm: str,
    telefono_norm: str,
    codigo: str | None,
) -> tuple[dict[str, str], int, int | None] | None:
    """`None` = par verificado (puede reservar); si no, error genérico.

    Costo fijo de hash siempre (mismo tiempo exista o no el par, R6).
    """
    momento = ahora_utc()
    # Hash en costo fijo aunque no haya fila (anti-enumeración por timing).
    codigo_dado_hash = sha_hex((codigo or "").strip())
    fila = (
        await session.execute(
            select(VerificacionPublica).where(
                VerificacionPublica.dni_hash == sha_hex(dni_norm),
                VerificacionPublica.telefono_hash == sha_hex(telefono_norm),
            )
        )
    ).scalar_one_or_none()

    if fila is not None and fila.bloqueada_hasta is not None:
        bloqueada = fila.bloqueada_hasta
        if bloqueada.tzinfo is None:
            bloqueada = bloqueada.replace(tzinfo=timezone.utc)
        if bloqueada > momento:
            espera = int((bloqueada - momento).total_seconds()) or 1
            return {"detalle": DETALLE_RATELIMIT}, 429, espera
    if fila is not None and fila.verificada_en is not None:
        return None

    valida = (
        fila is not None
        and codigo is not None
        and hmac.compare_digest(fila.codigo_hash, codigo_dado_hash)
        and (
            fila.expira_en.replace(tzinfo=timezone.utc)
            if fila.expira_en.tzinfo is None
            else fila.expira_en
        )
        > momento
    )
    if valida:
        assert fila is not None
        fila.verificada_en = momento
        await session.flush()
        return None
    return await _fallo_verificacion(session, fila)


def url_pago_para(turno_id: UUID, token_publico: str) -> str:
    """Link opaco de seña (firma HMAC; el secreto jamás va en claro, R7)."""
    firma = hmac.new(
        settings.pago_link_secret.encode("utf-8"),
        str(turno_id).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    base = settings.pago_link_base.rstrip("/")
    return f"{base}/{token_publico}?firma={firma}"


async def _reservar_clave(
    session: AsyncSession, clave: str
) -> ClaveIdempotencia | None:
    """Reserva la clave; `None` si ya existe (el llamador replays/espera)."""
    fila = ClaveIdempotencia(
        clave=clave, expira_en=ahora_utc() + timedelta(hours=ttl_idempotencia_h())
    )
    try:
        async with session.begin_nested():
            session.add(fila)
            await session.flush()
    except IntegrityError:
        return None
    await session.commit()
    return fila


async def _replay_clave(session: AsyncSession, clave: str) -> dict[str, Any] | None:
    """Respuesta ya completada para la clave, si existe."""
    fila = (
        await session.execute(
            select(ClaveIdempotencia).where(ClaveIdempotencia.clave == clave)
        )
    ).scalar_one_or_none()
    if fila is not None and fila.respuesta_json is not None:
        cuerpo = dict(fila.respuesta_json)
        return cuerpo
    return None


async def _esperar_replay(session: AsyncSession, clave: str) -> dict[str, Any] | None:
    """Espera al dueño concurrente (misma clave, otro in-flight).

    Ventana amplia (30 s): el dueño hace dos commits y el PG efímero de
    test puede tardar segundos por commit; en prod es ms.
    """
    for _ in range(60):
        await asyncio.sleep(0.5)
        cuerpo = await _replay_clave(session, clave)
        if cuerpo is not None:
            return cuerpo
    return None


async def reservar_turno_publico(
    session: AsyncSession,
    redis: Any,
    *,
    datos: TurnoPublicoCreate,
    clave: str,
    ip: str | None,
) -> tuple[dict[str, Any], int, int | None]:
    """`(cuerpo, estado, retry_after)`. 409 fluye como `SlotOcupadoError`
    al handler C-01 (mismo shape + alternativos, sin PII)."""
    telefono_norm = normalizar_telefono(datos.paciente.telefono)
    dni_norm = datos.paciente.dni.strip().replace(".", "")

    if redis is not None:
        freno = await chequear_rate(redis, ip=ip, telefono_norm=telefono_norm)
        if freno is not None:
            detalle, espera = freno
            return {"detalle": detalle}, 429, espera

    replay = await _replay_clave(session, clave)
    if replay is not None:
        return replay, 200, None

    error_verif = await chequear_verificacion(
        session,
        dni_norm=dni_norm,
        telefono_norm=telefono_norm,
        codigo=datos.codigo_verificacion,
    )
    if error_verif is not None:
        cuerpo_err, estado_err, espera_err = error_verif
        return cuerpo_err, estado_err, espera_err

    fila_clave = await _reservar_clave(session, clave)
    if fila_clave is None:
        # Carrera misma clave: replay del dueño (o espera breve).
        replay = await _replay_clave(session, clave) or await _esperar_replay(
            session, clave
        )
        if replay is not None:
            return replay, 200, None
        return {"detalle": DETALLE_RATELIMIT}, 429, 1

    # Reutiliza el paciente existente por DNI (unique) o crea uno nuevo.
    existente = (
        await session.execute(select(Paciente).where(Paciente.dni == dni_norm))
    ).scalar_one_or_none()
    if existente is not None:
        internos = TurnoCreate(
            paciente_id=existente.id,
            profesional_id=datos.profesional_id,
            prestacion_id=datos.prestacion_id,
            inicio=datos.inicio,
            canal="online",
        )
    else:
        internos = TurnoCreate(
            paciente={
                "nombre": datos.paciente.nombre,
                "dni": dni_norm,
                "telefono": telefono_norm,
                "consentimiento_hc": datos.paciente.consentimiento_hc,
            },  # type: ignore[arg-type]
            profesional_id=datos.profesional_id,
            prestacion_id=datos.prestacion_id,
            inicio=datos.inicio,
            canal="online",
        )

    try:
        turno = await crear_turno(session, internos, usuario_id=None, ip=ip)
    except Exception:
        # La clave reservada sin turno debe liberarse (reintento limpio).
        await session.rollback()
        await session.execute(
            delete(ClaveIdempotencia).where(ClaveIdempotencia.clave == clave)
        )
        await session.commit()
        raise

    prestacion = await repo_agenda.obtener_prestacion(session, datos.prestacion_id)
    url_pago = (
        url_pago_para(turno.id, turno.token_publico)
        if prestacion is not None and bool(prestacion.requiere_sena)
        else None
    )
    respuesta: dict[str, Any] = {
        "id": str(turno.id),
        "profesional_id": str(turno.profesional_id),
        "prestacion_id": str(turno.prestacion_id),
        "inicio": turno.inicio.isoformat(),
        "fin": turno.fin.isoformat(),
        "estado": turno.estado,
        "canal": turno.canal,
        "token_publico": turno.token_publico,
        "url_pago": url_pago,
    }
    fila_clave.turno_id = turno.id
    fila_clave.respuesta_json = respuesta
    await repo_auditoria.registrar_auditoria(
        session,
        accion="turno_publico_creado",
        entidad="turno",
        entidad_id=str(turno.id),
        diff={
            "profesional_id": str(turno.profesional_id),
            "prestacion_id": str(turno.prestacion_id),
            "inicio": turno.inicio.isoformat(),
            "fin": turno.fin.isoformat(),
            "estado": turno.estado,
            "canal": turno.canal,
        },
        usuario_id=None,
        ip=ip,
    )
    await session.commit()
    return respuesta, 201, None
