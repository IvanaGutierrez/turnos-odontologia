"""Router de reportes operativos C-11 (spec `admin/reportes-operativos`).

JSON (`recurso reportes`): `GET /reportes/ocupacion|ausentismo|ingresos`
con `desde&hasta` obligatorios (+ `profesional_id&sillon_id&sede`
opcionales); scoping por rol en servicio (admin full / odontólogo solo
propios / recepción solo día operativo) → `403` genérico + auditoría.

CSV (`recurso reportes_csv` → `admin` full y `odontologo` propio;
recepción → `403`): `GET /reportes/:tipo.csv` con `text/csv; charset=utf-8`,
BOM (Excel AR), separador `,`, headers fijos en español, cuerpo en
streaming (`StreamingResponse`, sin cargar todo en memoria),
`Content-Disposition: attachment; filename=reporte-<tipo>-<desde>-<hasta>.csv`
y evento `reporte_csv_exportado`. El serializador CSV solo emite claves
del contrato (allowlist); jamás PII/HCE (R6).
"""

from __future__ import annotations

import codecs
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.dependencies import require_role
from app.models.caja import SEDE_DEFAULT
from app.models.entidades import Usuario
from app.repositories import auditoria as repo_auditoria
from app.services.reportes import (
    AlcanceDenegadoError,
    alcance_profesional,
    ausentismo,
    exigir_dia_operativo,
    ingresos,
    ocupacion,
)

router = APIRouter(prefix="/reportes", tags=["reportes"])

_JSON = require_role("reportes")
_CSV = require_role("reportes_csv")

DETALLE_SIN_PERMISO = "Sin permiso."
DETALLE_RANGO = "El rango de fechas es inválido."

HEADERS_OCUPACION = (
    "periodo_desde,periodo_hasta,dimension,dimension_id,"
    "turnos_totales,turnos_activos,horas_ocupadas,ocupacion_pct"
)
HEADERS_AUSENTISMO = (
    "periodo_desde,periodo_hasta,profesional_id,"
    "turnos_finalizados,ausentes,ausentismo_pct"
)
HEADERS_INGRESOS = (
    "periodo_desde,periodo_hasta,metodo,monto,total,acreditado_mp,diferencia"
)

COLUMNAS_OCUPACION: tuple[str, ...] = (
    "periodo_desde",
    "periodo_hasta",
    "dimension",
    "dimension_id",
    "turnos_totales",
    "turnos_activos",
    "horas_ocupadas",
    "ocupacion_pct",
)
COLUMNAS_AUSENTISMO: tuple[str, ...] = (
    "periodo_desde",
    "periodo_hasta",
    "profesional_id",
    "turnos_finalizados",
    "ausentes",
    "ausentismo_pct",
)
COLUMNAS_INGRESOS: tuple[str, ...] = (
    "periodo_desde",
    "periodo_hasta",
    "metodo",
    "monto",
    "total",
    "acreditado_mp",
    "diferencia",
)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _fmt(valor: object) -> str:
    """Número sin notación científica para el CSV (texto, sin PII)."""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)


def _filas_csv(columnas: tuple[str, ...], filas: list[dict[str, object]]) -> list[str]:
    """Serializador allowlist: solo claves del contrato llegan al CSV."""
    lineas = [",".join(columnas)]
    for fila in filas:
        lineas.append(",".join(_fmt(fila.get(columna, "")) for columna in columnas))
    return lineas


async def _csv_stream(lineas: list[str]) -> AsyncIterator[bytes]:
    yield codecs.BOM_UTF8
    for linea in lineas:
        yield (linea + "\n").encode("utf-8")


def _respuesta_csv(
    *, tipo: str, desde: date, hasta: date, lineas: list[str]
) -> StreamingResponse:
    nombre = f"reporte-{tipo}-{desde.isoformat()}-{hasta.isoformat()}.csv"
    return StreamingResponse(
        _csv_stream(lineas),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={nombre}"},
    )


