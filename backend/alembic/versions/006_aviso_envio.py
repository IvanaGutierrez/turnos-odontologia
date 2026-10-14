"""006 avisos de WhatsApp C-06 (tabla `aviso_envio`, design decisión 3).

Solo vía Alembic (R2). Sobre DB con datos C-01…C-05:
- Tabla `aviso_envio` (idempotencia durable + auditoría de los 3 envíos
  utility): `turno_id UUID NOT NULL → turno.id ON DELETE CASCADE`
  (al purgarse el turno se purgan sus avisos; la auditoría de dominio
  sigue en `auditoria_log`), `tipo_aviso` + `estado` con checks,
  `intentos INT NOT NULL DEFAULT 0`, `proveedor_msg_id VARCHAR(100)
  NULL UNIQUE` (NULL múltiple permitido: solo el worker lo setea al
  enviar; el UNIQUE frena duplicados del proveedor), `payload_hash`
  (sha256 hex, sin PII — R6), `creado_en`/`actualizado_en` (equivalen a
  `created_at`) + `enviado_en NULL` (equivale a `sent_at`).
- `UNIQUE (turno_id, tipo_aviso)` (`uq_aviso_turno_tipo`): segunda
  barrera anti-doble-envío junto al `SET NX` de Redis (parte 2).
- Índices btree `ix_aviso_turno` (consulta por `turno_id` para
  recepción) + `ix_aviso_estado` (reclamo del worker por estado).
- Sin tocar GiST ni tablas de agenda (R3 intacta); sin backfill
  (cero avisos históricos).
Rollback: `downgrade -1` elimina índices + tabla (solo si no hay filas
con avisos pendientes de procesar; en ese caso el re-encolado de la
parte 2 los regenera desde los turnos — documentado).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "006_aviso_envio"
down_revision = "005_autogestion_cancelacion"
branch_labels = None
depends_on = None

TIPOS_AVISO: tuple[str, ...] = (
    "confirmacion",
    "recordatorio_24h",
    "aviso_3h",
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


def upgrade() -> None:
    op.create_table(
        "aviso_envio",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "turno_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("turno.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tipo_aviso", sa.String(20), nullable=False),
        sa.Column(
            "estado",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pendiente'"),
        ),
        sa.Column(
            "intentos", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("proveedor_msg_id", sa.String(100), nullable=True),
        sa.Column("payload_hash", sa.String(64), nullable=True),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("enviado_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"tipo_aviso IN ({_lista(TIPOS_AVISO)})",
            name="ck_aviso_tipo",
        ),
        sa.CheckConstraint(
            f"estado IN ({_lista(ESTADOS_AVISO)})",
            name="ck_aviso_estado",
        ),
        sa.UniqueConstraint("turno_id", "tipo_aviso", name="uq_aviso_turno_tipo"),
        sa.UniqueConstraint("proveedor_msg_id", name="uq_aviso_proveedor_msg"),
    )
    op.create_index("ix_aviso_turno", "aviso_envio", ["turno_id"])
    op.create_index("ix_aviso_estado", "aviso_envio", ["estado"])


def downgrade() -> None:
    op.drop_index("ix_aviso_estado", table_name="aviso_envio")
    op.drop_index("ix_aviso_turno", table_name="aviso_envio")
    op.drop_table("aviso_envio")
