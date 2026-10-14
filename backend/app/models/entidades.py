"""Entidades de agenda (capas separadas: solo ORM aquí — R2)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

ESTADOS_TURNO: tuple[str, ...] = (
    "reservado",
    "confirmado",
    "presente",
    "atendido",
    "cancelado",
    "ausente",
    "reprogramado",
)

# Estados que liberan el recurso (fuera del constraint de exclusión).
ESTADOS_INACTIVOS: tuple[str, ...] = ("cancelado", "ausente", "reprogramado")


class Usuario(BaseModel):
    __tablename__ = "usuario"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[str] = mapped_column(String(30), nullable=False, default="admin")
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Paciente(BaseModel):
    __tablename__ = "paciente"

    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    dni: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)
    telefono: Mapped[str] = mapped_column(String(25), nullable=False)
    consentimiento_hc: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # C-06: sin WhatsApp → la cascada usa email/SMS sin llamar a Meta.
    sin_whatsapp: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    turnos: Mapped[list["Turno"]] = relationship(back_populates="paciente")


class Profesional(BaseModel):
    __tablename__ = "profesional"

    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    matricula: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    turnos: Mapped[list["Turno"]] = relationship(back_populates="profesional")


class Sillon(BaseModel):
    __tablename__ = "sillon"

    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    # Sede como texto en C-01; entidad multi-sede se decide en C-04.
    sede: Mapped[str] = mapped_column(
        String(100), nullable=False, default="Consultorio"
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    turnos: Mapped[list["Turno"]] = relationship(back_populates="sillon")


class Prestacion(BaseModel):
    __tablename__ = "prestacion"

    nombre: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    duracion_min: Mapped[int] = mapped_column(Integer, nullable=False)
    requiere_sena: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requiere_sillon: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # C-08: config de seña (migración 009; NULL = sin seña configurada).
    # `requiere_sena` sin monto ni % → `422` de configuración en servicio
    # (nunca monto cero silencioso, design decisión 4).
    precio_base: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    sena_monto_fijo: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    sena_porcentaje: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    turnos: Mapped[list["Turno"]] = relationship(back_populates="prestacion")


_ESTADOS_CHECK = "estado IN (" + ", ".join("'" + e + "'" for e in ESTADOS_TURNO) + ")"


class Turno(BaseModel):
    __tablename__ = "turno"
    __table_args__ = (
        CheckConstraint(
            _ESTADOS_CHECK,
            name="ck_turno_estado",
        ),
        CheckConstraint("fin > inicio", name="ck_turno_fin_mayor_inicio"),
    )

    paciente_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paciente.id"), nullable=False
    )
    profesional_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profesional.id"), nullable=False
    )
    sillon_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sillon.id"), nullable=True
    )
    prestacion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prestacion.id"), nullable=False
    )
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fin: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="reservado")
    canal: Mapped[str] = mapped_column(String(20), nullable=False, default="mostrador")
    token_publico: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    motivo_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    # C-04: sobreturno explícito (excepción auditada, design decisión 1) +
    # enlace de reprogramación (RN-AG-07, design decisión 3). `presente` es el
    # canónico de check-in (`en_sala` consolidado por la migración 005).
    sobreturno: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    motivo_sobreturno: Mapped[str | None] = mapped_column(Text, nullable=True)
    # C-05: trazabilidad de la cancelación del paciente (NULL salvo `cancelado`).
    motivo_cancelacion: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelado_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reprogramado_de_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("turno.id", ondelete="SET NULL"),
        nullable=True,
    )

    paciente: Mapped[Paciente] = relationship(back_populates="turnos")
    profesional: Mapped[Profesional] = relationship(back_populates="turnos")
    sillon: Mapped[Sillon | None] = relationship(back_populates="turnos")
    prestacion: Mapped[Prestacion] = relationship(back_populates="turnos")
