"""Reserva pública C-03: `POST /api/v1/turnos/publicos` (sin JWT).

Header `Idempotency-Key` obligatorio; `201 reservado + token_publico`
(`url_pago` opaca si requiere seña, sin crear `Pago` — C-08); `422`/`429`
genéricos anti-enumeración; `409` con el handler y shape de C-01.
Router separado de los protegidos.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.publicos import TurnoPublicoCreate
from app.services.reserva_publica import reservar_turno_publico

router = APIRouter(prefix="/turnos/publicos", tags=["turnos-publicos"])


@router.post("", summary="Reservar turno sin cuenta")
async def post_turno_publico(
    datos: TurnoPublicoCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    clave_idempotencia: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    if not clave_idempotencia or not clave_idempotencia.strip():
        return JSONResponse(
            status_code=422,
            content={
                "problema": "validacion",
                "detalle": "Falta el header Idempotency-Key.",
            },
        )
    cuerpo, estado, espera = await reservar_turno_publico(
        session,
        request.app.state.redis,
        datos=datos,
        clave=clave_idempotencia.strip(),
        ip=request.client.host if request.client else None,
    )
    headers = {"Retry-After": str(espera)} if estado == 429 and espera else None
    return JSONResponse(status_code=estado, content=cuerpo, headers=headers)
