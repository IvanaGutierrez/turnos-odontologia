"""Webhook Mercado Pago C-08 (design decisión 5, fuera de `/api/v1`, sin JWT).

`POST /webhooks/mercadopago` exige `x-signature: ts=...,v1=...` con
`v1 = HMAC-SHA256(MP_WEBHOOK_SECRET,
"id:{data.id};request-id:{x-request-id};ts:{ts};")` comparado con
`hmac.compare_digest`. Ausente/inválida/cuerpo alterado →
`401` ciego (genérico, sin procesar, sin mutar, sin auditar contenido).

Tras verificar, el estado se confirma contra MP (Fake en tests), nunca
desde el cuerpo (el cuerpo es falsificable; la firma solo autentica el
aviso). Aviso duplicado del mismo `mp_payment_id` → `200` idempotente
sin doble efecto (RN-PA-03, la DB manda).

MP caído → `503` pinneado (decisión documentada: reintentable por MP,
nunca acredita por defecto; turno `reservado` + aviso a recepción por
auditoría `pago_mp_no_disponible`).

R6: ningún log/response/auditoría contiene PII del pagador ni tokens
(solo IDs, monto, moneda y estados). R7: secreto solo por env.
R0: montos sintéticos, Fake en tests, jamás red real en la suite.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.logger import get_logger
from app.core.settings import settings
from app.infrastructure.mercadopago.client import (
    MercadoPagoNoDisponibleError,
    cliente_para_app,
)
from app.schemas.pagos import AvisoMP
from app.services.pagos import procesar_aviso

logger = get_logger(__name__)

router = APIRouter(tags=["webhooks-mp"])

RUTA_WEBHOOK = "/webhooks/mercadopago"

DETALLE_401 = "No autorizado."
DETALLE_503 = "El cobro no está disponible; reintentá más tarde."


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _extraer_partes_firma(cabecera: str | None) -> tuple[str | None, str | None]:
    """`(ts, v1)` de `x-signature: ts=...,v1=...` (`(None, None)` si mal)."""
    if not cabecera:
        return None, None
    partes: dict[str, str] = {}
    for trozo in cabecera.split(","):
        clave, _, valor = trozo.partition("=")
        partes[clave.strip()] = valor.strip()
    ts = partes.get("ts") or None
    v1 = partes.get("v1") or None
    return ts, v1


def firma_valida(
    *, mp_payment_id: str, firma: str | None, request_id: str | None, secreto: str
) -> bool:
    """Compara en tiempo constante (ciego ante timing attacks)."""
    ts, v1 = _extraer_partes_firma(firma)
    if not ts or not v1 or not request_id or not mp_payment_id:
        return False
    base = f"id:{mp_payment_id};request-id:{request_id};ts:{ts};"
    esperada = hmac.new(
        secreto.encode("utf-8"), base.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(esperada, v1)


def _mp_id_del_cuerpo(cuerpo: bytes) -> str | None:
    """`data.id` del aviso (`None` si el cuerpo no es JSON válido)."""
    try:
        datos: Any = json.loads(cuerpo)
    except ValueError:
        return None
    if not isinstance(datos, dict):
        return None
    data = datos.get("data")
    if not isinstance(data, dict):
        return None
    mp_id = data.get("id")
    return str(mp_id) if isinstance(mp_id, str) and mp_id else None


@router.post(RUTA_WEBHOOK, summary="Aviso de pago MP verificado (idempotente)")
async def recibir_aviso(
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> JSONResponse:
    cuerpo = await request.body()
    mp_id = _mp_id_del_cuerpo(cuerpo)
    firma = request.headers.get("x-signature")
    request_id = request.headers.get("x-request-id")
    if mp_id is None or not firma_valida(
        mp_payment_id=mp_id,
        firma=firma,
        request_id=request_id,
        secreto=settings.mp_webhook_secret,
    ):
        # 401 ciego: sin procesar, sin mutar, sin auditar, sin PII en logs.
        logger.warning("webhook mp sin firma válida")
        return JSONResponse(status_code=401, content={"detalle": DETALLE_401})
    try:
        AvisoMP.model_validate_json(cuerpo)
    except Exception:  # noqa: BLE001 — firmado pero no parseable: no acredita.
        logger.warning("webhook mp con cuerpo inválido")
        await session.rollback()
        return JSONResponse(status_code=401, content={"detalle": DETALLE_401})
    try:
        resultado = await procesar_aviso(
            session,
            mp_payment_id=mp_id,
            client=cliente_para_app(request.app),
            ip=_ip(request),
        )
    except MercadoPagoNoDisponibleError:
        logger.warning("webhook mp degradado: mp caído")
        return JSONResponse(status_code=503, content={"detalle": DETALLE_503})
    _ = resultado
    return JSONResponse(status_code=200, content={"recibido": True})
