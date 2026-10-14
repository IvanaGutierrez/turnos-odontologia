"""Lector de bitácora C-11 (spec `auditoria/registro-acciones` MODIFIED).

`GET /api/v1/auditoria?entidad&entidad_id&accion&desde&hasta&page&page_size`
(JWT, solo `admin` vía recurso `auditoria`): devuelve la bitácora
paginada ordenada por hora descendente, con los `diff` ya sanitizados
(la escritura `registrar_auditoria()` + `sanitizar_diff()` C-02 no cambia;
aquí se re-sanitiza en lectura por defensa en profundidad).

Recepción/odontólogo → `403` genérico + `acceso_denegado`; sin JWT → `401`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.dependencies import require_role
from app.models.auditoria import AuditoriaLog
from app.models.entidades import Usuario
from app.repositories.auditoria import sanitizar_diff

router = APIRouter(prefix="/auditoria", tags=["auditoria"])

_ADMIN = require_role("auditoria")


def cuerpo_evento(fila: AuditoriaLog) -> dict[str, object]:
    """Serialización mínima (R6: `diff` re-sanitizado, sin PII)."""
    creado = fila.creado_en
    iso = creado.isoformat() if isinstance(creado, datetime) else str(creado)
    return {
        "id": str(fila.id),
        "accion": fila.accion,
        "entidad": fila.entidad,
        "entidad_id": fila.entidad_id,
        "diff": sanitizar_diff(dict(fila.diff or {})),
        "usuario_id": str(fila.usuario_id) if fila.usuario_id else None,
        "ip": fila.ip,
        "hora": iso,
        "creado_en": iso,
    }


@router.get("", summary="Bitácora filtrable (solo admin)")
async def get_auditoria(
    usuario: Annotated[Usuario, Depends(_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_session)],
    entidad: Annotated[str | None, Query(description="Entidad.")] = None,
    entidad_id: Annotated[str | None, Query(description="Id de entidad.")] = None,
    accion: Annotated[str | None, Query(description="Acción.")] = None,
    desde: Annotated[datetime | None, Query(description="Hora desde.")] = None,
    hasta: Annotated[datetime | None, Query(description="Hora hasta.")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]:
    _ = usuario
    consulta = select(AuditoriaLog)
    conteo = select(func.count()).select_from(AuditoriaLog)
    if entidad is not None:
        consulta = consulta.where(AuditoriaLog.entidad == entidad)
        conteo = conteo.where(AuditoriaLog.entidad == entidad)
    if entidad_id is not None:
        consulta = consulta.where(AuditoriaLog.entidad_id == entidad_id)
        conteo = conteo.where(AuditoriaLog.entidad_id == entidad_id)
    if accion is not None:
        consulta = consulta.where(AuditoriaLog.accion == accion)
        conteo = conteo.where(AuditoriaLog.accion == accion)
    if desde is not None:
        consulta = consulta.where(AuditoriaLog.creado_en >= desde)
        conteo = conteo.where(AuditoriaLog.creado_en >= desde)
    if hasta is not None:
        consulta = consulta.where(AuditoriaLog.creado_en <= hasta)
        conteo = conteo.where(AuditoriaLog.creado_en <= hasta)
    total = int(await session.scalar(conteo) or 0)
    filas = (
        (
            await session.execute(
                consulta.order_by(AuditoriaLog.creado_en.desc(), AuditoriaLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [cuerpo_evento(f) for f in filas],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
