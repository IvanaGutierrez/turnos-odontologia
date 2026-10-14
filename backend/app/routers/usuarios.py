"""Router de gestión de usuarios C-11 (spec `admin/gestion-usuarios`).

RBAC (matriz C-02 extendida, deny-by-default): `usuarios → {admin}`;
recepción/odontólogo → `403` genérico + `acceso_denegado` (vía
`require_role`, entidad `usuario`); sin JWT → `401`. Reemplaza al probe
`GET /usuarios` de `routers/rbac.py` (lista plana) con el CRUD real.

- `GET /usuarios?page&page_size` → `200` paginado sin `password_hash`.
- `POST /usuarios` → `201` + `usuario_creado`; duplicado → `409`;
  rol inválido → `422` (pydantic).
- `GET /usuarios/:id` → `200` sin hash; inexistente → `404`.
- `PATCH /usuarios/:id` → `200` + `rol_cambiado`; autodegradación
  del propio admin → `422`.
- `DELETE /usuarios/:id` → baja lógica `200 {activo: false}`;
  el login posterior de ese usuario es `401` (lo impone `auth`).

Responses con clave `detalle` en errores; jamás PII/secretos (R6).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.dependencies import require_role
from app.core.exceptions import EntidadNoEncontradaError
from app.models.entidades import Usuario
from app.schemas.usuarios import UsuarioCreate, UsuarioOut, UsuarioUpdate
from app.services.usuarios import (
    ActualizacionVaciaError,
    AutobloqueoError,
    EmailDuplicadoError,
    UsuarioNoEncontradoError,
    actualizar_usuario,
    crear_usuario,
    desactivar_usuario,
    listar_usuarios,
    obtener_usuario,
    salida_usuario,
)

router = APIRouter(prefix="/usuarios", tags=["usuarios"])

DETALLE_SIN_PERMISO = "Sin permiso."
DETALLE_DUPLICADO = "El email ya está registrado."
DETALLE_AUTOBLOQUEO = "No podés quitarte tu propio rol de admin ni desactivarte."
DETALLE_SIN_CAMBIOS = "La solicitud no trae cambios."

_ADMIN = require_role("usuarios")


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", summary="Listar usuarios (solo admin)")
async def get_usuarios(
    usuario: Annotated[Usuario, Depends(_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]:
    _ = usuario
    filas, total = await listar_usuarios(session, page=page, page_size=page_size)
    return {
        "items": [salida_usuario(f).model_dump(mode="json") for f in filas],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", status_code=201, summary="Crear usuario (solo admin)")
async def post_usuario(
    datos: UsuarioCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    try:
        creado = await crear_usuario(
            session,
            email=datos.email,
            rol=str(datos.rol),
            password=datos.password,
            actor_id=usuario.id,
            ip=_ip(request),
        )
    except EmailDuplicadoError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=DETALLE_DUPLICADO
        ) from None
    return salida_usuario(creado).model_dump(mode="json")


@router.get("/{usuario_id}", summary="Ver usuario (solo admin)")
async def get_usuario(
    usuario_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    _ = usuario
    try:
        fila = await obtener_usuario(session, usuario_id)
    except UsuarioNoEncontradoError:
        raise EntidadNoEncontradaError("usuario") from None
    out: UsuarioOut = salida_usuario(fila)
    return out.model_dump(mode="json")


@router.patch("/{usuario_id}", summary="Cambiar rol/activo (solo admin)")
async def patch_usuario(
    usuario_id: uuid.UUID,
    datos: UsuarioUpdate,
    request: Request,
    usuario: Annotated[Usuario, Depends(_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    try:
        fila = await actualizar_usuario(
            session,
            usuario_id=usuario_id,
            rol=str(datos.rol) if datos.rol is not None else None,
            activo=datos.activo,
            actor_id=usuario.id,
            ip=_ip(request),
        )
    except UsuarioNoEncontradoError:
        raise EntidadNoEncontradaError("usuario") from None
    except AutobloqueoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=DETALLE_AUTOBLOQUEO,
        ) from None
    except ActualizacionVaciaError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=DETALLE_SIN_CAMBIOS,
        ) from None
    return salida_usuario(fila).model_dump(mode="json")


@router.delete("/{usuario_id}", summary="Baja lógica (solo admin)")
async def delete_usuario(
    usuario_id: uuid.UUID,
    request: Request,
    usuario: Annotated[Usuario, Depends(_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    try:
        fila = await desactivar_usuario(
            session, usuario_id=usuario_id, actor_id=usuario.id, ip=_ip(request)
        )
    except UsuarioNoEncontradoError:
        raise EntidadNoEncontradaError("usuario") from None
    except AutobloqueoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=DETALLE_AUTOBLOQUEO,
        ) from None
    return salida_usuario(fila).model_dump(mode="json")
