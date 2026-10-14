"""001 agenda fundacional + EXCLUDE anti-doble-reserva (R3).

Dos constraints (cota superior exclusiva '[)' → adyacentes permitidos):
- ex_turno_profesional_sin_solape: (profesional_id, rango) en turnos activos.
- ex_turno_sillon_sin_solape: (sillon_id, rango) solo si requiere sillón
  (sillon_id NOT NULL; los NULL nunca colisionan en gist — comportamiento
  deseado según RN-AG-02).
Requiere btree_gist (igualdad sobre UUID dentro del gist).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "001_agenda_exclusion"
down_revision = None
branch_labels = None
depends_on = None

ESTADOS_INACTIVOS = ("cancelado", "ausente", "reprogramado")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "usuario",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("rol", sa.String(30), nullable=False, server_default="admin"),
        sa.Column("activo", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_table(
        "paciente",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("dni", sa.String(8), unique=True, nullable=False),
        sa.Column("telefono", sa.String(25), nullable=False),
        sa.Column(
            "consentimiento_hc", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_table(
        "profesional",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("matricula", sa.String(50), unique=True, nullable=False),
        sa.Column("activo", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_table(
        "sillon",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("sede", sa.String(100), nullable=False, server_default="Consultorio"),
        sa.Column("activo", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_table(
        "prestacion",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nombre", sa.String(150), unique=True, nullable=False),
        sa.Column("duracion_min", sa.Integer, nullable=False),
        sa.Column(
            "requiere_sena", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "requiere_sillon", sa.Boolean, nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_table(
        "turno",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paciente_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("paciente.id"),
            nullable=False,
        ),
        sa.Column(
            "profesional_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("profesional.id"),
            nullable=False,
        ),
        sa.Column(
            "sillon_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sillon.id"),
            nullable=True,
        ),
        sa.Column(
            "prestacion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prestacion.id"),
            nullable=False,
        ),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fin", sa.DateTime(timezone=True), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False, server_default="reservado"),
        sa.Column("canal", sa.String(20), nullable=False, server_default="mostrador"),
        sa.Column("token_publico", sa.String(64), unique=True, nullable=False),
        sa.Column("motivo_override", sa.Text, nullable=True),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.CheckConstraint("fin > inicio", name="ck_turno_fin_mayor_inicio"),
        sa.CheckConstraint(
            "estado IN ('reservado','confirmado','en_sala','atendido','cancelado','ausente','reprogramado')",
            name="ck_turno_estado",
        ),
    )
    op.create_index(
        "ix_turno_profesional_inicio", "turno", ["profesional_id", "inicio"]
    )
    op.create_index("ix_turno_sillon_inicio", "turno", ["sillon_id", "inicio"])

    inactivos = ", ".join(f"'{e}'" for e in ESTADOS_INACTIVOS)
    op.execute(f"""ALTER TABLE turno ADD CONSTRAINT ex_turno_profesional_sin_solape
        EXCLUDE USING gist (
            profesional_id WITH =,
            tstzrange(inicio, fin, '[)') WITH &&
        ) WHERE (estado NOT IN ({inactivos}))""")
    op.execute(f"""ALTER TABLE turno ADD CONSTRAINT ex_turno_sillon_sin_solape
        EXCLUDE USING gist (
            sillon_id WITH =,
            tstzrange(inicio, fin, '[)') WITH &&
        ) WHERE (sillon_id IS NOT NULL AND estado NOT IN ({inactivos}))""")


def downgrade() -> None:
    op.execute("ALTER TABLE turno DROP CONSTRAINT IF EXISTS ex_turno_sillon_sin_solape")
    op.execute(
        "ALTER TABLE turno DROP CONSTRAINT IF EXISTS ex_turno_profesional_sin_solape"
    )
    op.drop_index("ix_turno_sillon_inicio", table_name="turno")
    op.drop_index("ix_turno_profesional_inicio", table_name="turno")
    op.drop_table("turno")
    op.drop_table("prestacion")
    op.drop_table("sillon")
    op.drop_table("profesional")
    op.drop_table("paciente")
    op.drop_table("usuario")
