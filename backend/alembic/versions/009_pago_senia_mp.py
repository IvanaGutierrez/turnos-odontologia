"""009 seña Mercado Pago C-08 (parte 1 RED: solo esquema, R2).

Tabla `pago` (cobro de seña por Mercado Pago en ARS) + columnas de seña
en `prestacion`. Sin tocar GiST ni tablas de agenda/C-06/C-07 (R3 intacta):

- `pago`: `paciente_id`/`turno_id`/`presupuesto_id` FK NULL (el handler del
  webhook puede crear el `Pago` desde `metadata` antes de resolver todo —
  design decisión 5, riesgo `origen=webhook`; `SET NULL` preserva el
  rastro del dinero si el turno se borra), `monto NUMERIC(12,2) >= 0`,
  `moneda` CHECK `='ARS'`, `metodo` CHECK `='mercadopago'`, `estado` CHECK
  `pendiente|acreditado|rechazado|reembolsado` (el flujo de `reembolsado`
  es manual, fuera de scope; el estado se modela para C-09), `UNIQUE`s
  `mp_payment_id`/`mp_preference_id` (idempotencia RN-PA-03: la DB manda
  ante duplicados concurrentes) + UNIQUE parcial
  `uq_pago_turno_pendiente` (UN pendiente por turno, design decisión 3) +
  índices `(turno_id)`, `(estado)`, `webhook_recibido_at` NULL.
- `prestacion`: `precio_base` (base del `%`; el spec exige
  `precio_base * sena_porcentaje/100` pero ningún change anterior la
  creó — se agrega aquí como parte del config de seña), `sena_monto_fijo`
  (gana al porcentaje, design decisión 4), `sena_porcentaje` CHECK 0–100.
  Todo NULL (catálogo existente sin seña sigue válido; `requiere_sena`
  sin monto ni % → `422` de configuración en servicio, nunca cero
  silencioso).

Rollback: `downgrade -1` elimina la tabla `pago` y las 3 columnas.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "009_pago_senia_mp"
down_revision = "008_ficha_clinica"
branch_labels = None
depends_on = None

ESTADOS_PAGO: tuple[str, ...] = (
    "pendiente",
    "acreditado",
    "rechazado",
    "reembolsado",
)


def _lista(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


def upgrade() -> None:
    op.add_column(
        "prestacion",
        sa.Column("precio_base", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "prestacion",
        sa.Column("sena_monto_fijo", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "prestacion",
        sa.Column("sena_porcentaje", sa.Numeric(5, 2), nullable=True),
    )
    op.create_check_constraint(
        "ck_prestacion_precio_base",
        "prestacion",
        "precio_base IS NULL OR precio_base >= 0",
    )
    op.create_check_constraint(
        "ck_prestacion_sena_fijo",
        "prestacion",
        "sena_monto_fijo IS NULL OR sena_monto_fijo >= 0",
    )
    op.create_check_constraint(
        "ck_prestacion_sena_pct",
        "prestacion",
        "sena_porcentaje IS NULL OR (sena_porcentaje >= 0 AND sena_porcentaje <= 100)",
    )

    op.create_table(
        "pago",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paciente_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("paciente.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "turno_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("turno.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "presupuesto_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("presupuesto.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("monto", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "moneda", sa.String(3), nullable=False, server_default=sa.text("'ARS'")
        ),
        sa.Column(
            "metodo",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'mercadopago'"),
        ),
        sa.Column(
            "estado",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pendiente'"),
        ),
        sa.Column("mp_payment_id", sa.Text(), nullable=True),
        sa.Column("mp_preference_id", sa.Text(), nullable=True),
        sa.Column("webhook_recibido_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("monto >= 0", name="ck_pago_monto"),
        sa.CheckConstraint("moneda = 'ARS'", name="ck_pago_moneda_ars"),
        sa.CheckConstraint(
            "metodo = 'mercadopago'", name="ck_pago_metodo_mp"
        ),
        sa.CheckConstraint(
            f"estado IN ({_lista(ESTADOS_PAGO)})",
            name="ck_pago_estado",
        ),
        sa.UniqueConstraint("mp_payment_id", name="uq_pago_mp_payment"),
        sa.UniqueConstraint("mp_preference_id", name="uq_pago_mp_preference"),
    )
    op.create_index("ix_pago_turno", "pago", ["turno_id"])
    op.create_index("ix_pago_estado", "pago", ["estado"])
    # UN solo pendiente por turno (el reintento tras rechazo crea uno nuevo
    # solo cuando el anterior ya no está pendiente — design decisión 6).
    op.create_index(
        "uq_pago_turno_pendiente",
        "pago",
        ["turno_id"],
        unique=True,
        postgresql_where=sa.text("estado = 'pendiente'"),
    )


def downgrade() -> None:
    op.drop_index("uq_pago_turno_pendiente", table_name="pago")
    op.drop_index("ix_pago_estado", table_name="pago")
    op.drop_index("ix_pago_turno", table_name="pago")
    op.drop_table("pago")
    op.drop_constraint("ck_prestacion_sena_pct", "prestacion", type_="check")
    op.drop_constraint("ck_prestacion_sena_fijo", "prestacion", type_="check")
    op.drop_constraint("ck_prestacion_precio_base", "prestacion", type_="check")
    op.drop_column("prestacion", "sena_porcentaje")
    op.drop_column("prestacion", "sena_monto_fijo")
    op.drop_column("prestacion", "precio_base")