async def _auditar_export(
    session: AsyncSession,
    *,
    tipo: str,
    desde: date,
    hasta: date,
    usuario: Usuario,
    ip: str | None,
) -> None:
    await repo_auditoria.registrar_auditoria(
        session,
        accion="reporte_csv_exportado",
        entidad="reporte",
        entidad_id=tipo,
        diff={
            "tipo": tipo,
            "desde": desde.isoformat(),
            "hasta": hasta.isoformat(),
        },
        usuario_id=usuario.id,
        ip=ip,
    )
    await session.commit()


async def _profesional_efectivo(
    session: AsyncSession,
    *,
    usuario: Usuario,
    profesional_id: uuid.UUID | None,
) -> uuid.UUID | None:
    try:
        return await alcance_profesional(
            session,
            rol=usuario.rol,
            usuario_id=usuario.id,
            profesional_id=profesional_id,
        )
    except AlcanceDenegadoError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=DETALLE_SIN_PERMISO
        ) from None


def _exigir_alcance(*, usuario: Usuario, desde: date, hasta: date) -> None:
    if hasta < desde:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=DETALLE_RANGO
        )
    try:
        exigir_dia_operativo(rol=usuario.rol, desde=desde, hasta=hasta)
    except AlcanceDenegadoError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=DETALLE_SIN_PERMISO
        ) from None


@router.get("/ocupacion", summary="Ocupación por profesional y sillón")
async def get_ocupacion(
    desde: Annotated[date, Query(description="Desde (fecha).")],
    hasta: Annotated[date, Query(description="Hasta (fecha).")],
    usuario: Annotated[Usuario, Depends(_JSON)],
    session: Annotated[AsyncSession, Depends(get_session)],
    profesional_id: Annotated[uuid.UUID | None, Query()] = None,
    sillon_id: Annotated[uuid.UUID | None, Query()] = None,
    sede: Annotated[str | None, Query()] = None,
) -> dict[str, object]:
    _exigir_alcance(usuario=usuario, desde=desde, hasta=hasta)
    efectivo = await _profesional_efectivo(
        session, usuario=usuario, profesional_id=profesional_id
    )
    if usuario.rol == "odontologo" and efectivo is None:
        return {"por_profesional": [], "por_sillon": []}
    return await ocupacion(
        session,
        desde=desde,
        hasta=hasta,
        profesional_id=efectivo,
        sillon_id=sillon_id,
        sede=sede,
    )


@router.get("/ausentismo", summary="Ausentismo global y por profesional")
async def get_ausentismo(
    desde: Annotated[date, Query(description="Desde (fecha).")],
    hasta: Annotated[date, Query(description="Hasta (fecha).")],
    usuario: Annotated[Usuario, Depends(_JSON)],
    session: Annotated[AsyncSession, Depends(get_session)],
    profesional_id: Annotated[uuid.UUID | None, Query()] = None,
    sede: Annotated[str | None, Query()] = None,
) -> dict[str, object]:
    _exigir_alcance(usuario=usuario, desde=desde, hasta=hasta)
    efectivo = await _profesional_efectivo(
        session, usuario=usuario, profesional_id=profesional_id
    )
    if usuario.rol == "odontologo" and efectivo is None:
        return {
            "turnos_finalizados": 0,
            "ausentes": 0,
            "ausentismo_pct": 0.0,
            "por_profesional": [],
        }
    return await ausentismo(
        session, desde=desde, hasta=hasta, profesional_id=efectivo, sede=sede
    )


