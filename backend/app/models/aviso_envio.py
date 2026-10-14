"""Avisos de envío de notificaciones C-06 (solo ORM aquí — R2).

Tabla `aviso_envio`: idempotencia durable + auditoría de los 3 envíos
utility (`confirmacion`, `recordatorio_24h`, `aviso_3h`). El reclamo
transaccional del worker y el `SET NX` de Redis viven en la parte 2
(`workers/envios.py` + scheduler); aquí solo el shape durable.

Timestamps: `creado_en`/`actualizado_en` heredados de `BaseModel`
(equivalen a `created_at`); `enviado_en` equivale a `sent_at`.

Privacidad (R6): jamás teléfonos/DNI/HC en esta tabla — solo
`payload_hash` (sha256 del payload) y FKs/estados/horas.
Todo dato de prueba sintético (R0); type hints siempre (R1).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.entidades import Turno

TIPOS_AVISO: tuple[str, ...] = (
    "confirmacion",
    "recordatorio_24h",
    "aviso_3h",
    # C-08: comprobante de pago acreditado (migración 010 extiende
    # `ck_aviso_tipo`; se inserta directo desde el servicio de pagos, sin
    # pasar por el veto marketing de C-06 — no es marketing).
    "comprobante_pago",
)

ESTADOS_AVISO: tuple[str, ...] = (
    "pendiente",
    "enviando",
    "enviado",
    "reintentar",
    "fallido",
    "fallback",
    "cancelado",
)


def _lista(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


class AvisoEnvio(BaseModel):
    """Un envío utility por (turno, tipo): exactamente-una-vez durable."""

    __tablename__ = "aviso_envio"
    __table_args__ = (
        CheckConstraint(
            f"tipo_aviso IN ({_lista(TIPOS_AVISO)})",
            name="ck_aviso_tipo",
        ),
        CheckConstraint(
            f"estado IN ({_lista(ESTADOS_AVISO)})",
            name="ck_aviso_estado",
        ),
        UniqueConstraint("turno_id", "tipo_aviso", name="uq_aviso_turno_tipo"),
        UniqueConstraint("proveedor_msg_id", name="uq_aviso_proveedor_msg"),
    )

    turno_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("turno.id", ondelete="CASCADE"),
        nullable=False,
    )
    tipo_aviso: Mapped[str] = mapped_column(String(20), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    proveedor_msg_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enviado_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # C-06 GREEN: ventana de envío (`inicio - RECORDATORIO/AVISO_MIN`).
    # El worker solo envía filas con `programado_para <= ahora`
    # (`NULL` = vencido/due inmediato, p. ej. la `confirmacion`).
    programado_para: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    turno: Mapped[Turno] = relationship("Turno")
