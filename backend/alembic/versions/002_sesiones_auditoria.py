"""002 sesiones de refresh + auditoría (C-02, RN-AU-03).

Solo vía Alembic (R2): crea `sesion_refresh` (jti PK, FK a usuario,
índice (usuario_id, expira_at) para revocación de cadena) y
`auditoria_log` (accion/entidad/entidad_id/diff jsonb, índice
(entidad, entidad_id) para la bitácora de C-11). Sin backfill: no hay
sesiones ni eventos previos. Rollback: `downgrade -1` revierte ambas
tablas (los JWT emitidos quedan inválidos → fail-closed, correcto).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "002_sesiones_auditoria"
down_revision = "001_agenda_exclusion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sesion_refresh",
        sa.Column("jti", sa.String(36), primary_key=True),
        sa.Column(
            "usuario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuario.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expira_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revocado", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_sesion_refresh_usuario_expira",
        "sesion_refresh",
        ["usuario_id", "expira_at"],
    )

    op.create_table(
        "auditoria_log",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column("accion", sa.String(60), nullable=False),
        sa.Column("entidad", sa.String(60), nullable=False),
        sa.Column("entidad_id", sa.String(64), nullable=True),
        sa.Column(
            "diff",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "usuario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuario.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_auditoria_entidad",
        "auditoria_log",
        ["entidad", "entidad_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_auditoria_entidad", table_name="auditoria_log")
    op.drop_table("auditoria_log")
    op.drop_index("ix_sesion_refresh_usuario_expira", table_name="sesion_refresh")
    op.drop_table("sesion_refresh")
