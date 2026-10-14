"""Consultas de agenda: solapamientos `[inicio, fin)` sobre estados activos.

El solapamiento aplicativo (`inicio_existente < fin_nuevo AND
fin_existente > inicio_nuevo`) replica la semántica del `EXCLUDE USING gist`
con cota `'[)'`; es solo la vía rápida para el 409 — la DB manda (R3).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entidades import (
    ESTADOS_INACTIVOS,
    Paciente,
    Prestacion,
    Profesional,
    Sillon,
    Turno,
)
from app.repositories.base import RepositorioBase


async def obtener_prestacion(session: AsyncSession, id: UUID) -> Prestacion | None:
    return await RepositorioBase(session, Prestacion).obtener_por_id(id)


async def obtener_profesional(session: AsyncSession, id: UUID) -> Profesional | None:
    return await RepositorioBase(session, Profesional).obtener_por_id(id)


async def obtener_sillon(session: AsyncSession, id: UUID) -> Sillon | None:
    return await RepositorioBase(session, Sillon).obtener_por_id(id)


async def obtener_paciente(session: AsyncSession, id: UUID) -> Paciente | None:
    return await RepositorioBase(session, Paciente).obtener_por_id(id)


async def existe_solape_profesional(
    session: AsyncSession,
    profesional_id: UUID,
    inicio: datetime,
    fin: datetime,
    *,
    excluir_turno_id: UUID | None = None,
) -> bool:
    """Pre-chequeo aplicativo: cuenta sobreturnos como ocupantes (R3).

    El camino normal nunca pisa un sobreturno existente: recibe 409. El
    sobreturno dedicado no pasa por aquí (bypass explícito auditado).
    """
    stmt = (
        select(Turno.id)
        .where(
            Turno.profesional_id == profesional_id,
            Turno.estado.notin_(ESTADOS_INACTIVOS),
            Turno.inicio < fin,
            Turno.fin > inicio,
        )
        .limit(1)
    )
    if excluir_turno_id is not None:
        stmt = stmt.where(Turno.id != excluir_turno_id)
    return (await session.execute(stmt)).first() is not None


async def existe_solape_sillon(
    session: AsyncSession,
    sillon_id: UUID,
    inicio: datetime,
    fin: datetime,
    *,
    excluir_turno_id: UUID | None = None,
) -> bool:
    stmt = (
        select(Turno.id)
        .where(
            Turno.sillon_id == sillon_id,
            Turno.estado.notin_(ESTADOS_INACTIVOS),
            Turno.inicio < fin,
            Turno.fin > inicio,
        )
        .limit(1)
    )
    if excluir_turno_id is not None:
        stmt = stmt.where(Turno.id != excluir_turno_id)
    return (await session.execute(stmt)).first() is not None


async def obtener_turno_por_id(session: AsyncSession, turno_id: UUID) -> Turno | None:
    """Turno con sus relaciones (una ronda, sin N+1 en la operación)."""
    stmt = (
        select(Turno)
        .where(Turno.id == turno_id)
        .options(
            selectinload(Turno.paciente),
            selectinload(Turno.profesional),
            selectinload(Turno.sillon),
            selectinload(Turno.prestacion),
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def listar_turnos_por_token(
    session: AsyncSession, token: str, *, para_actualizar: bool = False
) -> list[Turno]:
    """Filas con ese `token_publico` (una sola query indexada, R6).

    Tras una reprogramación el token vive en dos filas (original
    `reprogramado` + nuevo activo): el servicio elige la no inactiva.
    Con `para_actualizar=True` toma `FOR UPDATE` (confirmar/cancelar en
    carrera: el segundo ve el estado ya mutado, sin doble auditoría).
    """
    stmt = (
        select(Turno)
        .where(Turno.token_publico == token)
        .options(
            selectinload(Turno.paciente),
            selectinload(Turno.profesional),
            selectinload(Turno.sillon),
            selectinload(Turno.prestacion),
        )
    )
    if para_actualizar:
        stmt = stmt.with_for_update()
    return list((await session.execute(stmt)).scalars().all())


async def obtener_hijo_reprogramado(
    session: AsyncSession, original_id: UUID
) -> Turno | None:
    """Turno nuevo enlazado por `reprogramado_de_id` (cadena C-04, R2).

    C-06 lo usa para que cancelar por token tras una reprogramación opere
    sobre el turno vigente (idempotente si ya está `cancelado`).
    """
    stmt = (
        select(Turno)
        .where(Turno.reprogramado_de_id == original_id)
        .options(
            selectinload(Turno.paciente),
            selectinload(Turno.profesional),
            selectinload(Turno.sillon),
            selectinload(Turno.prestacion),
        )
        .order_by(Turno.creado_en.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def listar_turnos_rango(
    session: AsyncSession,
    *,
    desde: datetime,
    hasta: datetime,
    profesional_id: UUID | None = None,
    sillon_id: UUID | None = None,
    limite: int = 500,
) -> list[Turno]:
    """Grilla agregada día/semana en UNA query (design decisión 4).

    Turnos activos que pisan `[desde, hasta)`, ordenados por `inicio`, con
    `selectinload` de profesional/sillón/prestación/paciente-nombre (sin
    N+1). Índices: `(profesional_id, inicio)`, `(sillon_id, inicio)` +
    `(inicio, fin)` de 004. Incluye sobreturnos con su flag (resolución
    operativa en sala).
    """
    stmt = (
        select(Turno)
        .where(
            Turno.inicio < hasta,
            Turno.fin > desde,
            Turno.estado.notin_(ESTADOS_INACTIVOS),
        )
        .order_by(Turno.inicio)
        .options(
            selectinload(Turno.paciente),
            selectinload(Turno.profesional),
            selectinload(Turno.sillon),
            selectinload(Turno.prestacion),
        )
        .limit(limite)
    )
    if profesional_id is not None:
        stmt = stmt.where(Turno.profesional_id == profesional_id)
    if sillon_id is not None:
        stmt = stmt.where(Turno.sillon_id == sillon_id)
    return list((await session.execute(stmt)).scalars().all())
