"""011 caja y cierre diario C-09 (parte 1 RED: solo esquema, R2).

Tablas (2, sin tocar agenda/`pago`/avisos — C-08 solo lectura):

- `movimiento_caja`: ingreso/egreso manual por metodo
  (`efectivo|transferencia|tarjeta|mercadopago`, RN-PA-05) con
  `usuario_id` del operador (FK `SET NULL`: el rastro del dinero
  sobrevive a la baja del usuario) y `pago_id` FK NULL opcional (ata
  un ingreso MP a su pago C-08). `monto > 0`, `concepto` 1-280
  caracteres (el servicio lo sanitiza antes de loguear — R6),
  `origen manual|mercadopago` (default `manual`). Indice
  `(fecha, sede)` para el arqueo + UNIQUE parcial
  `uq_movcaja_pago_unico` (un `pago_id` en un solo movimiento de
  ingreso; los NULL multiples estan permitidos — design riesgo).
- `cierre_diario`: snapshot por dia/sede (sede texto default
  `"Consultorio"`, patron `Sillon.sede`) con totales por metodo,
  `acreditado_mp` (leido de `pago`, solo lectura) y `diferencia`
  (`total_mp_movimientos - acreditado_mp`; `estado_conciliacion` se
  deriva en servicio: `diferencia == 0` → `cuadrado`). Maquina
  `abierto→cerrado` (cierre) / `cerrado→abierto` (reapertura admin,
  con `reaperturas+1`). `UNIQUE(fecha, sede)`: la DB manda ante
  doble cierre concurrente → `409` (RN-PA-04, design decision 3).

Todo dato de prueba sintetico (R0); type hints siempre (R1).
Rollback: `downgrade -1` elimina ambas tablas (orden inverso).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "011_caja_cierre_diario"
down_revision = "010_pago_comprobante"
branch_labels = None
depends_on = None

TIPOS_MOVIMIENTO: tuple[str, ...] = ("ingreso", "egreso")

METODOS_CAJA: tuple[str, ...] = (
    "efectivo",
    "transferencia",
    "tarjeta",
    "mercadopago",
)

ORIGENES_MOVIMIENTO: tuple[str, ...] = ("manual", "mercadopago")

ESTADOS_CIERRE: tuple[str, ...] = ("abierto", "cerrado")

SEDE_DEFAULT = "Consultorio"


def _lista(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


def upgrade() -> None:
    op.create_table(
        "movimiento_caja",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column(
            "sede",
            sa.Text(),
            nullable=False,
            server_default=sa.text(f"'{SEDE_DEFAULT}'"),
        ),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("concepto", sa.Text(), nullable=False),
        sa.Column("monto", sa.Numeric(12, 2), nullable=False),
        sa.Column("metodo", sa.String(20), nullable=False),
        sa.Column(
            "usuario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuario.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "pago_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pago.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "origen",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'manual'"),
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
            f"tipo IN ({_lista(TIPOS_MOVIMIENTO)})",
            name="ck_movcaja_tipo",
        ),
        sa.CheckConstraint(
            f"metodo IN ({_lista(METODOS_CAJA)})",
            name="ck_movcaja_metodo",
        ),
        sa.CheckConstraint("monto > 0", name="ck_movcaja_monto"),
        sa.CheckConstraint(
            "char_length(concepto) BETWEEN 1 AND 280",
            name="ck_movcaja_concepto",
        ),
        sa.CheckConstraint(
            f"origen IN ({_lista(ORIGENES_MOVIMIENTO)})",
            name="ck_movcaja_origen",
        ),
    )
    op.create_index(
        "ix_movcaja_fecha_sede", "movimiento_caja", ["fecha", "sede"]
    )
    # Un `pago_id` en un solo movimiento de ingreso (los NULL no
    # colisionan en PG: los movimientos sin pago atado pasan siempre).
    op.create_index(
        "uq_movcaja_pago_unico",
        "movimiento_caja",
        ["pago_id"],
        unique=True,
        postgresql_where=sa.text("pago_id IS NOT NULL"),
    )

    op.create_table(
        "cierre_diario",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column(
            "sede",
            sa.Text(),
            nullable=False,
            server_default=sa.text(f"'{SEDE_DEFAULT}'"),
        ),
        sa.Column(
            "total_efectivo",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("'0'"),
        ),
        sa.Column(
            "total_transferencia",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("'0'"),
        ),
        sa.Column(
            "total_tarjeta",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("'0'"),
        ),
        sa.Column(
            "total_mp",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("'0'"),
        ),
        sa.Column(
            "total_egresos",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("'0'"),
        ),
        sa.Column(
            "acreditado_mp",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("'0'"),
        ),
        sa.Column(
            "diferencia",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("'0'"),
        ),
        sa.Column(
            "estado",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'cerrado'"),
        ),
        sa.Column(
            "cerrado_por",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuario.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cerrado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reaperturas",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
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
            f"estado IN ({_lista(ESTADOS_CIERRE)})",
            name="ck_cierre_estado",
        ),
        sa.CheckConstraint("reaperturas >= 0", name="ck_cierre_reaperturas"),
        # UN solo cierre por dia/sede: la DB manda ante doble cierre
        # concurrente (el servicio traduce a `409` — RN-PA-04).
        sa.UniqueConstraint("fecha", "sede", name="uq_cierre_fecha_sede"),
    )


def downgrade() -> None:
    op.drop_table("cierre_diario")
    op.drop_index("uq_movcaja_pago_unico", table_name="movimiento_caja")
    op.drop_index("ix_movcaja_fecha_sede", table_name="movimiento_caja")
    op.drop_table("movimiento_caja")
