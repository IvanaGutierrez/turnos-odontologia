"""Schemas de auth (capas separadas — R2; jamás `password_hash` afuera, R6)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    # `str` simple (sin `email-validator`): la normalización va en el router.
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    roles: list[str]
    activo: bool