@router.get("/ingresos", summary="Ingresos por método con conciliación")
async def get_ingresos(
    desde: Annotated[date, Query(description="Desde (fecha).")],
    hasta: Annotated[date, Query(description="Hasta (fecha).")],
    usuario: Annotated[Usuario, Depends(_JSON)],
    session: Annotated[AsyncSession, Depends(get_session)],
    sede: Annotated[str, Query()] = SEDE_DEFAULT,
) -> dict[str, object]:
    _exigir_alcance(usuario=usuario, desde=desde, hasta=hasta)
    propio: uuid.UUID | None = usuario.id if usuario.rol == "odontologo" else None
    return await ingresos(
        session, desde=desde, hasta=hasta, sede=sede, usuario_id=propio
    )


def _filas_ocupacion(
    *, desde: date, hasta: date, datos: dict[str, object]
) -> list[dict[str, object]]:
    filas: list[dict[str, object]] = []
    por_prof = datos.get("por_profesional")
    por_sillon = datos.get("por_sillon")
    assert isinstance(por_prof, list) and isinstance(por_sillon, list)
    for entrada in por_prof:
        assert isinstance(entrada, dict)
        filas.append(
            {
                "periodo_desde": desde.isoformat(),
                "periodo_hasta": hasta.isoformat(),
                "dimension": "profesional",
                "dimension_id": entrada.get("profesional_id"),
                "turnos_totales": entrada.get("turnos_totales"),
                "turnos_activos": entrada.get("turnos_activos"),
                "horas_ocupadas": entrada.get("horas_ocupadas"),
                "ocupacion_pct": entrada.get("ocupacion_pct"),
            }
        )
    for entrada in por_sillon:
        assert isinstance(entrada, dict)
        filas.append(
            {
                "periodo_desde": desde.isoformat(),
                "periodo_hasta": hasta.isoformat(),
                "dimension": "sillon",
                "dimension_id": entrada.get("sillon_id"),
                "turnos_totales": entrada.get("turnos_totales"),
                "turnos_activos": entrada.get("turnos_activos"),
                "horas_ocupadas": entrada.get("horas_ocupadas"),
                "ocupacion_pct": entrada.get("ocupacion_pct"),
            }
        )
    return filas


def _filas_ausentismo(
    *, desde: date, hasta: date, datos: dict[str, object]
) -> list[dict[str, object]]:
    filas: list[dict[str, object]] = []
    grupos = datos.get("por_profesional")
    assert isinstance(grupos, list)
    for entrada in grupos:
        assert isinstance(entrada, dict)
        filas.append(
            {
                "periodo_desde": desde.isoformat(),
                "periodo_hasta": hasta.isoformat(),
                "profesional_id": entrada.get("profesional_id"),
                "turnos_finalizados": entrada.get("turnos_finalizados"),
                "ausentes": entrada.get("ausentes"),
                "ausentismo_pct": entrada.get("ausentismo_pct"),
            }
        )
    return filas


def _filas_ingresos(
    *, desde: date, hasta: date, datos: dict[str, object]
) -> list[dict[str, object]]:
    filas: list[dict[str, object]] = []
    por_metodo = datos.get("por_metodo")
    assert isinstance(por_metodo, dict)
    for metodo in sorted(por_metodo):
        filas.append(
            {
                "periodo_desde": desde.isoformat(),
                "periodo_hasta": hasta.isoformat(),
                "metodo": metodo,
                "monto": por_metodo.get(metodo),
                "total": datos.get("total"),
                "acreditado_mp": datos.get("acreditado_mp"),
                "diferencia": datos.get("diferencia"),
            }
        )
    return filas


async def _csv_desde(
    *,
    tipo: str,
    columnas: tuple[str, ...],
    constructor: Callable[..., list[dict[str, object]]],
    desde: date,
    hasta: date,
    datos: dict[str, object],
    request: Request,
    usuario: Usuario,
    session: AsyncSession,
) -> StreamingResponse:
    await _auditar_export(
        session, tipo=tipo, desde=desde, hasta=hasta, usuario=usuario, ip=_ip(request)
    )
    lineas = _filas_csv(columnas, constructor(desde=desde, hasta=hasta, datos=datos))
    return _respuesta_csv(tipo=tipo, desde=desde, hasta=hasta, lineas=lineas)


