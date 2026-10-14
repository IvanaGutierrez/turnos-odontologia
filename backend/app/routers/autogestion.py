"""Autogestión del paciente C-05: `GET/POST /turnos/publicos/:token` (sin JWT).

Router separado del protegido (patrón C-03). El token viaja en path, nunca
en query (evita que quede en logs de proxy). Rate limit por IP ANTES de
resolver el token (el `429` no revela si existe). Token desconocido →
`404` byte-idéntico en los cuatro endpoints (R6 anti-enumeración).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.publicos import CancelarPublicoRequest, ReprogramarPublicoRequest
from app.services.autogestion import (
    DETALLE_RATELIMIT,
    NO_ENCONTRADO,
    ahora_utc,
    cancelar_por_token,
    chequear_rate_ip,
    confirmar_por_token,
    reprogramar_por_token,
    ver_por_token,
)

router = APIRouter(prefix="/turnos/publicos", tags=["autogestion"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _freno_o_nada(request: Request) -> JSONResponse | None:
    """`429` con `Retry-After` si se excede el tope por IP (sin procesar)."""
    freno = await chequear_rate_ip(request.app.state.redis, _ip(request))
    if freno is None:
        return None
    _, espera = freno
    headers = {"Retry-After": str(espera)} if espera else None
    return JSONResponse(
        status_code=429, content={"detalle": DETALLE_RATELIMIT}, headers=headers
    )


def _no_encontrado() -> JSONResponse:
    """404 idéntico siempre (misma serialización, sin PII ni horarios)."""
    return JSONResponse(status_code=404, content=dict(NO_ENCONTRADO))


@router.get("/{token}", summary="Ver turno propio con token (campos mínimos)")
async def get_turno_propio(
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> JSONResponse:
    if (freno := await _freno_o_nada(request)) is not None:
        return freno
    cuerpo = await ver_por_token(session, token, ahora=ahora_utc())
    if cuerpo is None:
        return _no_encontrado()
    return JSONResponse(status_code=200, content=cuerpo)


@router.post("/{token}/confirmar", summary="Confirmar turno con token")
async def post_confirmar_por_token(
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> JSONResponse:
    if (freno := await _freno_o_nada(request)) is not None:
        return freno
    cuerpo = await confirmar_por_token(session, token, ip=_ip(request))
    if cuerpo is None:
        return _no_encontrado()
    return JSONResponse(status_code=200, content=cuerpo)


@router.post("/{token}/cancelar", summary="Cancelar turno con token (en término)")
async def post_cancelar_por_token(
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    datos: CancelarPublicoRequest | None = None,
) -> JSONResponse:
    if (freno := await _freno_o_nada(request)) is not None:
        return freno
    cuerpo = await cancelar_por_token(
        session,
        token,
        motivo=datos.motivo if datos is not None else None,
        ahora=ahora_utc(),
        ip=_ip(request),
    )
    if cuerpo is None:
        return _no_encontrado()
    return JSONResponse(status_code=200, content=cuerpo)


@router.post("/{token}/reprogramar", summary="Reprogramar turno con token")
async def post_reprogramar_por_token(
    token: str,
    datos: ReprogramarPublicoRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> JSONResponse:
    if (freno := await _freno_o_nada(request)) is not None:
        return freno
    nuevo = await reprogramar_por_token(
        session, token, nuevo_inicio=datos.nuevo_inicio, ip=_ip(request)
    )
    if nuevo is None:
        return _no_encontrado()
    return JSONResponse(
        status_code=201,
        content={
            "id": str(nuevo.id),
            "token_publico": str(nuevo.token_publico),
            "estado": str(nuevo.estado),
            "inicio": nuevo.inicio.isoformat(),
            "fin": nuevo.fin.isoformat(),
        },
    )
