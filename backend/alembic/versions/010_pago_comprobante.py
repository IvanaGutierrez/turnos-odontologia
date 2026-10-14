"""010 comprobante de pago + init_point C-08 (parte 2 GREEN, R2).

Dos necesidades C-08 sobre el esquema 009 (sin tocar GiST ni agenda):

- `pago.init_point TEXT NULL`: persiste el link vigente de la
  preferencia para reutilizarlo en reintentos sin crear preferencias de
  más (el reintento tras rechazo devuelve el MISMO link con UN solo
  pendiente por turno).
- `ck_aviso_tipo` extendido con `comprobante_pago`: el comprobante de
  pago acreditado se encola como `aviso_envio` (reusa la infraestructura
  C-06 sin modificar sus specs; el tipo nuevo solo lo inserta el
  servicio de pagos, el veto marketing de C-06 sigue intacto).

Rollback: `downgrade -1` quita la columna y restaura el check de 3 tipos.
"""

import sqlalchemy as sa

from alembic import op

revision = "010_pago_comprobante"
down_revision = "009_pago_senia_mp"
branch_labels = None
depends_on = None

TIPOS_AVISO_010 = (
    "confirmacion",
    "recordatorio_24h",
    "aviso_3h",
    "comprobante_pago",
)

TIPOS_AVISO_009 = (
    "confirmacion",
    "recordatorio_24h",
    "aviso_3h",
)


def _lista(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


def upgrade() -> None:
    op.add_column("pago", sa.Column("init_point", sa.Text(), nullable=True))
    op.drop_constraint("ck_aviso_tipo", "aviso_envio", type_="check")
    op.create_check_constraint(
        "ck_aviso_tipo",
        "aviso_envio",
        f"tipo_aviso IN ({_lista(TIPOS_AVISO_010)})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_aviso_tipo", "aviso_envio", type_="check")
    op.create_check_constraint(
        "ck_aviso_tipo",
        "aviso_envio",
        f"tipo_aviso IN ({_lista(TIPOS_AVISO_009)})",
    )
    op.drop_column("pago", "init_point")
