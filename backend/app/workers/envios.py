"""Worker de envíos C-06 (design decisiones 2–3 y 5).

Consume avisos vencidos (`programado_para <= ahora`, estados
`pendiente|reintentar`) con reclamo transaccional en `aviso_envio`:

- Éxito → `enviado` + `proveedor_msg_id` durable + `aviso_enviado`.
- Fallo transitorio (5xx/timeout/conexión) → `reintentar` con backoff
  exponencial + jitter en `wa:reintentos` (la DB manda; Redis es hint).
  Agotado `WA_MAX_REINTENTOS=5` → `fallido` + `aviso_fallido` +
  cascada email/SMS (`aviso_fallback`) + `aviso_a_recepcion` en
  `wa:muertos`/auditoría; el turno queda intacto en su estado.
- Fallo permanente (4xx) o paciente `sin_whatsapp` → `fallback` directo
  con `aviso_fallback(canal)`, sin llamar a Meta ni reintentar.
- Duplicado del proveedor (mismo `proveedor_msg_id`) → el `UNIQUE`
  durable lo frena; el webhook responde `200` idempotente.

Redis (`wa:envios`, `wa:reintentos`, `wa:muertos`) es fast-path con
degradación fail-open: `drenar_pendientes()` opera solo con DB + el
transporte inyectado (así la suite corre hermética con fakeredis/sin
redis y `FakeWhatsAppTransport`, R5). R6: logs/diffs solo con
`sha256(tel)[:12]`; jamás cuerpos del proveedor. R0: datos ficticios.
"""

from __future__ import annotations

import asyncio
import os
import random
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import async_session_factory
from app.core.logger import get_logger
from app.core.redis_client import obtener_redis
from app.core.settings import settings
from app.infrastructure.whatsapp.mensajes import (
    TIPOS_UTILITY,
    construir_variables,
    fecha_hora_corta,
    hash_payload,
    huella_destino,
    plantilla_para,
    registro_fallback,
)
from app.infrastructure.whatsapp.transporte import (
    TransporteError,
    obtener_transporte,
)
from app.models.aviso_envio import AvisoEnvio
from app.models.entidades import Turno
from app.repositories import auditoria as repo_auditoria

logger = get_logger(__name__)

ESTADOS_RECLAMABLES: tuple[str, ...] = ("pendiente", "reintentar")


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def max_reintentos() -> int:
    try:
        return int(os.environ.get("WA_MAX_REINTENTOS", str(settings.wa_max_reintentos)))
    except ValueError:
        return settings.wa_max_reintentos


def backoff_base_s() -> float:
    try:
        return float(
            os.environ.get("WA_BACKOFF_BASE_S", str(settings.wa_backoff_base_s))
        )
    except ValueError:
        return settings.wa_backoff_base_s


def calcular_backoff_s(intentos: int) -> float:
    """Backoff exponencial + jitter (`base * 2^(n-1) + [0, base)`)."""
    base = backoff_base_s()
    return base * (2 ** max(intentos - 1, 0)) + random.uniform(0, base)


def es_transitorio(exc: BaseException) -> bool:
    """5xx/timeout/conexión → reintenta; 4xx → fallback sin reintentar."""
    if isinstance(exc, TransporteError):
        return exc.transitorio
    estado = getattr(exc, "estado_http", None)
    if isinstance(estado, int):
        return estado >= 500 or estado == 408
    return True


async def _zadd_backoff(redis: Any | None, aviso_id: UUID, segundos: float) -> None:
    if redis is None:
        return
    try:
        await redis.zadd(
            "wa:reintentos", {str(aviso_id): ahora_utc().timestamp() + segundos}
        )
    except Exception:  # noqa: BLE001 — fail-open (la DB manda).
        logger.warning("redis no disponible, degradando", extra={"op": "backoff"})


async def _dlq(redis: Any | None, turno_id: UUID, tipo: str) -> None:
    if redis is None:
        return
    try:
        await redis.rpush("wa:muertos", f"{turno_id}:{tipo}")
    except Exception:  # noqa: BLE001 — fail-open (la auditoría ya guardó).
        logger.warning("redis no disponible, degradando", extra={"op": "dlq"})


