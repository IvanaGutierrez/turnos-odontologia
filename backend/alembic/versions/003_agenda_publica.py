"""003 agenda pública C-03: horarios + bloqueos + idempotencia + verificación.

Solo vía Alembic (R2). Tablas nuevas vacías, sin backfill (no hay agenda
pública previa). Checks `desde < hasta` / `hora_fin > hora_inicio` /
`dia_semana 0–6`. Índices btree de rango/fecha para la query de slots
(ventana día/semana); sin gist adicional: la exclusión de C-01 sigue
siendo la última línea de defensa (R3, no se toca). Rollback:
`downgrade -1` elimina las 4 tablas + índices (no toca turnos).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "003_agenda_publica"
down_revision = "002_sesiones_auditoria"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "horario_profesional",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "profesional_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("profesional.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dia_semana", sa.Integer, nullable=False),
        sa.Column("hora_inicio", sa.Time, nullable=False),
        sa.Column("hora_fin", sa.Time, nullable=False),
        sa.Column("vigente_desde", sa.Date, nullable=True),
        sa.Column("vigente_hasta", sa.Date, nullable=True),
        sa.Column("activo", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.CheckConstraint("dia_semana BETWEEN 0 AND 6", name="ck_horario_dia_semana"),
        sa.CheckConstraint("hora_fin > hora_inicio", name="ck_horario_horas"),
    )
    op.create_index(
        "ix_horario_profesional_dia",
        "horario_profesional",
        ["profesional_id", "dia_semana"],
    )

    op.create_table(
        "bloqueo",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "profesional_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("profesional.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "sillon_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sillon.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("desde", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hasta", sa.DateTime(timezone=True), nullable=False),
        sa.Column("motivo", sa.String(200), nullable=True),
        sa.Column(
            "creado_por",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuario.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.CheckConstraint("hasta > desde", name="ck_bloqueo_rango"),
    )
    op.create_index("ix_bloqueo_rango", "bloqueo", ["desde", "hasta"])
    op.create_index(
        "ix_bloqueo_profesional_desde", "bloqueo", ["profesional_id", "desde"]
    )

    op.create_table(
        "clave_idempotencia",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("clave", sa.String(128), nullable=False),
        sa.Column(
            "turno_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("turno.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("respuesta_json", postgresql.JSONB, nullable=True),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("clave", name="uq_clave_idempotencia_clave"),
    )
    op.create_index(
        "ix_clave_idempotencia_expira", "clave_idempotencia", ["expira_en"]
    )

    op.create_table(
        "verificacion_publica",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("dni_hash", sa.String(64), nullable=False),
        sa.Column("telefono_hash", sa.String(64), nullable=False),
        sa.Column("codigo_hash", sa.String(64), nullable=False),
        sa.Column("intentos", sa.Integer, nullable=False, server_default="0"),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verificada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bloqueada_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("dni_hash", "telefono_hash", name="uq_verificacion_par"),
    )
    op.create_index(
        "ix_verificacion_expira", "verificacion_publica", ["expira_en"]
    )


def downgrade() -> None:
    op.drop_index("ix_verificacion_expira", table_name="verificacion_publica")
    op.drop_table("verificacion_publica")
    op.drop_index("ix_clave_idempotencia_expira", table_name="clave_idempotencia")
    op.drop_table("clave_idempotencia")
    op.drop_index("ix_bloqueo_profesional_desde", table_name="bloqueo")
    op.drop_index("ix_bloqueo_rango", table_name="bloqueo")
    op.drop_table("bloqueo")
    op.drop_index("ix_horario_profesional_dia", table_name="horario_profesional")
    op.drop_table("horario_profesional")
