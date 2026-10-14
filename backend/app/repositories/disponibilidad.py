"""Consultas de agenda pública C-03 (R2: solo queries aquí, sin negocio).

Horarios semanales vigentes + bloqueos puntuales + turnos activos en rango.
La exclusión GiST de C-01 sigue siendo la verdad final (R3): estas queries
proponen slots libres y la DB veta la colisión concurrente.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.disponibilidad import Bloqueo, HorarioProfesional
from app.models.entidades import ESTADOS_INACTIVOS, Turno


async def obtener_horarios_profesional(
    session: AsyncSession, profesional_id: uuid.UUID
) -> list[HorarioProfesional]:
    stmt = (
        select(HorarioProfesional)
        .where(
            HorarioProfesional.profesional_id == profesional_id,
            HorarioProfesional.activo.is_(True),
        )
        .order_by(HorarioProfesional.dia_semana, HorarioProfesional.hora_inicio)
    )
    return list((await session.execute(stmt)).scalars().all())


def horario_vigente_en(horario: HorarioProfesional, dia: date) -> bool:
    """Predicado de vigencia (`vigente_desde/hasta` NULL = sin acotar)."""
    desde_ok = horario.vigente_desde is None or dia >= horario.vigente_desde
    hasta_ok = horario.vigente_hasta is None or dia <= horario.vigente_hasta
    return desde_ok and hasta_ok


async def obtener_bloqueos_en_rango(
    session: AsyncSession,
    profesional_id: uuid.UUID,
    desde: datetime,
    hasta: datetime,
) -> list[Bloqueo]:
    """Bloqueos que pisan `[desde, hasta)`: del profesional o globales/sede.

    Los bloqueos de sillón/sede (`profesional_id NULL`) también excluyen
    (conservador: el endpoint público no recibe `sillon_id`).
    """
    stmt = (
        select(Bloqueo)
        .where(
            Bloqueo.desde < hasta,
            Bloqueo.hasta > desde,
            (
                (Bloqueo.profesional_id == profesional_id)
                | (Bloqueo.profesional_id.is_(None))
            ),
        )
        .order_by(Bloqueo.desde)
    )
    return list((await session.execute(stmt)).scalars().all())


async def obtener_turnos_activos_en_rango(
    session: AsyncSession,
    profesional_id: uuid.UUID,
    desde: datetime,
    hasta: datetime,
) -> list[Turno]:
    """Turnos activos del profesional que pisan `[desde, hasta)` (C-01 §solape)."""
    stmt = (
        select(Turno)
        .where(
            Turno.profesional_id == profesional_id,
            Turno.estado.notin_(ESTADOS_INACTIVOS),
            Turno.inicio < hasta,
            Turno.fin > desde,
        )
        .order_by(Turno.inicio)
    )
    return list((await session.execute(stmt)).scalars().all())
