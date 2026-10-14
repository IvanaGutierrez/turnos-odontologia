"""005 autogestión del paciente C-05 (design decisión 2).

Solo vía Alembic (R2). Sobre DB con datos C-01…C-04:
- Columnas `motivo_cancelacion TEXT NULL` + `cancelado_at TIMESTAMPTZ NULL`
  (trazabilidad de la cancelación del paciente; NULL salvo `cancelado`).
- Consolidación `en_sala→presente`: backfill `UPDATE turno SET
  estado='presente' WHERE estado='en_sala'` + reescritura de
  `ck_turno_estado` sin `'en_sala'` (`presente` canónico de check-in C-04).
- Sin cambios en las exclusiones GiST ni en el índice parcial de token
  (ya sirven a reprogramación y rotación; R3 intacta).
Rollback: `downgrade -1` revierte columnas y check (el backfill
`en_sala→presente` no se deshace — documentado, sin pérdida semántica
porque el servicio ya escribe `presente`).
"""

import sqlalchemy as sa

from alembic import op

revision = "005_autogestion_cancelacion"
down_revision = "004_sobreturno_reprogramacion"
branch_labels = None
depends_on = None

ESTADOS_C05: tuple[str, ...] = (
    "reservado",
    "confirmado",
    "presente",
    "atendido",
    "cancelado",
    "ausente",
    "reprogramado",
)

ESTADOS_PREVIOS: tuple[str, ...] = (
    "reservado",
    "confirmado",
    "en_sala",
    "presente",
    "atendido",
    "cancelado",
    "ausente",
    "reprogramado",
)


def _lista(estados: tuple[str, ...]) -> str:
    return ", ".join(f"'{e}'" for e in estados)


def upgrade() -> None:
    op.add_column("turno", sa.Column("motivo_cancelacion", sa.Text(), nullable=True))
    op.add_column(
        "turno",
        sa.Column("cancelado_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Consolidación del alias transitorio (C-04 → C-05): sin backfill de
    # columnas nuevas (NULL salvo `cancelado`, que escribe el servicio).
    op.execute("UPDATE turno SET estado = 'presente' WHERE estado = 'en_sala'")

    op.drop_constraint("ck_turno_estado", "turno", type_="check")
    op.create_check_constraint(
        "ck_turno_estado",
        "turno",
        f"estado IN ({_lista(ESTADOS_C05)})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_turno_estado", "turno", type_="check")
    op.create_check_constraint(
        "ck_turno_estado",
        "turno",
        f"estado IN ({_lista(ESTADOS_PREVIOS)})",
    )

    op.drop_column("turno", "cancelado_at")
    op.drop_column("turno", "motivo_cancelacion")