async def _auditar(
    session: AsyncSession,
    *,
    accion: str,
    turno_id: UUID,
    diff: dict[str, Any],
) -> None:
    await repo_auditoria.registrar_auditoria(
        session,
        accion=accion,
        entidad="aviso_envio",
        entidad_id=str(turno_id),
        diff=diff,
    )


async def _fallback_directo(
    session: AsyncSession,
    fila: AvisoEnvio,
    *,
    destino: str,
    motivo: str,
    ahora: datetime,
) -> None:
    """Paciente sin WA o 4xx: email/SMS sin llamar a Meta (RN-NO-04)."""
    prov_email = registro_fallback.enviar_email(
        destino_hash=destino, asunto=fila.tipo_aviso
    )
    fila.estado = "fallback"
    fila.intentos += 1
    await _auditar(
        session,
        accion="aviso_fallback",
        turno_id=fila.turno_id,
        diff={
            "tipo": fila.tipo_aviso,
            "canal": "email",
            "proveedor_ref": prov_email,
            "motivo": motivo,
            "destino": destino,
            "hora": ahora.isoformat(),
        },
    )
    await session.commit()
    logger.info("aviso a fallback", extra={"tipo": fila.tipo_aviso, "destino": destino})


async def _agotar(
    session: AsyncSession,
    fila: AvisoEnvio,
    *,
    destino: str,
    ahora: datetime,
    redis: Any | None,
) -> None:
    """Reintentos agotados: `fallido` + fallback + aviso a recepción.

    El turno conserva su estado y su slot (excepción global KB: el fallo
    externo degrada a manual, nunca pierde el turno).
    """
    fila.estado = "fallido"
    await _auditar(
        session,
        accion="aviso_fallido",
        turno_id=fila.turno_id,
        diff={
            "tipo": fila.tipo_aviso,
            "estado": "fallido",
            "intentos": fila.intentos,
            "destino": destino,
            "hora": ahora.isoformat(),
        },
    )
    prov_email = registro_fallback.enviar_email(
        destino_hash=destino, asunto=fila.tipo_aviso
    )
    await _auditar(
        session,
        accion="aviso_fallback",
        turno_id=fila.turno_id,
        diff={
            "tipo": fila.tipo_aviso,
            "canal": "email",
            "proveedor_ref": prov_email,
            "motivo": "reintentos_agotados",
            "destino": destino,
            "hora": ahora.isoformat(),
        },
    )
    await _auditar(
        session,
        accion="aviso_a_recepcion",
        turno_id=fila.turno_id,
        diff={
            "tipo": fila.tipo_aviso,
            "estado": "fallido",
            "motivo": "reintentos_agotados",
            "destino": destino,
            "hora": ahora.isoformat(),
        },
    )
    await session.commit()
    await _dlq(redis, fila.turno_id, fila.tipo_aviso)
    logger.warning(
        "aviso agotado, a recepción",
        extra={"tipo": fila.tipo_aviso, "destino": destino},
    )


