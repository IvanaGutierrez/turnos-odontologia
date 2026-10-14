"""Dependencias FastAPI componibles: identidad + RBAC (design §5).

`get_current_user` (access válido + usuario activo, o 401) → factoría
`require_role(*roles)` (403 genérico + auditoría si el rol no habilita) →
atajo `require_admin()`. Deny-by-default: routers nuevos sin permiso
explícito se rechazan en review (test de inventario, grupo 5).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import decodificar_y_validar
from app.core.settings import settings
from app.domain.auth.matriz import puede
from app.models.entidades import Usuario
from app.repositories import auditoria as repo_auditoria

_bearer = HTTPBearer(auto_error=False)

DETALLE_SIN_AUTH = "No autenticado."
DETALLE_SIN_PERMISO = "Sin permiso."


async def get_current_user(
    request: Request,
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Usuario:
    """Identidad verificable: access válido + usuario activo, o 401 (R6)."""
    if credenciales is None or not credenciales.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=DETALLE_SIN_AUTH
        )
    try:
        claims = decodificar_y_validar(
            credenciales.credentials,
            secreto=settings.jwt_secret,
            tipo_esperado="access",
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=DETALLE_SIN_AUTH
        ) from None
    try:
        usuario_id = uuid.UUID(str(claims["sub"]))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=DETALLE_SIN_AUTH
        ) from None
    usuario = (
        await session.execute(select(Usuario).where(Usuario.id == usuario_id))
    ).scalar_one_or_none()
    if usuario is None or not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=DETALLE_SIN_AUTH
        )
    return usuario


def require_role(
    recurso: str,
) -> Callable[[Request, Usuario, AsyncSession], Coroutine[Any, Any, Usuario]]:
    """Factoría de dependencia: autoriza contra la matriz o 403 + auditoría."""

    async def _verificar(
        request: Request,
        usuario: Annotated[Usuario, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> Usuario:
        if not puede(usuario.rol, recurso):
            await repo_auditoria.registrar_auditoria(
                session,
                accion="acceso_denegado",
                entidad=recurso_auditado(recurso),
                entidad_id=None,
                diff={"recurso": recurso},
                usuario_id=usuario.id,
                ip=_ip(request),
            )
            await session.commit()
            # Genérico: jamás enumera qué roles sí podrían (design riesgo 403).
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=DETALLE_SIN_PERMISO,
            )
        return usuario

    return _verificar


def recurso_auditado(recurso: str) -> str:
    """Entidad para `AuditoriaLog` (los tests esperan `usuario`/`configuracion`)."""
    if recurso == "usuarios":
        return "usuario"
    if recurso == "configuracion_agenda":
        return "configuracion"
    return recurso


def _ip(request: Request) -> str | None:
    if request.client is not None:
        return str(request.client.host)
    return None


async def require_admin(
    request: Request,
    usuario: Annotated[Usuario, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Usuario:
    """Atajo: solo `admin` (403 genérico + auditoría si no)."""
    verificada = require_role("usuarios")
    return await verificada(request, usuario, session)
