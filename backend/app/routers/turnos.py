"""Router de turnos (C-01 GREEN + C-02 JWT/RBAC + C-04 operación recepción).

C-04 suma los endpoints dedicados de confirmar, check-in (`presente`),
reprogramar por enlace y sobreturno auditado. El shape 201/409/422 de C-01
no cambia; la cancelación es C-05 y NO se implementa aquí.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.dependencies import require_role
from app.models.entidades import Usuario
from app.schemas.turno import (
    ReprogramarRequest,
    SobreturnoCreate,
    TurnoCreate,
    TurnoRead,
)
from app.services.agenda import (
    confirmar_turno,
    crear_sobreturno,
    registrar_checkin,
    reprogramar_turno,
)
from app.services.autogestion import rotar_token
from app.services.crear_turno import crear_turno

router = APIRouter(prefix="/turnos", tags=["turnos"])


@router.post(
    "",
    response_model=TurnoRead,
    status_code=201,
    summary="Crear turno evitando solapamientos",
)
async def post_turno(
    datos: TurnoCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(require_role("turnos"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TurnoRead:
    turno = await crear_turno(
        session,
        datos,
        usuario_id=usuario.id,
        ip=request.client.host if request.client else None,
    )
    return TurnoRead.model_validate(turno)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post(
    "/sobreturno",
    response_model=TurnoRead,
    status_code=201,
    summary="Crear sobreturno auditado (solo recepcion/admin, con motivo)",
)
async def post_sobreturno(
    datos: SobreturnoCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(require_role("turnos"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TurnoRead:
    turno = await crear_sobreturno(
        session,
        datos,
        usuario_rol=usuario.rol,
        usuario_id=usuario.id,
        ip=_ip(request),
    )
    return TurnoRead.model_validate(turno)


@router.post(
    "/{turno_id}/confirmar",
    response_model=TurnoRead,
    summary="Confirmar turno (reservado→confirmado)",
)
async def post_confirmar(
    turno_id: uuid.UUID,
    request: Request,
    usuario: Annotated[Usuario, Depends(require_role("turnos"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TurnoRead:
    turno = await confirmar_turno(
        session, turno_id, usuario_id=usuario.id, ip=_ip(request)
    )
    return TurnoRead.model_validate(turno)


@router.post(
    "/{turno_id}/check-in",
    response_model=TurnoRead,
    summary="Check-in (reservado|confirmado→presente)",
)
async def post_checkin(
    turno_id: uuid.UUID,
    request: Request,
    usuario: Annotated[Usuario, Depends(require_role("turnos"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TurnoRead:
    turno = await registrar_checkin(
        session, turno_id, usuario_id=usuario.id, ip=_ip(request)
    )
    return TurnoRead.model_validate(turno)


@router.post(
    "/{turno_id}/reprogramar",
    response_model=TurnoRead,
    status_code=201,
    summary="Reprogramar (conserva token_publico, enlaza el original)",
)
async def post_reprogramar(
    turno_id: uuid.UUID,
    datos: ReprogramarRequest,
    request: Request,
    usuario: Annotated[Usuario, Depends(require_role("turnos"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TurnoRead:
    turno = await reprogramar_turno(
        session,
        turno_id,
        nuevo_inicio=datos.nuevo_inicio,
        motivo_override=datos.motivo_override,
        usuario_id=usuario.id,
        ip=_ip(request),
    )
    return TurnoRead.model_validate(turno)


@router.post(
    "/{turno_id}/rotar-token",
    summary="Rotar token_publico ante sospecha de fuga (solo staff)",
)
async def post_rotar_token(
    turno_id: uuid.UUID,
    request: Request,
    usuario: Annotated[Usuario, Depends(require_role("turnos"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    """Genera un token nuevo e invalida el anterior (C-05, RN-PU-02).

    Sin permiso → `403` + `acceso_denegado` (vía `require_role`), token
    intacto. La respuesta lleva el token nuevo (staff autenticado); el
    `diff` de `token_rotado` jamás incluye tokens (R6).
    """
    turno = await rotar_token(session, turno_id, usuario_id=usuario.id, ip=_ip(request))
    return {"id": str(turno.id), "token_publico": str(turno.token_publico)}
