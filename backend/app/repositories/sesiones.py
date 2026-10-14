"""Repositorio de sesiones refresh (fuente de verdad en Postgres, R2)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sesiones import SesionRefresh


async def crear_sesion(
    session: AsyncSession,
    *,
    jti: str,
    usuario_id: uuid.UUID,
    expira_at: datetime,
) -> SesionRefresh:
    fila = SesionRefresh(jti=jti, usuario_id=usuario_id, expira_at=expira_at)
    session.add(fila)
    await session.flush()
    return fila


async def buscar_por_jti(session: AsyncSession, jti: str) -> SesionRefresh | None:
    return await session.get(SesionRefresh, jti)


async def revocar_por_jti(session: AsyncSession, jti: str) -> None:
    await session.execute(
        update(SesionRefresh).where(SesionRefresh.jti == jti).values(revocado=True)
    )
    await session.flush()


async def revocar_cadena_usuario(session: AsyncSession, usuario_id: uuid.UUID) -> None:
    """Revoca TODAS las sesiones del usuario (señal de robo por reuso)."""
    await session.execute(
        update(SesionRefresh)
        .where(SesionRefresh.usuario_id == usuario_id)
        .values(revocado=True)
    )
    await session.flush()


async def eliminar_sesiones_usuario(
    session: AsyncSession, usuario_id: uuid.UUID
) -> None:
    """Solo tests: purga las filas de un usuario sintético (self-cleanup)."""
    await session.execute(
        delete(SesionRefresh).where(SesionRefresh.usuario_id == usuario_id)
    )
