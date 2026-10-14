"""Router de caja y cierre diario C-09 (RN-PA-04/05, Flujo 6).

RBAC (matriz C-02 extendida, deny-by-default): `caja → {admin,
recepcion}` (movimientos, cierre, consultas); `reapertura_caja →
{admin}` (odontólogo/recepción → `403` + `reapertura_denegada`
con solo `{fecha, sede, usuario_id}`); sin JWT → `401`.
Errores con clave `detalle` sin PII (R6); `404` de dominio con
`problema: no_encontrado`; día cerrado con `422 dia_cerrado`;
doble cierre con `409` (UNIQUE, la DB manda).
Responses sin `concepto` crudo ni PII (solo IDs/montos/métodos/estados).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.dependencies import get_current_user
from app.core.exceptions import EntidadNoEncontradaError
from app.domain.auth.matriz import puede
from app.models.entidades import Usuario
from app.repositories import auditoria as repo_auditoria
from app.schemas.caja import CierreCreate, MovimientoCreate, ReaperturaCreate
from app.services.caja import (
    CierreAbiertoError,
    CierreExistenteError,
    CierreNoEncontradoError,
    DiaCerradoError,
    MovimientoInvalidoError,
    PagoYaVinculadoError,
    _cuerpo_cierre,
    _cuerpo_movimiento,
    crear_cierre,
    listar_movimientos,
    obtener_cierre,
    reabrir_cierre,
    registrar_movimiento,
)

router = APIRouter(prefix="/caja", tags=["caja"])

DETALLE_SIN_PERMISO = "Sin permiso."
DETALLE_DIA_CERRADO = "dia_cerrado"
DETALLE_CIERRE_EXISTENTE = "El cierre ya existe para ese día y sede."
DETALLE_MOVIMIENTO_INVALIDO = "El movimiento no es válido."
DETALLE_PAGO_VINCULADO = "El pago ya está vinculado a otro movimiento."
DETALLE_REAPERTURA_ABIERTA = "El cierre ya está abierto."


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _caja_o_403(
    request: Request,
    usuario: Annotated[Usuario, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Usuario:
    """Gate `caja`: roles de la matriz; resto → `403` + auditoría sin PII."""
    if not puede(usuario.rol, "caja"):
        await repo_auditoria.registrar_auditoria(
            session,
            accion="acceso_denegado",
            entidad="caja",
            entidad_id=None,
            diff={"recurso": "caja", "rol": usuario.rol},
            usuario_id=usuario.id,
            ip=_ip(request),
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=DETALLE_SIN_PERMISO
        )
    return usuario


@router.post("/movimientos", status_code=201, summary="Registrar movimiento (RN-PA-05)")
async def post_movimiento(
    datos: MovimientoCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(_caja_o_403)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    try:
        mov = await registrar_movimiento(
            session,
            fecha=datos.fecha,
            sede=datos.sede,
            tipo=str(datos.tipo),
            concepto=str(datos.concepto),
            monto=datos.monto,
            metodo=str(datos.metodo),
            usuario_id=usuario.id,
            pago_id=datos.pago_id,
            ip=_ip(request),
        )
    except DiaCerradoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=DETALLE_DIA_CERRADO,
        ) from None
    except PagoYaVinculadoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=DETALLE_PAGO_VINCULADO,
        ) from None
    except MovimientoInvalidoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=DETALLE_MOVIMIENTO_INVALIDO,
        ) from None
    return dict(_cuerpo_movimiento(mov))


@router.get("/movimientos", summary="Arqueo del día (Flujo 6 paso 1)")
async def get_movimientos(
    request: Request,
    fecha: Annotated[date, Query(description="Día operativo.")],
    usuario: Annotated[Usuario, Depends(_caja_o_403)],
    session: Annotated[AsyncSession, Depends(get_session)],
    sede: Annotated[str, Query(description="Sede.")] = "Consultorio",
) -> list[dict[str, object]]:
    _ = (request, usuario)
    filas = await listar_movimientos(session, fecha=fecha, sede=sede)
    return [dict(_cuerpo_movimiento(f)) for f in filas]


@router.post("/cierre", status_code=201, summary="Cerrar el día/sede (RN-PA-04)")
async def post_cierre(
    datos: CierreCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(_caja_o_403)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    try:
        cierre = await crear_cierre(
            session,
            fecha=datos.fecha,
            sede=datos.sede,
            usuario_id=usuario.id,
            ip=_ip(request),
        )
    except CierreExistenteError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DETALLE_CIERRE_EXISTENTE,
        ) from None
    return dict(_cuerpo_cierre(cierre))


@router.get("/cierre", summary="Consultar el cierre del día")
async def get_cierre(
    request: Request,
    fecha: Annotated[date, Query(description="Día operativo.")],
    usuario: Annotated[Usuario, Depends(_caja_o_403)],
    session: Annotated[AsyncSession, Depends(get_session)],
    sede: Annotated[str, Query(description="Sede.")] = "Consultorio",
) -> dict[str, object]:
    _ = (request, usuario)
    cierre = await obtener_cierre(session, fecha=fecha, sede=sede)
    if cierre is None:
        raise EntidadNoEncontradaError("cierre")
    return dict(_cuerpo_cierre(cierre))


@router.post("/reapertura", summary="Reabrir un día cerrado (solo admin)")
async def post_reapertura(
    datos: ReaperturaCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    if not puede(usuario.rol, "reapertura_caja"):
        await repo_auditoria.registrar_auditoria(
            session,
            accion="reapertura_denegada",
            entidad="cierre_diario",
            entidad_id=None,
            diff={
                "fecha": datos.fecha.isoformat(),
                "sede": datos.sede,
                "usuario_id": str(usuario.id),
            },
            usuario_id=usuario.id,
            ip=_ip(request),
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=DETALLE_SIN_PERMISO
        )
    try:
        cierre = await reabrir_cierre(
            session,
            fecha=datos.fecha,
            sede=datos.sede,
            motivo=str(datos.motivo),
            usuario_id=usuario.id,
            ip=_ip(request),
        )
    except CierreNoEncontradoError:
        raise EntidadNoEncontradaError("cierre") from None
    except CierreAbiertoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=DETALLE_REAPERTURA_ABIERTA,
        ) from None
    except MovimientoInvalidoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=DETALLE_MOVIMIENTO_INVALIDO,
        ) from None
    return {
        "id": str(cierre.id),
        "fecha": cierre.fecha.isoformat(),
        "sede": cierre.sede,
        "estado": cierre.estado,
        "reaperturas": cierre.reaperturas,
    }
