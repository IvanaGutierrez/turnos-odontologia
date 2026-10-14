"""Contratos de gestión de usuarios C-11 (capas separadas — R2).

- `POST /api/v1/usuarios {email, rol, password}` (solo `admin`) → `201`
  con `{id, email, rol, activo}` (jamás `password_hash` — R6).
- `GET /api/v1/usuarios?page&page_size` (solo `admin`) → `200` paginado.
- `GET /api/v1/usuarios/:id` (solo `admin`) → `200` sin hash.
- `PATCH /api/v1/usuarios/:id {rol?, activo?}` (solo `admin`) → `200`;
  rol fuera del enum → `422` (validación pydantic).
- `DELETE /api/v1/usuarios/:id` (solo `admin`) → baja lógica
  (`activo=false`, nunca borrado físico).

Todo dato sintético (R0); type hints siempre (R1).
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RolUsuario = Literal["admin", "odontologo", "recepcion"]

ROLES_USUARIO: tuple[str, ...] = ("admin", "odontologo", "recepcion")


class UsuarioCreate(BaseModel):
    """Alta interna (solo admin crea; sin alta pública — non-goal C-11)."""

    model_config = ConfigDict(extra="ignore")

    # `str` simple (sin `email-validator`, patrón de `schemas/auth.py`).
    email: str = Field(min_length=3, max_length=255)
    rol: RolUsuario
    password: str = Field(min_length=8, max_length=256)


class UsuarioUpdate(BaseModel):
    """Cambio de `rol` y/o `activo` (al menos un campo)."""

    model_config = ConfigDict(extra="ignore")

    rol: RolUsuario | None = None
    activo: bool | None = None


class UsuarioOut(BaseModel):
    """Salida pública de usuario (allowlist: jamás `password_hash` — R6)."""

    id: uuid.UUID
    email: str
    rol: str
    activo: bool


class UsuarioLista(BaseModel):
    """Lista paginada de usuarios (solo admin)."""

    items: list[UsuarioOut]
    total: int
    page: int
    page_size: int
