"""Pagos de seña por Mercado Pago C-08 (solo ORM aquí — R2).

Tabla `pago` (migración 009 + `init_point` en 010): un cobro de seña en
ARS por Mercado Pago. Idempotencia en dos niveles (RN-PA-03, la DB manda
ante duplicados concurrentes):

- UNIQUE `mp_payment_id` / `mp_preference_id` (el aviso duplicado del
  mismo pago nunca acredita dos veces);
- UNIQUE parcial `uq_pago_turno_pendiente` (UN solo `pendiente` por
  turno; el reintento tras rechazo crea uno nuevo solo cuando el
  anterior ya no está pendiente).

Máquina: `pendiente → acreditado | rechazado`; `acreditado → reembolsado`
solo manual (fuera de scope, modelado para C-09). `webhook_recibido_at`
marca la confirmación contra MP. `init_point` persiste el link vigente
para reutilizarlo sin crear preferencias de más.

Privacidad (R6): esta tabla jamás guarda PII del pagador (sin email,
tarjeta, DNI ni teléfono) — solo IDs, monto, moneda y estados.
Todo dato de prueba sintético (R0); type hints siempre (R1).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel

ESTADOS_PAGO: tuple[str, ...] = (
    "pendiente",
    "acreditado",
    "rechazado",
    "reembolsado",
)

MONEDA_SENA = "ARS"
METODO_SENA = "mercadopago"


def _lista(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


class Pago(BaseModel):
    """Un cobro de seña (MP) vinculado a un turno y/o presupuesto."""

    __tablename__ = "pago"
    __table_args__ = (
        CheckConstraint("monto >= 0", name="ck_pago_monto"),
        CheckConstraint("moneda = 'ARS'", name="ck_pago_moneda_ars"),
        CheckConstraint("metodo = 'mercadopago'", name="ck_pago_metodo_mp"),
        CheckConstraint(
            f"estado IN ({_lista(ESTADOS_PAGO)})",
            name="ck_pago_estado",
        ),
        UniqueConstraint("mp_payment_id", name="uq_pago_mp_payment"),
        UniqueConstraint("mp_preference_id", name="uq_pago_mp_preference"),
        Index("ix_pago_turno", "turno_id"),
        Index("ix_pago_estado", "estado"),
        Index(
            "uq_pago_turno_pendiente",
            "turno_id",
            unique=True,
            postgresql_where=text("estado = 'pendiente'"),
        ),
    )

    paciente_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("paciente.id", ondelete="SET NULL"),
        nullable=True,
    )
    turno_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("turno.id", ondelete="SET NULL"),
        nullable=True,
    )
    presupuesto_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("presupuesto.id", ondelete="SET NULL"),
        nullable=True,
    )
    monto: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="ARS")
    metodo: Mapped[str] = mapped_column(
        String(20), nullable=False, default="mercadopago"
    )
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    mp_payment_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    mp_preference_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Link vigente de la preferencia (reuso sin duplicar, C-08).
    init_point: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_recibido_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
