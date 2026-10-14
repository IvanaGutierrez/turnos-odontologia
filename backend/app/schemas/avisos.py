"""Schemas de avisos C-06 (contratos observables sin mirar el código).

Estados de `aviso_envio`: `pendiente|enviando|enviado|reintentar|fallido|
fallback|cancelado` (+ `intentos`, `programado_para`, `enviado_en`).

Claves Redis: `wa:envios` (lista de jobs `turno_id:tipo`), `wa:reintentos`
(sorted-set `aviso_id → not_before` del backoff), `wa:muertos` (DLQ),
`aviso:{turno_id}:{tipo}` (`SET NX EX 7d`, deduplicación rápida).

Cascada de fallback: WhatsApp → email SMTP → SMS gateway; si todo canal
automático falla → `aviso_a_recepcion` (gestión manual, turno intacto).

Webhook: `GET /webhooks/whatsapp` (verify con `hub.verify_token`) y
`POST /webhooks/whatsapp` con `X-Hub-Signature-256 = HMAC-SHA256(secret,
body)`; firma ausente/inválida → `401` ciego `{"detalle": ...}` sin
procesar, sin mutar, sin auditar contenido y sin PII en logs.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AvisoEnvioRead(BaseModel):
    """Estado de un aviso, consultable por `turno_id` (recepción, sin PII)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    turno_id: uuid.UUID
    tipo_aviso: str = Field(
        description="confirmacion|recordatorio_24h|aviso_3h (otro → 422)"
    )
    estado: str = Field(
        description="pendiente|enviando|enviado|reintentar|fallido|fallback|cancelado"
    )
    intentos: int
    proveedor_msg_id: str | None = None
    programado_para: datetime | None = None
    enviado_en: datetime | None = None


class WebhookInbound(BaseModel):
    """Cuerpo entrante verificado (estricto; el texto libre jamás se loguea).

    C-06 solo extraía `wa_message_id`/`remitente_hash`/`timestamp`/`tipo`.
    C-12 extiende con `texto` + `remitente` E.164 (el handler conversacional
    los usa; `extra="ignore"` mantiene forward-compat con Meta).
    Clave `wa:conv:{hash}` y TTL, extensión de `aviso_recibido` con
    `respuesta` (tipo, sin texto libre): ver `services/conversacion_whatsapp`.
    """

    model_config = ConfigDict(extra="ignore")

    wa_message_id: str = Field(min_length=1, max_length=100)
    remitente_hash: str | None = Field(default=None, max_length=64)
    remitente: str | None = Field(default=None, max_length=40)
    texto: str | None = Field(default=None, max_length=2000)
    timestamp: str | None = None
    tipo: str | None = None
    turno_id: str | None = None


class WebhookAck(BaseModel):
    """Acuse de recibo idempotente (`duplicado=True` ante reintento Meta)."""

    estado: str = "recibido"
    duplicado: bool = False
