"""Superficie RBAC mínima C-02 (contratos asumidos por los tests RED).

Probes que verifican la matriz `domain/auth/matriz.py` (espejo de
`03_actores_y_roles.md`): agenda propia (`odontologo`) y configuración
de agenda (solo `admin`). La gestión de usuarios vive en
`routers/usuarios.py` (CRUD C-11; el probe plano se retiró al llegar
el CRUD real — el 403 + `acceso_denegado` se preserva vía matriz).
Los recursos completos llegan en changes posteriores; aquí solo se
prueba que el permiso se exige y la denegación se audita (RN-AU-03).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import require_role
from app.models.entidades import Usuario

router = APIRouter(tags=["rbac"])


@router.get("/agenda/mia", summary="Agenda propia (odontólogo)")
async def agenda_mia(
    usuario: Annotated[Usuario, Depends(require_role("agenda_propia"))],
) -> dict[str, object]:
    return {"profesional": usuario.email, "turnos": []}


@router.get("/configuracion/agenda", summary="Configuración (solo admin)")
async def configuracion_agenda(
    usuario: Annotated[Usuario, Depends(require_role("configuracion_agenda"))],
) -> dict[str, object]:
    return {"configuracion": {"sede": "Consultorio"}, "responsable": usuario.email}
