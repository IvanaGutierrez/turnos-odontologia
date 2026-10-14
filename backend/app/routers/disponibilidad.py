"""Disponibilidad pública C-03: `GET /api/v1/disponibilidad` (sin JWT).

Solo `{inicio, fin, profesional_id, prestacion_id}` por slot (R6); errores
genéricos (`404 no_encontrado`, `422 validacion`) sin agenda interna; rate
limit por IP con `Retry-After` (RN-PU-03). Router separado de los
protegidos (superficie pública auditable).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.exceptions import EntidadNoEncontradaError
from app.core.logger import get_logger
from app.services.disponibilidad import VentanaInvalidaError, calcular_slots
from app.services.reserva_publica import DETALLE_RATELIMIT, _contar_rate, topes_rate

logger = get_logger(__name__)

router = APIRouter(prefix="/disponibilidad", tags=["disponibilidad"])


async def _freno_ip(request: Request) -> int | None:
    ip = request.client.host if request.client else "desconocida"
    tope, ventana, _, _ = topes_rate()
    conteo, espera = await _contar_rate(
        request.app.state.redis, f"rl:disponibilidad:ip:{ip}", ventana
    )
    if conteo is not None and conteo > tope:
        return espera
    return None


@router.get("", summary="Consultar slots libres por prestación y profesional")
async def get_disponibilidad(
    request: Request,
    prestacion_id: uuid.UUID,
    profesional_id: uuid.UUID,
    desde: datetime = Query(...),  # noqa: B008
    hasta: datetime = Query(...),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> JSONResponse:
    espera = await _freno_ip(request)
    if espera is not None:
        return JSONResponse(
            status_code=429,
            content={"detalle": DETALLE_RATELIMIT},
            headers={"Retry-After": str(espera)},
        )
    try:
        slots = await calcular_slots(
            session,
            profesional_id=profesional_id,
            prestacion_id=prestacion_id,
            desde=desde,
            hasta=hasta,
        )
    except EntidadNoEncontradaError:
        return JSONResponse(status_code=404, content={"problema": "no_encontrado"})
    except VentanaInvalidaError:
        return JSONResponse(status_code=422, content={"problema": "validacion"})
    logger.info("disponibilidad consultada")
    return JSONResponse(status_code=200, content=slots)
