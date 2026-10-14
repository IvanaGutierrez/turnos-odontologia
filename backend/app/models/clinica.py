"""Modelos clínicos C-07 (capas separadas: solo ORM aquí — R2).

Espejo de la migración 008 (`008_ficha_clinica`): `Ficha` con anamnesis
cifrada app-level (`anamnesis_cifrada` BYTEA, `clave_id` por fila),
`OdontogramaEntry` por pieza/cara con FK compuesta al catálogo versionado,
`Evolucion` con texto cifrado, `Presupuesto`/`PresupuestoItem`/
`PlanTratamiento` con máquina `borrador→aprobado→pagado` y firma del
paciente como gate (RN-CL-03). Todo dato es sintético (R0).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy import Numeric as SaNumeric
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BaseModel


class CatalogoOdontogramaEstado(Base):
    """Catálogo versionado de estados (~18 en seed v1, migración 008).

    PK compuesta `(version, codigo)`: v2 agrega filas, jamás reescribe v1
    (las entries guardan su versión para preservar historia, RN-CL-02).
    """

    __tablename__ = "catalogo_odontograma_estado"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(Text, primary_key=True)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Ficha(BaseModel):
    """HCE por paciente (una fila por historia; `consentimiento_en` NOT NULL).

    `anamnesis_cifrada` guarda solo bytes (Fernet app-level en la capa de
    servicio; jamás plaintext en DB/logs). `profesional_id` es el profesional
    tratante de referencia; `firmante_usuario_id` el odontólogo JWT que firmó.
    """

    __tablename__ = "ficha"

    paciente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("paciente.id", ondelete="CASCADE"),
        nullable=False,
    )
    profesional_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profesional.id"), nullable=False
    )
    fecha: Mapped[date | None] = mapped_column(Date, nullable=True)
    anamnesis_cifrada: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    firmante_usuario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True
    )
    firmado_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consentimiento_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    clave_id: Mapped[str] = mapped_column(Text, nullable=False, default="hce-v1")


class OdontogramaEntry(BaseModel):
    """Una fila por `(ficha_id, pieza_fdi, cara)` (upsert por pieza).

    `pieza_fdi` CHECK 11–48 en DB; el servicio valida FDI real
    (11–18/21–28/31–38/41–48). FK compuesta a `(catalogo_version,
    estado_codigo)` para preservar historia ante catálogo v2.
    """

    __tablename__ = "odontograma_entry"
    __table_args__ = (
        CheckConstraint("pieza_fdi BETWEEN 11 AND 48", name="ck_odo_pieza_fdi"),
    )

    ficha_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ficha.id", ondelete="CASCADE"), nullable=False
    )
    pieza_fdi: Mapped[int] = mapped_column(Integer, nullable=False)
    estado_codigo: Mapped[str] = mapped_column(Text, nullable=False)
    catalogo_version: Mapped[int] = mapped_column(Integer, nullable=False)
    cara: Mapped[str | None] = mapped_column(Text, nullable=True)


class Evolucion(BaseModel):
    """Evolución firmada (`texto_cifrado` BYTEA, jamás plaintext fuera del servicio)."""

    __tablename__ = "evolucion"

    ficha_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ficha.id", ondelete="CASCADE"), nullable=False
    )
    texto_cifrado: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    firmante_usuario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True
    )
    firmado_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    clave_id: Mapped[str] = mapped_column(Text, nullable=False, default="hce-v1")


class Presupuesto(BaseModel):
    """Presupuesto nacido de hallazgos; `borrador→aprobado` exige firma.

    `firma_paciente_en + firma_hash` gatean la aprobación (RN-CL-03);
    `version` para inmutabilidad post-firma (cambiar exige nueva versión).
    """

    __tablename__ = "presupuesto"

    ficha_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ficha.id", ondelete="CASCADE"), nullable=False
    )
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador")
    total: Mapped[Decimal] = mapped_column(
        SaNumeric(12, 2), nullable=False, default=Decimal(0)
    )
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="ARS")
    sena_requerida: Mapped[Decimal] = mapped_column(
        SaNumeric(12, 2), nullable=False, default=Decimal(0)
    )
    firma_paciente_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    firma_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    motivo_rechazo: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PresupuestoItem(Base):
    """Item por pieza/prestación (precio viaja en el hallazgo en C-07)."""

    __tablename__ = "presupuesto_item"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    presupuesto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("presupuesto.id", ondelete="CASCADE"),
        nullable=False,
    )
    pieza_fdi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estado_codigo: Mapped[str | None] = mapped_column(Text, nullable=True)
    prestacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prestacion.id"), nullable=True
    )
    detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    precio_unitario: Mapped[Decimal] = mapped_column(SaNumeric(12, 2), nullable=False)


class PlanTratamiento(BaseModel):
    """Un plan por presupuesto (`UNIQUE presupuesto_id`); `etapas` JSONB + GIN."""

    __tablename__ = "plan_tratamiento"

    presupuesto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("presupuesto.id", ondelete="CASCADE"),
        nullable=False,
    )
    etapas: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default="planificado"
    )
    sena_requerida: Mapped[Decimal] = mapped_column(
        SaNumeric(12, 2), nullable=False, default=Decimal(0)
    )
