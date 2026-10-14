"""Scheduler de avisos C-06 dirigido por eventos de dominio (design decisión 7).

- Al `reservado→confirmado`: encola `confirmacion` inmediata
  (`programado_para = ahora`) + programa `recordatorio_24h`
  (`inicio - RECORDATORIO_24H_MIN`) y `aviso_3h` (`inicio - AVISO_3H_MIN`)
  solo si la ventana futura existe. Reloj inyectable (`ahora` explícito;
  en prod `ahora_utc`, en tests freezegun `America/Argentina/Buenos_Aires`).
- Ante `reprogramado`: cancela pendientes del turno viejo y programa el
  nuevo. Ante `cancelado/ausente/atendido/presente`: cancela pendientes
  (idempotente, sin error si no existen).
- Idempotencia en dos niveles (design decisión 3): `SET aviso:{turno}:{tipo}
  NX EX` en Redis (rápida, fail-open) + `UNIQUE (turno_id, tipo_aviso)`
  durable (la DB manda). Cada encolado audita `aviso_encolado` sin PII
  (solo `sha256(tel)[:12]`, R6) y empuja el job a `wa:envios` (fail-open:
  si Redis cae, la DB manda y el worker drena por `programado_para`).
- Veto marketing (RN-NO-01): cualquier tipo fuera de los 3 utility se
  rechaza con `TipoAvisoNoPermitidoError` (→ 422), sin encolar ni llamar
  al proveedor.

R0: teléfonos ficticios `+54 9 11 15-000-XXXX` en tests. R1: hints.
R2: servicio separado de `models/`/`schemas/`/`repositories/`.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import TipoAvisoNoPermitidoError
from app.core.logger import get_logger
from app.core.redis_client import obtener_redis
from app.core.settings import settings
from app.infrastructure.whatsapp.mensajes import TIPOS_UTILITY, huella_destino
from app.models.aviso_envio import AvisoEnvio
from app.models.entidades import Turno
from app.repositories import auditoria as repo_auditoria

logger = get_logger(__name__)

# Estados que admiten avisos programados (el resto cancela pendientes).
ESTADOS_PROGRAMABLES: frozenset[str] = frozenset({"reservado", "confirmado"})

# El turno jamás muta por un fallo de notificación (excepción global KB).
CLAVE_NX_TTL_S = 7 * 24 * 3600


def ahora_utc() -> datetime:
    """Reloj inyectable (tests: freezegun; prod: UTC real)."""
    return datetime.now(timezone.utc)


def ventanas_min() -> tuple[int, int]:
    """`(24h_min, 3h_min)` legibles por env en cada llamada (piloto)."""
    try:
        v24 = int(
            os.environ.get("RECORDATORIO_24H_MIN", str(settings.recordatorio_24h_min))
        )
    except ValueError:
        v24 = settings.recordatorio_24h_min
    try:
        v3 = int(os.environ.get("AVISO_3H_MIN", str(settings.aviso_3h_min)))
    except ValueError:
        v3 = settings.aviso_3h_min
    return v24, v3


def validar_tipo(tipo: str) -> None:
    """Veto marketing: fuera de los 3 utility → 422 (RN-NO-01)."""
    if tipo not in TIPOS_UTILITY:
        raise TipoAvisoNoPermitidoError(tipo)


async def _marcar_nx(redis: Any | None, turno_id: UUID, tipo: str) -> None:
    """Deduplicación rápida `SET NX EX` (fail-open: Redis nunca bloquea)."""
    if redis is None:
        return
    try:
        await redis.set(f"aviso:{turno_id}:{tipo}", "1", nx=True, ex=CLAVE_NX_TTL_S)
    except Exception:  # noqa: BLE001 — fail-open intencional (la DB manda).
        logger.warning("redis no disponible, degradando", extra={"op": "aviso_nx"})


async def _empujar_cola(redis: Any | None, turno_id: UUID, tipo: str) -> None:
    """Job a `wa:envios` (fail-open: el worker también drena por DB)."""
    if redis is None:
        return
    try:
        await redis.rpush("wa:envios", f"{turno_id}:{tipo}")
    except Exception:  # noqa: BLE001 — fail-open intencional (la DB manda).
        logger.warning("redis no disponible, degradando", extra={"op": "aviso_cola"})


async def encolar_aviso(
    session: AsyncSession,
    *,
    turno_id: UUID,
    tipo_aviso: str,
    programado_para: datetime | None,
    destino_hash: str,
    redis: Any | None = None,
) -> bool:
    """Encola UN aviso utility (idempotente: `True` si lo creó).

    Veta tipos fuera de scope (422), deduplica por `UNIQUE` durable y
    audita `aviso_encolado` sin PII. Ante carrera concurrente retorna
    `False` (el otro encolado ganó; exactamente-una-vez observable).
    """
    validar_tipo(tipo_aviso)
    await _marcar_nx(redis, turno_id, tipo_aviso)
    fila = AvisoEnvio(
        turno_id=turno_id,
        tipo_aviso=tipo_aviso,
        estado="pendiente",
        programado_para=programado_para,
    )
    session.add(fila)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return False
    await repo_auditoria.registrar_auditoria(
        session,
        accion="aviso_encolado",
        entidad="aviso_envio",
        entidad_id=str(turno_id),
        diff={
            "tipo": tipo_aviso,
            "estado": "pendiente",
            "programado_para": programado_para.isoformat() if programado_para else None,
            "destino": destino_hash,
        },
    )
    await session.flush()
    await _empujar_cola(redis, turno_id, tipo_aviso)
    logger.info("aviso encolado", extra={"tipo": tipo_aviso, "destino": destino_hash})
    return True


async def programar_avisos_confirmacion(
    session: AsyncSession,
    turno: Turno,
    *,
    ahora: datetime,
    redis: Any | None = None,
) -> list[str]:
    """Secuencia `confirmacion` + 24 h + 3 h (ventanas futuras existentes).

    Retorna los tipos efectivamente creados (idempotente: repetir ante el
    mismo turno confirmado no duplica por el `UNIQUE` durable).
    """
    v24, v3 = ventanas_min()
    destino = huella_destino(turno.paciente.telefono)
    planes: list[tuple[str, datetime | None]] = [("confirmacion", ahora)]
    restante = turno.inicio - ahora
    if restante > timedelta(minutes=v24):
        planes.append(("recordatorio_24h", turno.inicio - timedelta(minutes=v24)))
    if restante > timedelta(minutes=v3):
        planes.append(("aviso_3h", turno.inicio - timedelta(minutes=v3)))
    creados: list[str] = []
    for tipo, programado in planes:
        if await encolar_aviso(
            session,
            turno_id=turno.id,
            tipo_aviso=tipo,
            programado_para=programado,
            destino_hash=destino,
            redis=redis,
        ):
            creados.append(tipo)
    await session.commit()
    return creados


async def cancelar_pendientes(
    session: AsyncSession, *, turno_id: UUID, motivo: str = "turno_cancelado"
) -> int:
    """Cancela pendientes/reintentos del turno (idempotente, sin error).

    Retorna la cantidad cancelada. Los `enviado/fallido/fallback` son
    historia y no se tocan.
    """
    from sqlalchemy import select

    filas = (
        (
            await session.execute(
                select(AvisoEnvio).where(
                    AvisoEnvio.turno_id == turno_id,
                    AvisoEnvio.estado.in_(["pendiente", "reintentar"]),
                )
            )
        )
        .scalars()
        .all()
    )
    for fila in filas:
        fila.estado = "cancelado"
    if filas:
        await repo_auditoria.registrar_auditoria(
            session,
            accion="aviso_cancelado",
            entidad="aviso_envio",
            entidad_id=str(turno_id),
            diff={"cancelados": len(filas), "motivo": motivo},
        )
    await session.commit()
    return len(filas)


async def tras_confirmar(
    session: AsyncSession, turno: Turno, *, ahora: datetime | None = None
) -> list[str]:
    """Hook post-`confirmado` (staff + autogestión): programa la secuencia."""
    try:
        redis = obtener_redis()
    except Exception:  # noqa: BLE001 — sin Redis la DB manda.
        redis = None
    return await programar_avisos_confirmacion(
        session, turno, ahora=ahora or ahora_utc(), redis=redis
    )


async def tras_cancelar(
    session: AsyncSession, *, turno_id: UUID, motivo: str = "turno_cancelado"
) -> int:
    """Hook post-estado terminal: cancela pendientes (turno intacto)."""
    return await cancelar_pendientes(session, turno_id=turno_id, motivo=motivo)


async def tras_reprogramar(
    session: AsyncSession,
    *,
    original_id: UUID,
    nuevo: Turno,
    ahora: datetime | None = None,
) -> list[str]:
    """Hook post-reprogramación: cancela el viejo, programa el nuevo."""
    await cancelar_pendientes(session, turno_id=original_id, motivo="reprogramado")
    if nuevo.estado not in ESTADOS_PROGRAMABLES:
        return []
    try:
        redis = obtener_redis()
    except Exception:  # noqa: BLE001 — sin Redis la DB manda.
        redis = None
    return await programar_avisos_confirmacion(
        session, nuevo, ahora=ahora or ahora_utc(), redis=redis
    )
