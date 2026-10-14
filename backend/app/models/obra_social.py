"""Modelos de validación OS preventiva C-13 (solo ORM aquí — R2).

Espejo de la migración 012 (`012_validacion_os`):

- `ObraSocial`: nomenclador LOCAL versionado (`nomenclador jsonb` como
  mapa código→{cubre, copago, frecuencia} + `topes jsonb` +
  `nomenclador_version >= 1`). `codigo` estable ficticio (UNIQUE) y
  `activa` (la OS inactiva → `422` en servicio). Índice GIN sobre
  `nomenclador` para el lookup por prestación.
- `AfiliacionOS`: vínculo paciente ↔ OS con `nro_afiliado` TEXT
  (ficticio; la API lo enmascara — R6), `vigencia_desde/hasta` DATE y
  `vigente` (baja lógica). UNIQUE parcial
  `uq_afiliacion_vigente (paciente_id, obra_social_id) WHERE vigente`.
- `ValidacionCobertura`: una fila por validación (turno + afiliación +
  OS + `nomenclador_version` CONGELADA + `resultado
  cubre|parcial|no_cubre` + `detalle jsonb` con fuente
  `historial_local`). La versión congelada preserva historia ante
  nomenclador v2 (RN-OS-02).

Todo dato de prueba sintético (R0); type hints siempre (R1).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy import String as SaString
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel

RESULTADOS_VALIDACION: tuple[str, ...] = ("cubre", "parcial", "no_cubre")


def _lista(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


class ObraSocial(BaseModel):
    """Obra social / prepaga con nomenclador local versionado (v1: carga manual)."""

    __tablename__ = "obra_social"
    __table_args__ = (
        CheckConstraint("nomenclador_version >= 1", name="ck_os_nomenclador_version"),
        Index("ix_os_nomenclador_gin", "nomenclador", postgresql_using="gin"),
    )

    nombre: Mapped[str] = mapped_column(Text, nullable=False)
    codigo: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    nomenclador_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    nomenclador: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    topes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class AfiliacionOS(BaseModel):
    """Vínculo paciente ↔ OS con vigencia (`nro_afiliado` jamás sale en claro)."""

    __tablename__ = "afiliacion_os"
    __table_args__ = (
        CheckConstraint(
            "vigencia_hasta IS NULL OR vigencia_hasta >= vigencia_desde",
            name="ck_afiliacion_vigencia",
        ),
        Index("ix_afiliacion_paciente", "paciente_id"),
        Index("ix_afiliacion_os", "obra_social_id"),
        Index(
            "uq_afiliacion_vigente",
            "paciente_id",
            "obra_social_id",
            unique=True,
            postgresql_where=text("vigente IS TRUE"),
        ),
    )

    paciente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("paciente.id", ondelete="CASCADE"),
        nullable=False,
    )
    obra_social_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("obra_social.id", ondelete="CASCADE"),
        nullable=False,
    )
    nro_afiliado: Mapped[str] = mapped_column(Text, nullable=False)
    vigencia_desde: Mapped[date] = mapped_column(Date, nullable=False)
    vigencia_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    vigente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ValidacionCobertura(BaseModel):
    """Resultado congelado de una validación preventiva (nunca muta el turno)."""

    __tablename__ = "validacion_cobertura"
    __table_args__ = (
        CheckConstraint(
            f"resultado IN ({_lista(RESULTADOS_VALIDACION)})",
            name="ck_validacion_resultado",
        ),
        CheckConstraint("nomenclador_version >= 1", name="ck_validacion_version"),
        Index("ix_validacion_turno", "turno_id"),
        Index("ix_validacion_afiliacion", "afiliacion_id"),
        Index("ix_validacion_os", "obra_social_id"),
    )

    turno_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("turno.id", ondelete="CASCADE"),
        nullable=False,
    )
    afiliacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("afiliacion_os.id", ondelete="SET NULL"),
        nullable=True,
    )
    obra_social_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("obra_social.id", ondelete="CASCADE"),
        nullable=False,
    )
    nomenclador_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resultado: Mapped[str] = mapped_column(SaString(20), nullable=False)
    detalle: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
