"""Consultas de pagos de seña C-08 (solo lectura/claim, R2).

La idempotencia la garantiza la DB (UNIQUEs + reclamo por estado en el
servicio); aquí solo selects parametrizados por IDs, sin PII (R6).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entidades import Prestacion, Turno
from app.models.pago import Pago


async def obtener_por_mp(
    session: AsyncSession, mp_payment_id: str, *, para_actualizar: bool = False
) -> Pago | None:
    """Pago por `mp_payment_id` (`FOR UPDATE` para reclamar sin carrera)."""
    stmt = select(Pago).where(Pago.mp_payment_id == mp_payment_id)
    if para_actualizar:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def pendiente_por_turno(
    session: AsyncSession, turno_id: UUID, *, para_actualizar: bool = False
) -> Pago | None:
    """El `pendiente` del turno, si hay (UNICO por índice parcial).

    Con `para_actualizar=True` toma `FOR UPDATE`: el reclamo del
    webhook serializa (el segundo ve el estado ya mutado, sin doble
    efecto sobre la MISMA fila — el UNIQUE solo cubre filas nuevas).
    """
    stmt = (
        select(Pago)
        .where(Pago.turno_id == turno_id, Pago.estado == "pendiente")
        .order_by(Pago.creado_en.desc())
    )
    if para_actualizar:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalars().first()


async def ultimo_por_turno(session: AsyncSession, turno_id: UUID) -> Pago | None:
    """Último pago del turno (para exponer `estado_pago` sin PII)."""
    stmt = select(Pago).where(Pago.turno_id == turno_id).order_by(Pago.creado_en.desc())
    return (await session.execute(stmt)).scalars().first()


async def acreditado_por_turno(session: AsyncSession, turno_id: UUID) -> Pago | None:
    """Pago `acreditado` del turno (guarda de confirmación RN-PA-02)."""
    stmt = (
        select(Pago)
        .where(Pago.turno_id == turno_id, Pago.estado == "acreditado")
        .order_by(Pago.creado_en.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def hubo_rechazo(session: AsyncSession, turno_id: UUID) -> bool:
    """Si el turno tuvo un pago `rechazado` (sigue visible al reintentar)."""
    stmt = (
        select(Pago.id)
        .where(Pago.turno_id == turno_id, Pago.estado == "rechazado")
        .limit(1)
    )
    return (await session.execute(stmt)).first() is not None


async def candidatos_sena_pendiente(session: AsyncSession) -> list[Turno]:
    """Turnos `reservado` con seña requerida y sin pago acreditado.

    Fallback de vinculación cuando MP no porta `metadata` (el Fake de
    tests no la porta; MP real sí vía `metadata`/`external_reference`):
    solo se usa si hay EXACTAMENTE UN candidato y el monto coincide
    (ante ambigüedad jamás se atribuye dinero a ciegas, CRITICO).
    """
    stmt = (
        select(Turno)
        .join(Prestacion, Prestacion.id == Turno.prestacion_id)
        .where(
            Turno.estado == "reservado",
            Prestacion.requiere_sena.is_(True),
        )
        .where(
            ~select(Pago.id)
            .where(
                Pago.turno_id == Turno.id,
                Pago.estado == "acreditado",
            )
            .exists()
        )
        .options(selectinload(Turno.prestacion))
        .order_by(Turno.creado_en.desc())
    )
    return list((await session.execute(stmt)).scalars().all())
