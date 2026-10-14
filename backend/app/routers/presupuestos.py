"""Routers de presupuesto/firma C-07 (RN-CL-03 + máquina de estados).

`presupuesto` en matriz: `{admin, odontologo}`; rol fuera → `403`
genérico + `acceso_clinico_denegado` sin PII. `borrador→aprobado` exige
firma; `borrador→pagado` directo y salidas desde `rechazado` → `422`.
Respuestas sin narrativa clínica, solo piezas/códigos/montos (R6).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.dependencies import get_current_user
from app.domain.auth.matriz import puede
from app.models.clinica import PresupuestoItem
from app.models.entidades import Usuario
from app.repositories import auditoria as repo_auditoria
from app.schemas.clinica import FirmaIn, PresupuestoCreate, RechazoIn, TransicionIn
from app.services.presupuesto import (
    PresupuestoError,
    PresupuestoNoEncontradoError,
    aprobar,
    crear_desde_hallazgos,
    crear_plan,
    rechazar,
    registrar_firma,
    transicion,
)
from app.services.presupuesto import _presupuesto as _cargar

router = APIRouter(prefix="/presupuestos", tags=["clinica"])
planes_router = APIRouter(prefix="/planes", tags=["clinica"])

DETALLE_SIN_PERMISO = "Sin permiso."
DETALLE_PRESUPUESTO = "La operación no es válida en el estado actual."


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _presupuesto_o_403(
    request: Request,
    usuario: Annotated[Usuario, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Usuario:
    if not puede(usuario.rol, "presupuesto"):
        await repo_auditoria.registrar_auditoria(
            session,
            accion="acceso_clinico_denegado",
            entidad="presupuesto",
            entidad_id=None,
            diff={"recurso": "presupuesto", "rol": usuario.rol},
            usuario_id=usuario.id,
            ip=_ip(request),
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=DETALLE_SIN_PERMISO
        )
    return usuario


async def _cuerpo_presupuesto(
    session: AsyncSession, pid: uuid.UUID
) -> dict[str, object]:
    presupuesto = await _cargar(session, pid)
    items = (
        (
            await session.execute(
                select(PresupuestoItem).where(PresupuestoItem.presupuesto_id == pid)
            )
        )
        .scalars()
        .all()
    )
    return {
        "id": str(presupuesto.id),
        "estado": presupuesto.estado,
        "total": f"{presupuesto.total:.2f}",
        "items": [
            {
                "pieza_fdi": it.pieza_fdi,
                "estado_codigo": it.estado_codigo,
                "cantidad": it.cantidad,
                "precio_unitario": f"{it.precio_unitario:.2f}",
            }
            for it in items
        ],
    }


@router.post("", status_code=201, summary="Presupuesto desde hallazgos (borrador)")
async def post_presupuesto(
    datos: PresupuestoCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(_presupuesto_o_403)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    try:
        presupuesto, _ = await crear_desde_hallazgos(
            session,
            ficha_id=datos.ficha_id,
            hallazgos=list(datos.desde_hallazgos),
            firmante_id=usuario.id,
            firmante_rol=usuario.rol,
            ip=_ip(request),
        )
    except PresupuestoNoEncontradoError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado."
        ) from None
    return await _cuerpo_presupuesto(session, presupuesto.id)


@router.get("/{presupuesto_id}", summary="Ver estado del presupuesto")
async def get_presupuesto(
    presupuesto_id: uuid.UUID,
    request: Request,
    usuario: Annotated[Usuario, Depends(_presupuesto_o_403)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    try:
        return await _cuerpo_presupuesto(session, presupuesto_id)
    except PresupuestoNoEncontradoError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado."
        ) from None


@router.post("/{presupuesto_id}/firma", summary="Registrar firma del paciente")
async def post_firma(
    presupuesto_id: uuid.UUID,
    datos: FirmaIn,
    request: Request,
    usuario: Annotated[Usuario, Depends(_presupuesto_o_403)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    try:
        presupuesto = await registrar_firma(
            session,
            presupuesto_id,
            firma=datos.firma,
            fecha=datos.fecha,
            firmante_id=usuario.id,
            ip=_ip(request),
        )
    except PresupuestoNoEncontradoError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado."
        ) from None
    except PresupuestoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=DETALLE_PRESUPUESTO
        ) from None
    return {"id": str(presupuesto.id), "estado": presupuesto.estado}


@router.post("/{presupuesto_id}/aprobar", summary="Aprobar (exige firma)")
async def post_aprobar(
    presupuesto_id: uuid.UUID,
    request: Request,
    usuario: Annotated[Usuario, Depends(_presupuesto_o_403)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    try:
        presupuesto = await aprobar(
            session, presupuesto_id, firmante_id=usuario.id, ip=_ip(request)
        )
    except PresupuestoNoEncontradoError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado."
        ) from None
    except PresupuestoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=DETALLE_PRESUPUESTO
        ) from None
    return {"id": str(presupuesto.id), "estado": presupuesto.estado}


@router.post("/{presupuesto_id}/rechazar", summary="Rechazar (terminal, con motivo)")
async def post_rechazar(
    presupuesto_id: uuid.UUID,
    datos: RechazoIn,
    request: Request,
    usuario: Annotated[Usuario, Depends(_presupuesto_o_403)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    try:
        presupuesto = await rechazar(
            session,
            presupuesto_id,
            motivo=datos.motivo,
            firmante_id=usuario.id,
            ip=_ip(request),
        )
    except PresupuestoNoEncontradoError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado."
        ) from None
    except PresupuestoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=DETALLE_PRESUPUESTO
        ) from None
    return {"id": str(presupuesto.id), "estado": presupuesto.estado}


@router.post(
    "/{presupuesto_id}/transicion", summary="Transición genérica (valida máquina)"
)
async def post_transicion(
    presupuesto_id: uuid.UUID,
    datos: TransicionIn,
    request: Request,
    usuario: Annotated[Usuario, Depends(_presupuesto_o_403)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    try:
        presupuesto = await transicion(
            session,
            presupuesto_id,
            destino=datos.estado_destino,
            firmante_id=usuario.id,
            ip=_ip(request),
        )
    except PresupuestoNoEncontradoError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado."
        ) from None
    except PresupuestoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=DETALLE_PRESUPUESTO
        ) from None
    return {"id": str(presupuesto.id), "estado": presupuesto.estado}


@planes_router.post("", status_code=201, summary="Crear plan (seña exige firma previa)")
async def post_plan(
    datos: dict[str, object],
    request: Request,
    usuario: Annotated[Usuario, Depends(_presupuesto_o_403)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """Cuerpo `{presupuesto_id, etapas, sena_requerida}` (validado mínimo)."""
    from decimal import Decimal

    try:
        pid = uuid.UUID(str(datos.get("presupuesto_id")))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=DETALLE_PRESUPUESTO
        ) from None
    etapas_raw = datos.get("etapas", [])
    if not isinstance(etapas_raw, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=DETALLE_PRESUPUESTO
        ) from None
    if any(not isinstance(e, dict) for e in etapas_raw):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=DETALLE_PRESUPUESTO
        ) from None
    etapas: list[dict[str, object]] = list(etapas_raw)
    try:
        sena = Decimal(str(datos.get("sena_requerida", "0")))
    except (ValueError, ArithmeticError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=DETALLE_PRESUPUESTO
        ) from None
    if sena < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=DETALLE_PRESUPUESTO
        ) from None
    try:
        plan = await crear_plan(
            session,
            presupuesto_id=pid,
            etapas=etapas,
            sena_requerida=sena,
            firmante_id=usuario.id,
            ip=_ip(request),
        )
    except PresupuestoNoEncontradoError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado."
        ) from None
    except PresupuestoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=DETALLE_PRESUPUESTO
        ) from None
    return {
        "id": str(plan.id),
        "presupuesto_id": str(plan.presupuesto_id),
        "estado": plan.estado,
    }
