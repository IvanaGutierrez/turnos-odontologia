"""Router de validación de cobertura OS C-13 (RN-OS-01/02).

`POST /api/v1/obras-sociales/validar` (JWT `admin|recepcion|odontologo`
vía recurso `obras_sociales`): valida UN turno contra el nomenclador
LOCAL versionado y persiste la `ValidacionCobertura` con su evento
`validacion_os_registrada` (sin PII). Sin permiso → `403` genérico +
`acceso_denegado` (vía `require_role`); sin JWT → `401`. Errores con
clave `detalle`, jamás nro. de afiliado ni DNI (R6).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.dependencies import require_role
from app.models.entidades import Usuario
from app.schemas.obra_social import ValidarRequest
from app.services.validacion_os import (
    AfiliacionAjenaError,
    OSInactivaError,
    validar_cobertura,
)

router = APIRouter(prefix="/obras-sociales", tags=["obras-sociales"])

_VALIDAR = require_role("obras_sociales")

DETALLE_AFILIACION_AJENA = "La afiliación no corresponde al paciente del turno."
DETALLE_OS_INACTIVA = "La obra social está inactiva."


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/validar", summary="Validación preventiva de cobertura por turno")
async def post_validar(
    datos: ValidarRequest,
    request: Request,
    usuario: Annotated[Usuario, Depends(_VALIDAR)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    """Cruza afiliación + nomenclador + topes (nunca muta el turno)."""
    try:
        return await validar_cobertura(
            session,
            turno_id=datos.turno_id,
            afiliacion_id=datos.afiliacion_id,
            usuario_id=usuario.id,
            ip=_ip(request),
        )
    except AfiliacionAjenaError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=DETALLE_AFILIACION_AJENA,
        ) from None
    except OSInactivaError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=DETALLE_OS_INACTIVA,
        ) from None
