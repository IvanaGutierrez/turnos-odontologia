"""Agenda pública C-03: horarios, bloqueos, idempotencia y verificación (R2).

Solo ORM aquí (capas separadas); jamás PII en claro (R6): la verificación
guarda únicamente hashes SHA-256 hex (64 chars) de DNI/teléfono/código.
Los endpoints y servicios que usan estas tablas llegan en la parte 2
(GREEN); este archivo + la migración 003 son el alcance de la parte 1.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Time,
    UniqueConstraint,
)
from sqlalchemy import Integer as SaInteger
from sqlalchemy import String as SaString
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel

# SHA-256 hex digerido (fijado por contrato con los tests C-03).
HASH_HEX_LEN = 64


class HorarioProfesional(BaseModel):
    """Franja semanal recurrente de un profesional (0=lunes … 6=domingo)."""

    __tablename__ = "horario_profesional"
    __table_args__ = (
        CheckConstraint(
            "dia_semana BETWEEN 0 AND 6", name="ck_horario_dia_semana"
        ),
        CheckConstraint("hora_fin > hora_inicio", name="ck_horario_horas"),
    )

    profesional_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profesional.id", ondelete="CASCADE"),
        nullable=False,
    )
    dia_semana: Mapped[int] = mapped_column(SaInteger, nullable=False)
    hora_inicio: Mapped[time] = mapped_column(Time, nullable=False)
    hora_fin: Mapped[time] = mapped_column(Time, nullable=False)
    vigente_desde: Mapped[date | None] = mapped_column(Date, nullable=True)
    vigente_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    activo: Mapped[bool] = mapped_column(nullable=False, default=True)


class Bloqueo(BaseModel):
    """Excepción puntual (feriado, vacaciones, cierre de sillón/sede).

    `profesional_id` NULL = bloqueo de sillón/sede (no ata a un profesional).
    """

    __tablename__ = "bloqueo"
    __table_args__ = (
        CheckConstraint("hasta > desde", name="ck_bloqueo_rango"),
    )

    profesional_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profesional.id", ondelete="CASCADE"),
        nullable=True,
    )
    sillon_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sillon.id", ondelete="CASCADE"),
        nullable=True,
    )
    desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hasta: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    motivo: Mapped[str | None] = mapped_column(SaString(200), nullable=True)
    creado_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("usuario.id", ondelete="SET NULL"),
        nullable=True,
    )


class ClaveIdempotencia(BaseModel):
    """Clave `Idempotency-Key` persistida (la DB sobrevive a reinicios).

    Primera escritura en la misma transacción que el turno; `turno_id`
    NULL = clave reservada pero turno aún no creado (ventana de carrera).
    """

    __tablename__ = "clave_idempotencia"
    __table_args__ = (
        UniqueConstraint("clave", name="uq_clave_idempotencia_clave"),
    )

    clave: Mapped[str] = mapped_column(SaString(128), nullable=False)
    turno_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("turno.id", ondelete="SET NULL"),
        nullable=True,
    )
    respuesta_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    expira_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class VerificacionPublica(BaseModel):
    """Verificación anti-spam del par DNI + teléfono (solo hashes, R6).

    `intentos` cuenta códigos errados; `bloqueada_hasta` marca el bloqueo
    temporal tras superar `VERIF_MAX_INTENTOS`; `verificada_en` no NULL =
    par ya verificado (reservas posteriores sin código nuevo).
    """

    __tablename__ = "verificacion_publica"
    __table_args__ = (
        UniqueConstraint(
            "dni_hash", "telefono_hash", name="uq_verificacion_par"
        ),
    )

    dni_hash: Mapped[str] = mapped_column(SaString(HASH_HEX_LEN), nullable=False)
    telefono_hash: Mapped[str] = mapped_column(
        SaString(HASH_HEX_LEN), nullable=False
    )
    codigo_hash: Mapped[str] = mapped_column(SaString(HASH_HEX_LEN), nullable=False)
    intentos: Mapped[int] = mapped_column(SaInteger, nullable=False, default=0)
    expira_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    verificada_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bloqueada_hasta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
