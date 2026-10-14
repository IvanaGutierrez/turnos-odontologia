"""Modelos de lista de espera inteligente (C-14)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class ListaEspera(BaseModel):
    __tablename__ = "lista_espera"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('activa', 'ofertada', 'asignada', 'expirada')",
            name="ck_lista_espera_estado",
        ),
        CheckConstraint(
            "ventana_hasta > ventana_desde",
            name="ck_lista_espera_ventana",
        ),
    )

    paciente_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paciente.id", ondelete="CASCADE"), nullable=False
    )
    prestacion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prestacion.id", ondelete="CASCADE"), nullable=False
    )
    profesional_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profesional.id", ondelete="SET NULL"), nullable=True
    )
    ventana_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ventana_hasta: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0.0)
    score_componentes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="activa")

    paciente: Mapped[Any] = relationship("Paciente")
    prestacion: Mapped[Any] = relationship("Prestacion")
    profesional: Mapped[Any | None] = relationship("Profesional")
    ofertas: Mapped[list["OfertaEspera"]] = relationship(
        back_populates="lista_espera", cascade="all, delete-orphan"
    )


class OfertaEspera(BaseModel):
    __tablename__ = "oferta_espera"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('pendiente', 'aceptada', 'expirada', 'desplazada')",
            name="ck_oferta_espera_estado",
        ),
    )

    lista_espera_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lista_espera.id", ondelete="CASCADE"), nullable=False
    )
    # Agrupador del hueco cancelado (snapshot, sin FK: el turno origen
    # puede purgarse y la oferta es historia — migración 013).
    hueco_origen_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    # Snapshot congelado del slot ofertado (copiado del turno cancelado).
    profesional_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    sillon_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fin: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expira_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    mp_preference_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    lista_espera: Mapped[ListaEspera] = relationship(back_populates="ofertas")
