"""Routers clínicos C-07: fichas + odontograma batch + evoluciones.

RBAC fino (RN-CL-04): escritura/lectura clínica solo `odontologo`
(`puede(rol, "ficha_clinica|odontograma|evolucion")`); cualquier otro rol
→ `403` genérico + `acceso_clinico_denegado` auditado sin PII (entidad
`ficha`, diff solo recurso/rol). Errores `422` genéricos minimizados (R6):
jamás eco de anamnesis/DNI/teléfonos.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.dependencies import get_current_user
from app.domain.auth.matriz import puede
from app.models.entidades import Usuario
from app.repositories import auditoria as repo_auditoria
from app.schemas.clinica import (
    EvolucionCreate,
    FichaCreate,
    FichaPatch,
    OdontogramaBatchIn,
)
from app.services.ficha import (
    ConsentimientoRequeridoError,
    FichaNoEncontradaError,
    OdontogramaInvalidoError,
    agregar_evolucion,
    batch_odontograma,
    crear_ficha,
    editar_ficha,
    obtener_ficha,
)

router = APIRouter(prefix="/fichas", tags=["clinica"])

DETALLE_SIN_PERMISO = "Sin permiso."
DETALLE_CONSENTIMIENTO = "Se requiere consentimiento informado registrado."
DETALLE_ODONTO_INVALIDO = "El batch contiene datos inválidos."


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _clinico_o_403(
    request: Request,
    usuario: Annotated[Usuario, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    recurso: str = "ficha_clinica",
) -> Usuario:
    """Gate clínico: solo roles de la matriz; resto → 403 + auditoría sin PII."""
    if not puede(usuario.rol, recurso):
        await repo_auditoria.registrar_auditoria(
            session,
            accion="acceso_clinico_denegado",
            entidad="ficha",
            entidad_id=None,
            diff={"recurso": "ficha", "rol": usuario.rol},
            usuario_id=usuario.id,
            ip=_ip(request),
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=DETALLE_SIN_PERMISO
        )
    return usuario


@router.post("", status_code=201, summary="Crear HCE (exige consentimiento)")
async def post_ficha(
    datos: FichaCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str | None]:
    await _clinico_o_403(request, usuario, session, "ficha_clinica")
    try:
        ficha = await crear_ficha(
            session,
            paciente_id=datos.paciente_id,
            anamnesis=datos.anamnesis,
            firmante_id=usuario.id,
            firmante_rol=usuario.rol,
            ip=_ip(request),
        )
    except ConsentimientoRequeridoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=DETALLE_CONSENTIMIENTO,
        ) from None
    except FichaNoEncontradaError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado."
        ) from None
    return {
        "id": str(ficha.id),
        "paciente_id": str(ficha.paciente_id),
        "firmante_usuario_id": (
            str(ficha.firmante_usuario_id) if ficha.firmante_usuario_id else None
        ),
    }


@router.get("/{ficha_id}", summary="Leer ficha minimizada (solo odontólogo)")
async def get_ficha(
    ficha_id: uuid.UUID,
    request: Request,
    usuario: Annotated[Usuario, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str | None]:
    await _clinico_o_403(request, usuario, session, "ficha_clinica")
    ficha = await obtener_ficha(session, ficha_id)
    if ficha is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado."
        )
    return {
        "id": str(ficha.id),
        "paciente_id": str(ficha.paciente_id),
        "firmante_usuario_id": (
            str(ficha.firmante_usuario_id) if ficha.firmante_usuario_id else None
        ),
    }


@router.patch("/{ficha_id}", summary="Editar anamnesis con re-firma (solo odontólogo)")
async def patch_ficha(
    ficha_id: uuid.UUID,
    datos: FichaPatch,
    request: Request,
    usuario: Annotated[Usuario, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str | None]:
    await _clinico_o_403(request, usuario, session, "ficha_clinica")
    try:
        ficha = await editar_ficha(
            session,
            ficha_id,
            anamnesis=datos.anamnesis,
            firmante_id=usuario.id,
            firmante_rol=usuario.rol,
            ip=_ip(request),
        )
    except FichaNoEncontradaError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado."
        ) from None
    return {
        "id": str(ficha.id),
        "paciente_id": str(ficha.paciente_id),
        "firmante_usuario_id": (
            str(ficha.firmante_usuario_id) if ficha.firmante_usuario_id else None
        ),
    }


@router.post(
    "/{ficha_id}/odontograma", summary="Batch odontograma FDI por pieza (atómico)"
)
async def post_odontograma(
    ficha_id: uuid.UUID,
    datos: OdontogramaBatchIn,
    request: Request,
    usuario: Annotated[Usuario, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, list[dict[str, object]]]:
    await _clinico_o_403(request, usuario, session, "odontograma")
    try:
        filas = await batch_odontograma(
            session,
            ficha_id,
            list(datos.entries),
            firmante_id=usuario.id,
            firmante_rol=usuario.rol,
            ip=_ip(request),
        )
    except FichaNoEncontradaError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado."
        ) from None
    except OdontogramaInvalidoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=DETALLE_ODONTO_INVALIDO,
        ) from None
    return {
        "entries": [
            {
                "pieza_fdi": f.pieza_fdi,
                "estado_codigo": f.estado_codigo,
                "catalogo_version": f.catalogo_version,
                "cara": f.cara,
            }
            for f in filas
        ]
    }


@router.post(
    "/{ficha_id}/evoluciones", status_code=201, summary="Agregar evolución firmada"
)
async def post_evolucion(
    ficha_id: uuid.UUID,
    datos: EvolucionCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    await _clinico_o_403(request, usuario, session, "evolucion")
    try:
        evolucion = await agregar_evolucion(
            session,
            ficha_id,
            texto=datos.texto,
            firmante_id=usuario.id,
            firmante_rol=usuario.rol,
            ip=_ip(request),
        )
    except FichaNoEncontradaError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado."
        ) from None
    return {"id": str(evolucion.id), "ficha_id": str(evolucion.ficha_id)}
