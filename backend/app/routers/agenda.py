"""Grilla día/semana de recepción (C-04, spec `agenda/agenda-recepcion`).

`GET /api/v1/agenda?vista=dia|semana` — agregada multiprofesional y
multisillón en una query por rango, visibilidad por rol y minimización R6
(jamás DNI/teléfono/HC/hashes/tokens en cuerpos ni logs). Exige permiso
`turnos` (`401` sin token, `403` + `acceso_denegado` sin permiso).
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.dependencies import require_role
from app.models.entidades import Usuario
from app.schemas.turno import AgendaItem
from app.services.agenda import obtener_grilla

router = APIRouter(tags=["agenda"])


@router.get(
    "/agenda",
    response_model=list[AgendaItem],
    summary="Grilla día/semana para operación de recepción",
)
async def get_agenda(
    usuario: Annotated[Usuario, Depends(require_role("turnos"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    vista: Annotated[Literal["dia", "semana"], Query()] = "dia",
    profesional_id: Annotated[uuid.UUID | None, Query()] = None,
    sillon_id: Annotated[uuid.UUID | None, Query()] = None,
    desde: Annotated[datetime | None, Query()] = None,
    hasta: Annotated[datetime | None, Query()] = None,
) -> list[AgendaItem]:
    _ = usuario  # la identidad ya quedó auditada si correspondía
    return await obtener_grilla(
        session,
        vista=vista,
        profesional_id=profesional_id,
        sillon_id=sillon_id,
        desde=desde,
        hasta=hasta,
    )
