"""Contratos de cobro de seña C-08 (documentan sin mirar el código, 3.3).

- `GET /pagar/:token` (token opaco C-03, sin JWT): `200` con
  `{init_point, monto, moneda:'ARS', estado_pago}` donde `estado_pago`
  es `pendiente|acreditado|rechazado`; token/firma inválidos → `404`
  idéntico; seña sin configurar → `422`; MP caído → `503` (pinneado,
  el turno sigue `reservado` y el mismo link reintenta).
- `POST /webhooks/mercadopago` (sin JWT, firma `x-signature`
  obligatoria): `200` con `{recibido: true}` ante aviso procesado o
  duplicado idempotente; `401` ciego ante firma inválida; `503` ante
  MP caído (nunca acredita por defecto).
- Monto de la seña por prestación: `sena_monto_fijo` gana a
  `sena_porcentaje` sobre `precio_base`; sin ninguno → `422` de
  configuración (nunca cero silencioso).
- Idempotencia: UNIQUEs `mp_payment_id`/`mp_preference_id` + UN
  pendiente por turno (la DB manda ante carreras).
- R6: ningún contrato expone PII del pagador (solo IDs, monto,
  moneda y estados).

Todo dato sintético (R0); type hints siempre (R1).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PagoLinkResponse(BaseModel):
    """Respuesta de `GET /pagar/:token` (link vigente + estado visible)."""

    model_config = ConfigDict(from_attributes=True)

    init_point: str | None = Field(
        default=None,
        description="Link de pago MP vigente (ausente si aún no hay preferencia).",
    )
    monto: str = Field(description="Monto de la seña en ARS (decimal como texto).")
    moneda: Literal["ARS"] = Field(description="Moneda fija de las señas.")
    estado_pago: Literal["pendiente", "acreditado", "rechazado"] = Field(
        description="Estado visible para mostrar 'pago rechazado, reintentá'."
    )


class AvisoMPData(BaseModel):
    """`data` del aviso MP (solo el id; el resto del cuerpo se ignora)."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, description="`mp_payment_id` a confirmar contra MP.")


class AvisoMP(BaseModel):
    """Aviso `payment` mínimo (el bloque `pagador` jamás se parsea — R6)."""

    model_config = ConfigDict(extra="ignore")

    type: str = Field(description="Tipo de aviso (p.ej. `payment`).")
    data: AvisoMPData


class WebhookMpAck(BaseModel):
    """Acuse del webhook (sin eco del `mp_payment_id` ni PII — R6)."""

    recibido: bool = Field(description="`True` siempre en `200` (incl. duplicado).")