@router.get("/ocupacion.csv", summary="CSV de ocupación (streaming)")
async def get_ocupacion_csv(
    desde: Annotated[date, Query(description="Desde (fecha).")],
    hasta: Annotated[date, Query(description="Hasta (fecha).")],
    request: Request,
    usuario: Annotated[Usuario, Depends(_CSV)],
    session: Annotated[AsyncSession, Depends(get_session)],
    profesional_id: Annotated[uuid.UUID | None, Query()] = None,
    sillon_id: Annotated[uuid.UUID | None, Query()] = None,
    sede: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    _exigir_alcance(usuario=usuario, desde=desde, hasta=hasta)
    efectivo = await _profesional_efectivo(
        session, usuario=usuario, profesional_id=profesional_id
    )
    datos: dict[str, object]
    if usuario.rol == "odontologo" and efectivo is None:
        datos = {"por_profesional": [], "por_sillon": []}
    else:
        datos = await ocupacion(
            session,
            desde=desde,
            hasta=hasta,
            profesional_id=efectivo,
            sillon_id=sillon_id,
            sede=sede,
        )
    return await _csv_desde(
        tipo="ocupacion",
        columnas=COLUMNAS_OCUPACION,
        constructor=_filas_ocupacion,
        desde=desde,
        hasta=hasta,
        datos=datos,
        request=request,
        usuario=usuario,
        session=session,
    )


@router.get("/ausentismo.csv", summary="CSV de ausentismo (streaming)")
async def get_ausentismo_csv(
    desde: Annotated[date, Query(description="Desde (fecha).")],
    hasta: Annotated[date, Query(description="Hasta (fecha).")],
    request: Request,
    usuario: Annotated[Usuario, Depends(_CSV)],
    session: Annotated[AsyncSession, Depends(get_session)],
    profesional_id: Annotated[uuid.UUID | None, Query()] = None,
    sede: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    _exigir_alcance(usuario=usuario, desde=desde, hasta=hasta)
    efectivo = await _profesional_efectivo(
        session, usuario=usuario, profesional_id=profesional_id
    )
    datos: dict[str, object]
    if usuario.rol == "odontologo" and efectivo is None:
        datos = {
            "turnos_finalizados": 0,
            "ausentes": 0,
            "ausentismo_pct": 0.0,
            "por_profesional": [],
        }
    else:
        datos = await ausentismo(
            session, desde=desde, hasta=hasta, profesional_id=efectivo, sede=sede
        )
    return await _csv_desde(
        tipo="ausentismo",
        columnas=COLUMNAS_AUSENTISMO,
        constructor=_filas_ausentismo,
        desde=desde,
        hasta=hasta,
        datos=datos,
        request=request,
        usuario=usuario,
        session=session,
    )


@router.get("/ingresos.csv", summary="CSV de ingresos (streaming)")
async def get_ingresos_csv(
    desde: Annotated[date, Query(description="Desde (fecha).")],
    hasta: Annotated[date, Query(description="Hasta (fecha).")],
    request: Request,
    usuario: Annotated[Usuario, Depends(_CSV)],
    session: Annotated[AsyncSession, Depends(get_session)],
    sede: Annotated[str, Query()] = SEDE_DEFAULT,
) -> StreamingResponse:
    _exigir_alcance(usuario=usuario, desde=desde, hasta=hasta)
    propio: uuid.UUID | None = usuario.id if usuario.rol == "odontologo" else None
    datos = await ingresos(
        session, desde=desde, hasta=hasta, sede=sede, usuario_id=propio
    )
    return await _csv_desde(
        tipo="ingresos",
        columnas=COLUMNAS_INGRESOS,
        constructor=_filas_ingresos,
        desde=desde,
        hasta=hasta,
        datos=datos,
        request=request,
        usuario=usuario,
        session=session,
    )
