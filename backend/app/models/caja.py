"""Modelos de caja y cierre diario C-09 (solo ORM aquí — R2).

Espejo de la migración 011 (`011_caja_cierre_diario`):

- `MovimientoCaja`: ingreso/egreso manual por método
  (`efectivo|transferencia|tarjeta|mercadopago`, RN-PA-05) con
  `usuario_id` del operador (FK `SET NULL`) y `pago_id` FK NULL opcional
  (ata un ingreso MP a su pago C-08). `monto > 0`, `concepto` 1–280
  (el servicio lo excluye de logs/auditoría/responses — R6),
  `origen manual|mercadopago` (default `manual`). Índice
  `(fecha, sede)` para el arqueo + UNIQUE parcial `pago_id` (un pago
  en un solo movimiento de ingreso).
- `CierreDiario`: snapshot por día/sede (sede texto default
  `"Consultorio"`, patrón `Sillon.sede`) con totales por método,
  `acreditado_mp` (leído de `pago`, solo lectura) y `diferencia`
  (`total_mp − acreditado_mp`; `estado_conciliacion` se deriva en
  servicio: `diferencia == 0` → `cuadrado`). Máquina
  `abierto→cerrado` (cierre) / `cerrado→abierto` (reapertura admin,
  con `reaperturas+1`). `UNIQUE(fecha, sede)`: la DB manda ante
  doble cierre concurrente → `409` (RN-PA-04).

Todo dato de prueba sintético (R0); type hints siempre (R1).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import Numeric as SaNumeric
from sqlalchemy import String as SaString
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel

TIPOS_MOVIMIENTO: tuple[str, ...] = ("ingreso", "egreso")

METODOS_CAJA: tuple[str, ...] = (
    "efectivo",
    "transferencia",
    "tarjeta",
    "mercadopago",
)

ORIGENES_MOVIMIENTO: tuple[str, ...] = ("manual", "mercadopago")

ESTADOS_CIERRE: tuple[str, ...] = ("abierto", "cerrado")

SEDE_DEFAULT = "Consultorio"


def _lista(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


class MovimientoCaja(BaseModel):
    """Un ingreso/egreso manual de caja (el concepto se almacena, jamás se loguea)."""

    __tablename__ = "movimiento_caja"
    __table_args__ = (
        CheckConstraint(
            f"tipo IN ({_lista(TIPOS_MOVIMIENTO)})", name="ck_movcaja_tipo"
        ),
        CheckConstraint(
            f"metodo IN ({_lista(METODOS_CAJA)})", name="ck_movcaja_metodo"
        ),
        CheckConstraint("monto > 0", name="ck_movcaja_monto"),
        CheckConstraint(
            "char_length(concepto) BETWEEN 1 AND 280",
            name="ck_movcaja_concepto",
        ),
        CheckConstraint(
            f"origen IN ({_lista(ORIGENES_MOVIMIENTO)})",
            name="ck_movcaja_origen",
        ),
        Index("ix_movcaja_fecha_sede", "fecha", "sede"),
        Index(
            "uq_movcaja_pago_unico",
            "pago_id",
            unique=True,
            postgresql_where=text("pago_id IS NOT NULL"),
        ),
    )

    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    sede: Mapped[str] = mapped_column(Text, nullable=False, default=SEDE_DEFAULT)
    tipo: Mapped[str] = mapped_column(SaString(10), nullable=False)
    concepto: Mapped[str] = mapped_column(Text, nullable=False)
    monto: Mapped[Decimal] = mapped_column(SaNumeric(12, 2), nullable=False)
    metodo: Mapped[str] = mapped_column(SaString(20), nullable=False)
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("usuario.id", ondelete="SET NULL"),
        nullable=True,
    )
    pago_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pago.id", ondelete="SET NULL"),
        nullable=True,
    )
    origen: Mapped[str] = mapped_column(SaString(20), nullable=False, default="manual")


class CierreDiario(BaseModel):
    """Snapshot de un día/sede (UN renglón por `fecha,sede` — la DB manda)."""

    __tablename__ = "cierre_diario"
    __table_args__ = (
        CheckConstraint(
            f"estado IN ({_lista(ESTADOS_CIERRE)})", name="ck_cierre_estado"
        ),
        CheckConstraint("reaperturas >= 0", name="ck_cierre_reaperturas"),
        UniqueConstraint("fecha", "sede", name="uq_cierre_fecha_sede"),
    )

    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    sede: Mapped[str] = mapped_column(Text, nullable=False, default=SEDE_DEFAULT)
    total_efectivo: Mapped[Decimal] = mapped_column(
        SaNumeric(12, 2), nullable=False, default=Decimal(0)
    )
    total_transferencia: Mapped[Decimal] = mapped_column(
        SaNumeric(12, 2), nullable=False, default=Decimal(0)
    )
    total_tarjeta: Mapped[Decimal] = mapped_column(
        SaNumeric(12, 2), nullable=False, default=Decimal(0)
    )
    total_mp: Mapped[Decimal] = mapped_column(
        SaNumeric(12, 2), nullable=False, default=Decimal(0)
    )
    total_egresos: Mapped[Decimal] = mapped_column(
        SaNumeric(12, 2), nullable=False, default=Decimal(0)
    )
    acreditado_mp: Mapped[Decimal] = mapped_column(
        SaNumeric(12, 2), nullable=False, default=Decimal(0)
    )
    diferencia: Mapped[Decimal] = mapped_column(
        SaNumeric(12, 2), nullable=False, default=Decimal(0)
    )
    estado: Mapped[str] = mapped_column(SaString(20), nullable=False, default="cerrado")
    cerrado_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("usuario.id", ondelete="SET NULL"),
        nullable=True,
    )
    cerrado_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reaperturas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
