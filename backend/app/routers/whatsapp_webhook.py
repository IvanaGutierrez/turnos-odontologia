"""Webhook WhatsApp C-06 + conversación C-12 (fuera de `/api/v1`, sin JWT).

- `GET /webhooks/whatsapp`: suscripción Meta (`hub.mode=subscribe` +
  `hub.verify_token == WHATSAPP_VERIFY_TOKEN` → `200` con el challenge;
  si no → `403` genérico, sin eco del challenge ni del secreto).
- `POST /webhooks/whatsapp`: exige `X-Hub-Signature-256 =
  HMAC-SHA256(WHATSAPP_WEBHOOK_SECRET, body)` con `hmac.compare_digest`;
  ausente/inválida/cuerpo alterado → `401` ciego (`{"detalle": ...}`
  genérico), sin procesar, sin mutar agenda, sin auditar contenido y sin
  loguear PII (contrato C-06 intacto). Firma válida → dedupe por
  `wa_message_id` (`200` sin re-mutar ni re-responder ante reintento
  Meta) → rate-limit por remitente-hash → enrutado al handler
  conversacional C-12 (`services/conversacion_whatsapp`, `canal=whatsapp`).
  La respuesta se registra junto a `aviso_recibido` con `respuesta` por
  tipo (sin texto libre, R6); `GET` verify sin cambios.

R6: ningún log contiene teléfonos, textos libres ni tokens. R7: secreto
y token de verificación solo por env. R0: remitentes ficticios.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.logger import get_logger
from app.core.settings import settings
from app.models.auditoria import AuditoriaLog
from app.repositories import auditoria as repo_auditoria
from app.schemas.avisos import WebhookAck, WebhookInbound

logger = get_logger(__name__)

router = APIRouter(tags=["webhooks-whatsapp"])

RUTA_WEBHOOK = "/webhooks/whatsapp"

DETALLE_401 = "No autorizado."
DETALLE_403 = "Verificación rechazada."


def _firmar(cuerpo: bytes, secreto: str) -> str:
    firma = hmac.new(secreto.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()
    return f"sha256={firma}"


def firma_valida(cuerpo: bytes, cabecera: str | None, secreto: str) -> bool:
    """Compara en tiempo constante (ciego ante timing attacks)."""
    if not cabecera:
        return False
    return hmac.compare_digest(cabecera, _firmar(cuerpo, secreto))


@router.get(
    RUTA_WEBHOOK, summary="Verificación de suscripción Meta", response_model=None
)
async def verificar_suscripcion(
    mode: Annotated[str, Query(alias="hub.mode")] = "",
    verify_token: Annotated[str, Query(alias="hub.verify_token")] = "",
    challenge: Annotated[str, Query(alias="hub.challenge")] = "",
) -> PlainTextResponse | JSONResponse:
    if mode == "subscribe" and verify_token == settings.whatsapp_verify_token:
        return PlainTextResponse(challenge)
    logger.warning("verificación de webhook rechazada")
    return JSONResponse(status_code=403, content={"detalle": DETALLE_403})


@router.post(RUTA_WEBHOOK, summary="Inbound WhatsApp verificado + bot C-12")
async def recibir_inbound(
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> JSONResponse:
    cuerpo = await request.body()
    firma = request.headers.get("x-hub-signature-256")
    if not firma_valida(cuerpo, firma, settings.whatsapp_webhook_secret):
        # 401 ciego: sin procesar, sin mutar, sin auditar, sin PII en logs.
        logger.warning("webhook sin firma válida")
        return JSONResponse(status_code=401, content={"detalle": DETALLE_401})
    try:
        inbound = WebhookInbound.model_validate_json(cuerpo)
    except Exception:  # noqa: BLE001 — cuerpo firmado pero no parseable.
        logger.warning("webhook con cuerpo inválido")
        return JSONResponse(
            status_code=422,
            content={
                "problema": "validacion",
                "detalle": "La solicitud contiene datos inválidos.",
            },
        )
    previos = (
        (
            await session.execute(
                select(AuditoriaLog)
                .where(AuditoriaLog.accion == "aviso_recibido")
                .order_by(AuditoriaLog.creado_en.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    for previo in previos:
        diff = previo.diff if isinstance(previo.diff, dict) else {}
        if diff.get("wa_message_id") == inbound.wa_message_id:
            return JSONResponse(
                status_code=200,
                content=WebhookAck(duplicado=True).model_dump(),
            )
    # C-12: rate-limit por remitente-hash (antes de procesar, R6 sin PII).
    from app.services.conversacion_whatsapp import (
        chequear_rate_conv,
        hash_remitente,
        procesar_mensaje,
    )

    if inbound.remitente:
        remitente_hash = hash_remitente(inbound.remitente)
    elif inbound.remitente_hash:
        remitente_hash = str(inbound.remitente_hash)
    else:
        remitente_hash = hash_remitente("desconocido")
    espera = await chequear_rate_conv(request.app.state.redis, remitente_hash)
    if espera is not None:
        logger.warning("rate-limit conversacional")
        return JSONResponse(
            status_code=429,
            content={"detalle": "Demasiados intentos. Reintentá más tarde."},
            headers={"Retry-After": str(espera)},
        )
    estado, respuesta = await procesar_mensaje(
        session,
        request.app.state.redis,
        remitente=inbound.remitente,
        texto=inbound.texto,
        wa_message_id=inbound.wa_message_id,
    )
    # La respuesta se registra junto a `aviso_recibido` por tipo, sin
    # texto libre ni PII (el reintento Meta ve el dedupe, sin re-mutar).
    tipo_respuesta = _tipo_respuesta(estado, respuesta)
    await repo_auditoria.registrar_auditoria(
        session,
        accion="aviso_recibido",
        entidad="aviso_envio",
        entidad_id=inbound.turno_id,
        diff={
            "wa_message_id": inbound.wa_message_id,
            "remitente": remitente_hash,
            "timestamp": inbound.timestamp,
            "tipo": inbound.tipo,
            "respuesta": tipo_respuesta,
        },
    )
    await session.commit()
    logger.info("inbound verificado y procesado")
    return JSONResponse(status_code=estado, content=respuesta)


def _tipo_respuesta(estado: int, respuesta: dict[str, object]) -> str:
    """Etiqueta de la respuesta saliente (trazabilidad sin texto libre)."""
    if estado == 429:
        return "rate_limit"
    if estado == 409:
        return "colision_slot"
    if estado == 422:
        return "terminal"
    mensaje = str(respuesta.get("mensaje", "")).lower()
    if "url_pago" in respuesta or ("pag" in mensaje and "http" in mensaje):
        return "sena_pendiente"
    if "expir" in mensaje or "venci" in mensaje:
        return "oferta_expirada"
    if "opci" in mensaje and ("reprogramar" in mensaje or "slot" in mensaje):
        return "propuesta_slots"
    if "eleg" in mensaje:
        return "desambiguacion"
    if "confirm" in mensaje and "cancelar" in mensaje:
        return "ayuda"
    if "no encontramos" in mensaje:
        return "desconocido"
    if "confirmado" in mensaje or "reprogram" in mensaje or "cancelado" in mensaje:
        return "mutacion"
    return f"http_{estado}"
