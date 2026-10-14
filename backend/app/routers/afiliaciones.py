"""Router de afiliaciones OS C-13 (padrón administrativo, RN-OS-01).

`GET/POST /api/v1/afiliaciones` y `GET/PATCH/DELETE
/api/v1/afiliaciones/:id` (JWT solo `admin|recepcion` vía recurso
`afiliaciones`; `DELETE` lógico con `vigente=false`). El nro. de
afiliado se acepta al alta pero se devuelve enmascarado (últimos 4)
en TODA lectura; duplicada vigente → `409`; vigencia inválida →
`422`. Eventos `afiliacion_creada|afiliacion_actualizada` sin PII.
Odontólogo → `403` genérico + `acceso_denegado`; sin JWT → `401`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.dependencies import require_role
from app.models.entidades import Usuario
from app.schemas.obra_social import AfiliacionCreate, AfiliacionPatch
from app.services.validacion_os import (
    AfiliacionDuplicadaError,
    AfiliacionInvalidaError,
    actualizar_afiliacion,
    baja_afiliacion,
    crear_afiliacion,
    cuerpo_afiliacion,
    listar_afiliaciones,
    obtener_afiliacion,
)

router = APIRouter(prefix="/afiliaciones", tags=["afiliaciones"])

_STAFF_OS = require_role("afiliaciones")

DETALLE_DUPLICADA = "El paciente ya tiene una afiliación vigente en esa obra social."
DETALLE_VIGENCIA_INVALIDA = "La vigencia es inválida."


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", status_code=201, summary="Alta de afiliación (solo staff)")
async def post_afiliacion(
    datos: AfiliacionCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(_STAFF_OS)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    """Alta vigente (el nro. se almacena pero se devuelve enmascarado)."""
    try:
        fila = await crear_afiliacion(
            session,
            paciente_id=datos.paciente_id,
            obra_social_id=datos.obra_social_id,
            nro_afiliado=str(datos.nro_afiliado),
            vigencia_desde=datos.vigencia_desde,
            vigencia_hasta=datos.vigencia_hasta,
            usuario_id=usuario.id,
            ip=_ip(request),
        )
    except AfiliacionDuplicadaError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=DETALLE_DUPLICADA
        ) from None
    except AfiliacionInvalidaError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=DETALLE_VIGENCIA_INVALIDA,
        ) from None
    return dict(cuerpo_afiliacion(fila))


@router.get("", summary="Padrón de afiliaciones (solo staff)")
async def get_afiliaciones(
    request: Request,
    usuario: Annotated[Usuario, Depends(_STAFF_OS)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict[str, Any]]:
    _ = (request, usuario)
    filas = await listar_afiliaciones(session)
    return [dict(cuerpo_afiliacion(f)) for f in filas]


@router.get("/{afiliacion_id}", summary="Una afiliación (solo staff)")
async def get_afiliacion(
    afiliacion_id: uuid.UUID,
    request: Request,
    usuario: Annotated[Usuario, Depends(_STAFF_OS)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    _ = (request, usuario)
    fila = await obtener_afiliacion(session, afiliacion_id)
    return dict(cuerpo_afiliacion(fila))


@router.patch("/{afiliacion_id}", summary="Actualizar vigencia/flag (solo staff)")
async def patch_afiliacion(
    afiliacion_id: uuid.UUID,
    datos: AfiliacionPatch,
    request: Request,
    usuario: Annotated[Usuario, Depends(_STAFF_OS)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    _ = request
    try:
        fila = await actualizar_afiliacion(
            session,
            afiliacion_id=afiliacion_id,
            vigencia_hasta=datos.vigencia_hasta,
            tocar_hasta="vigencia_hasta" in datos.model_fields_set,
            vigente=datos.vigente,
            usuario_id=usuario.id,
            ip=_ip(request),
        )
    except AfiliacionDuplicadaError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=DETALLE_DUPLICADA
        ) from None
    except AfiliacionInvalidaError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=DETALLE_VIGENCIA_INVALIDA,
        ) from None
    return dict(cuerpo_afiliacion(fila))


@router.delete("/{afiliacion_id}", summary="Baja lógica (solo staff)")
async def delete_afiliacion(
    afiliacion_id: uuid.UUID,
    request: Request,
    usuario: Annotated[Usuario, Depends(_STAFF_OS)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    _ = request
    fila = await baja_afiliacion(
        session,
        afiliacion_id=afiliacion_id,
        usuario_id=usuario.id,
        ip=_ip(request),
    )
    return dict(cuerpo_afiliacion(fila))
