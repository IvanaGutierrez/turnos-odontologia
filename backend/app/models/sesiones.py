"""Sesiones de refresh JWT (C-02): fuente de verdad en Postgres (R2).

Cada fila representa un refresh emitido (`jti` como PK). La rotación
revoca la fila anterior e inserta la nueva; el reuso de una fila
revocada es señal de robo (revocación de cadena en GREEN). Redis solo
es fast-path de blacklist; ante su caída la DB manda (design §3).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, func
from sqlalchemy import String as SaString
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SesionRefresh(Base):
    """Refresh emitido a un usuario (capas separadas: solo ORM aquí — R2)."""

    __tablename__ = "sesion_refresh"

    jti: Mapped[str] = mapped_column(SaString(36), primary_key=True)
    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("usuario.id", ondelete="CASCADE"),
        nullable=False,
    )
    expira_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revocado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
