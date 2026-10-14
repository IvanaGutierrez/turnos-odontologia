"""Link de pago de seña C-08: `GET /pagar/:token` (sin JWT, fuera de `/api/v1`).

Resuelve el link opaco firmado de C-03 (`url_pago_para`) a la
preferencia MP real: verifica el token (`token_publico` + firma HMAC
con `PAGO_LINK_SECRET`), calcula la seña y devuelve `{init_point,
monto, moneda:'ARS', estado_pago}` sin PII (R6).

- Token/firma inválidos o turno fuera de scope → `404` idéntico
  (mismo cuerpo siempre, anti-enumeración R6).
- Seña sin configurar o no requerida → `422` sin crear preferencia.
- MP caído → `503` pinneado (turno `reservado`, mismo link reintenta).
- Rate limit público por IP ANTES de resolver (patrón C-03/C-05).

R0: montos sintéticos; R7: secretos solo por env.
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.logger import get_logger
from app.core.settings import settings
from app.infrastructure.mercadopago.client import (
    MercadoPagoNoDisponibleError,
    cliente_para_app,
)
from app.models.entidades import Turno
from app.services.autogestion import (
    DETALLE_RATELIMIT,
    NO_ENCONTRADO,
    chequear_rate_ip,
    resolver_por_token,
)
from app.services.pagos import SenaSinConfigurarError, link_pago_para

logger = get_logger(__name__)

router = APIRouter(tags=["pagos-sena"])

RUTA_PAGAR = "/pagar/{token}"

# Solo turnos con gestión de cobro abierta resuelven link de pago.
ESTADOS_COBRABLES: frozenset[str] = frozenset({"reservado", "confirmado"})


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def firma_link_valida(turno: Turno, firma: str | None) -> bool:
    """Verifica la firma opaca de `url_pago_para` (tiempo constante)."""
    if not firma:
        return False
    esperada = hmac.new(
        settings.pago_link_secret.encode("utf-8"),
        str(turno.id).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    return hmac.compare_digest(esperada, firma)


def _no_encontrado() -> JSONResponse:
    """404 idéntico siempre (misma serialización, sin PII)."""
    return JSONResponse(status_code=404, content=dict(NO_ENCONTRADO))


@router.get(RUTA_PAGAR, summary="Link de pago de la seña (token opaco)")
async def obtener_link_pago(
    token: str,
    request: Request,
    firma: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> JSONResponse:
    freno = await chequear_rate_ip(request.app.state.redis, _ip(request))
    if freno is not None:
        _, espera = freno
        headers = {"Retry-After": str(espera)} if espera else None
        return JSONResponse(
            status_code=429, content={"detalle": DETALLE_RATELIMIT}, headers=headers
        )
    turno = await resolver_por_token(session, token)
    if (
        turno is None
        or turno.estado not in ESTADOS_COBRABLES
        or not firma_link_valida(turno, firma)
    ):
        return _no_encontrado()
    try:
        cuerpo = await link_pago_para(
            session, turno, client=cliente_para_app(request.app), ip=_ip(request)
        )
    except SenaSinConfigurarError as exc:
        logger.warning("seña sin configurar")
        await session.rollback()
        return JSONResponse(
            status_code=422,
            content={
                "problema": "sena_sin_configurar",
                "detalle": (
                    "La seña no está configurada para esta prestación; "
                    "comunicate con el consultorio."
                ),
                "motivo": str(exc),
            },
        )
    except MercadoPagoNoDisponibleError:
        logger.warning("mp caído al resolver link de pago")
        return JSONResponse(
            status_code=503,
            content={"detalle": "El cobro no está disponible; reintentá más tarde."},
        )
    return JSONResponse(status_code=200, content=cuerpo)
