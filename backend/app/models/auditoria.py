"""Bitácora de auditoría (C-02, RN-AU-03): append-only, solo escritura.

En este change la tabla solo se escribe desde servicios vía
`registrar_auditoria()` (GREEN, parte 2); la lectura (`GET /auditoria`)
llega en C-11. El `diff` pasa por `sanitizar_diff()` (denylist R6):
jamás DNI, teléfonos, historia clínica, hashes ni tokens.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy import String as SaString
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditoriaLog(Base):
    """Evento auditable (capas separadas: solo ORM aquí — R2)."""

    __tablename__ = "auditoria_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    accion: Mapped[str] = mapped_column(SaString(60), nullable=False)
    entidad: Mapped[str] = mapped_column(SaString(60), nullable=False)
    entidad_id: Mapped[str | None] = mapped_column(SaString(64), nullable=True)
    diff: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("usuario.id", ondelete="SET NULL"),
        nullable=True,
    )
    ip: Mapped[str | None] = mapped_column(SaString(45), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
