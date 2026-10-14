"""Repositorio genérico async (SQLAlchemy 2.0, type hints — R1)."""

from __future__ import annotations

from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import BaseModel

T = TypeVar("T", bound=BaseModel)


class RepositorioBase(Generic[T]):
    """CRUD mínimo compartido; las consultas de dominio viven en `agenda`."""

    def __init__(self, session: AsyncSession, modelo: type[T]) -> None:
        self._session = session
        self._modelo = modelo

    async def obtener_por_id(self, id: UUID) -> T | None:
        return await self._session.get(self._modelo, id)

    def agregar(self, entidad: T) -> T:
        self._session.add(entidad)
        return entidad