async def drenar_pendientes(
    session: AsyncSession,
    transporte: Any,
    *,
    ahora: datetime | None = None,
    redis: Any | None = None,
) -> dict[str, int]:
    """Drena UN ciclo de avisos vencidos con el transporte inyectado.

    Retorna conteo por resultado (`enviados`, `reintentos`, `fallidos`,
    `fallbacks`, `omitidos`). Cada fila se reclama (`enviando`) y se
    commitea por separado: progreso durable ante caídas.
    """
    momento = ahora or ahora_utc()
    filas = (
        (
            await session.execute(
                select(AvisoEnvio)
                .options(
                    selectinload(AvisoEnvio.turno).selectinload(Turno.paciente),
                    selectinload(AvisoEnvio.turno).selectinload(Turno.sillon),
                )
                .where(
                    AvisoEnvio.estado.in_(ESTADOS_RECLAMABLES),
                    (AvisoEnvio.programado_para.is_(None))
                    | (AvisoEnvio.programado_para <= momento),
                )
                .order_by(AvisoEnvio.programado_para, AvisoEnvio.creado_en)
            )
        )
        .scalars()
        .all()
    )
    resumen = {
        "enviados": 0,
        "reintentos": 0,
        "fallidos": 0,
        "fallbacks": 0,
        "omitidos": 0,
    }
    for fila in filas:
        if fila.tipo_aviso not in TIPOS_UTILITY:
            resumen["omitidos"] += 1
            continue
        fila.estado = "enviando"
        await session.flush()
        turno = fila.turno
        destino = huella_destino(turno.paciente.telefono)
        if bool(getattr(turno.paciente, "sin_whatsapp", False)):
            await _fallback_directo(
                session, fila, destino=destino, motivo="sin_whatsapp", ahora=momento
            )
            resumen["fallbacks"] += 1
            continue
        fecha, hora = fecha_hora_corta(turno.inicio)
        sede = turno.sillon.sede if turno.sillon is not None else "Consultorio"
        variables = construir_variables(
            fecha=fecha,
            hora=hora,
            sede=sede,
            link_gestion=f"/turnos/publicos/{turno.token_publico}",
            nombre_pila=turno.paciente.nombre,
        )
        plantilla = plantilla_para(fila.tipo_aviso)
        fila.payload_hash = hash_payload(plantilla, variables)
        try:
            proveedor_id = await transporte.enviar(
                destino_hash=destino, plantilla=plantilla, variables=variables
            )
        except Exception as exc:  # noqa: BLE001 — degrada, nunca pierde el turno.
            if not es_transitorio(exc):
                await _fallback_directo(
                    session,
                    fila,
                    destino=destino,
                    motivo="numero_invalido",
                    ahora=momento,
                )
                resumen["fallbacks"] += 1
                continue
            fila.intentos += 1
            if fila.intentos >= max_reintentos():
                await _agotar(
                    session, fila, destino=destino, ahora=momento, redis=redis
                )
                resumen["fallidos"] += 1
            else:
                fila.estado = "reintentar"
                await session.commit()
                await _zadd_backoff(redis, fila.id, calcular_backoff_s(fila.intentos))
                logger.info(
                    "aviso a reintento",
                    extra={"tipo": fila.tipo_aviso, "destino": destino},
                )
                resumen["reintentos"] += 1
            continue
        fila.estado = "enviado"
        fila.intentos += 1
        fila.proveedor_msg_id = str(proveedor_id)
        fila.enviado_en = momento
        await _auditar(
            session,
            accion="aviso_enviado",
            turno_id=fila.turno_id,
            diff={
                "tipo": fila.tipo_aviso,
                "estado": "enviado",
                "intentos": fila.intentos,
                "destino": destino,
                "hora": momento.isoformat(),
            },
        )
        try:
            await session.commit()
        except Exception:  # noqa: BLE001 — UNIQUE frena duplicados del proveedor.
            # Duplicado del proveedor (mismo `proveedor_msg_id`): el
            # `UNIQUE` durable frena; se responde idempotente.
            await session.rollback()
            logger.warning(
                "duplicado de proveedor frenado", extra={"tipo": fila.tipo_aviso}
            )
        resumen["enviados"] += 1
        logger.info(
            "aviso enviado", extra={"tipo": fila.tipo_aviso, "destino": destino}
        )
    return resumen


async def main() -> None:
    """Loop del servicio `worker` (compose: `python -m app.workers.envios`)."""
    transporte = obtener_transporte()
    try:
        redis = obtener_redis()
    except Exception:  # noqa: BLE001 — sin Redis la DB manda.
        redis = None
    logger.info("worker de envíos iniciado")
    while True:
        try:
            async with async_session_factory() as session:
                await drenar_pendientes(session, transporte, redis=redis)
        except Exception:  # noqa: BLE001 — el worker nunca muere por un ciclo.
            logger.warning("ciclo de envíos con error, reintentando")
        await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())
