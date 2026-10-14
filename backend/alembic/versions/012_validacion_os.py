"""012 validación OS preventiva C-13 (parte 1 RED: solo esquema, R2).

Tablas (3, sin tocar agenda/clínica/caja — C-05/C-07/C-11 solo lectura):

- `obra_social`: nomenclador LOCAL versionado (`nomenclador jsonb` como
  mapa código→{cubre, copago, frecuencia} + `topes jsonb` + 
  `nomenclador_version >= 1`). `codigo` estable ficticio (UNIQUE) y
  `activa` (la OS inactiva → `422` en servicio). Índice GIN sobre
  `nomenclador` para el lookup por prestación (design decisión 2).
- `afiliacion_os`: vínculo paciente ↔ OS con `nro_afiliado` TEXT
  (ficticio; la API lo enmascara — R6), `vigencia_desde/hasta` DATE y
  `vigente` (baja lógica: `DELETE` pone `vigente=false`). CHECK
  `vigencia_hasta IS NULL OR >= vigencia_desde` + UNIQUE parcial
  `uq_afiliacion_vigente (paciente_id, obra_social_id) WHERE vigente`
  (la DB manda ante duplicada vigente → `409`, design decisión 6).
- `validacion_cobertura`: una fila por validación (turno + afiliación
  opcional NULL para `sin_afiliacion_vigente` + OS + `nomenclador_version`
  CONGELADA + `resultado cubre|parcial|no_cubre` + `detalle jsonb`
  con fuente `historial_local`, motivo y versión). FKs CASCADE salvo
  `afiliacion_id SET NULL` (la historia sobrevive a la purga física
  de tests; en prod la baja es lógica). La versión congelada preserva
  historia ante nomenclador v2 (design decisión 2 + RN-OS-02).

Todo dato de prueba sintético (R0); type hints siempre (R1).
Rollback: `downgrade -1` elimina las 3 tablas (orden inverso).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "012_validacion_os"
down_revision = "011_caja_cierre_diario"
branch_labels = None
depends_on = None

RESULTADOS_VALIDACION: tuple[str, ...] = ("cubre", "parcial", "no_cubre")


def _lista(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


def upgrade() -> None:
    op.create_table(
        "obra_social",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column(
            "activa", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "nomenclador_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "nomenclador",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "topes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "nomenclador_version >= 1", name="ck_os_nomenclador_version"
        ),
        sa.UniqueConstraint("codigo", name="uq_os_codigo"),
    )
    op.create_index(
        "ix_os_nomenclador_gin", "obra_social", ["nomenclador"], postgresql_using="gin"
    )

    op.create_table(
        "afiliacion_os",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paciente_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("paciente.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "obra_social_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("obra_social.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nro_afiliado", sa.Text(), nullable=False),
        sa.Column("vigencia_desde", sa.Date(), nullable=False),
        sa.Column("vigencia_hasta", sa.Date(), nullable=True),
        sa.Column(
            "vigente", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "vigencia_hasta IS NULL OR vigencia_hasta >= vigencia_desde",
            name="ck_afiliacion_vigencia",
        ),
    )
    op.create_index(
        "ix_afiliacion_paciente", "afiliacion_os", ["paciente_id"]
    )
    op.create_index("ix_afiliacion_os", "afiliacion_os", ["obra_social_id"])
    # Una afiliación vigente por paciente+OS: la DB manda ante alta
    # duplicada concurrente (el servicio traduce a `409`).
    op.create_index(
        "uq_afiliacion_vigente",
        "afiliacion_os",
        ["paciente_id", "obra_social_id"],
        unique=True,
        postgresql_where=sa.text("vigente IS TRUE"),
    )

    op.create_table(
        "validacion_cobertura",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "turno_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("turno.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "afiliacion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("afiliacion_os.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "obra_social_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("obra_social.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nomenclador_version", sa.Integer(), nullable=False),
        sa.Column("resultado", sa.String(20), nullable=False),
        sa.Column(
            "detalle",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            f"resultado IN ({_lista(RESULTADOS_VALIDACION)})",
            name="ck_validacion_resultado",
        ),
        sa.CheckConstraint(
            "nomenclador_version >= 1", name="ck_validacion_version"
        ),
    )
    op.create_index("ix_validacion_turno", "validacion_cobertura", ["turno_id"])
    op.create_index(
        "ix_validacion_afiliacion", "validacion_cobertura", ["afiliacion_id"]
    )
    op.create_index("ix_validacion_os", "validacion_cobertura", ["obra_social_id"])


def downgrade() -> None:
    op.drop_index("ix_validacion_os", table_name="validacion_cobertura")
    op.drop_index("ix_validacion_afiliacion", table_name="validacion_cobertura")
    op.drop_index("ix_validacion_turno", table_name="validacion_cobertura")
    op.drop_table("validacion_cobertura")
    op.drop_index("uq_afiliacion_vigente", table_name="afiliacion_os")
    op.drop_index("ix_afiliacion_os", table_name="afiliacion_os")
    op.drop_index("ix_afiliacion_paciente", table_name="afiliacion_os")
    op.drop_table("afiliacion_os")
    op.drop_index("ix_os_nomenclador_gin", table_name="obra_social")
    op.drop_table("obra_social")
