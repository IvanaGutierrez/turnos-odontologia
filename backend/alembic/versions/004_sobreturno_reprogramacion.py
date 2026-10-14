"""004 sobreturno + reprogramación C-04 (decisiones design 1–3).

Solo vía Alembic (R2). Sobre DB con datos C-01…C-03:
- Columnas `sobreturno BOOL NOT NULL DEFAULT FALSE`,
  `motivo_sobreturno TEXT NULL`, `reprogramado_de_id UUID NULL → turno.id`
  (self-FK `ON DELETE SET NULL`; sin backfill: cero sobreturnos históricos).
- Exclusiones GiST C-01 amplían su predicado con
  `AND (sobreturno IS NOT TRUE)`: normal-vs-normal sigue vetado por la DB
  exactamente igual que antes (R3); el sobreturno entra solo por el
  endpoint dedicado auditado. Ventana de bloqueo breve (DROP/ADD
  CONSTRAINT en una transacción).
- Unicidad de `token_publico` relajada a parcial: el índice único total se
  reemplaza por `uq_turno_token_activo ... WHERE estado NOT IN (inactivos)`
  (original `reprogramado` + nuevo activo comparten token).
- `ck_turno_estado` ampliado con `'presente'` (canónico de check-in);
  `'en_sala'` se conserva como alias transitorio (C-05 consolida).
- Check `ck_turno_sobreturno_motivo`: si `sobreturno` entonces motivo no vacío.
- Índices btree `(inicio, fin)` para la grilla día/semana (una query por
  rango) + `reprogramado_de_id` para el enlace original→nuevo.
Rollback: `downgrade -1` revierte columnas, checks, GiST e índices
(solo si no hay filas C-04 con `sobreturno=true` o `estado='presente`;
en ese caso el downgrade falla en vez de corromper datos — correcto).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "004_sobreturno_reprogramacion"
down_revision = "003_agenda_publica"
branch_labels = None
depends_on = None

ESTADOS_INACTIVOS = ("cancelado", "ausente", "reprogramado")

ESTADOS_C04: tuple[str, ...] = (
    "reservado",
    "confirmado",
    "en_sala",
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
    "atendido",
    "cancelado",
    "ausente",
    "reprogramado",
)


def _lista(estados: tuple[str, ...]) -> str:
    return ", ".join(f"'{e}'" for e in estados)


def upgrade() -> None:
    op.add_column(
        "turno",
        sa.Column(
            "sobreturno",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("turno", sa.Column("motivo_sobreturno", sa.Text(), nullable=True))
    op.add_column(
        "turno",
        sa.Column(
            "reprogramado_de_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("turno.id", name="fk_turno_reprogramado_de", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_turno_reprogramado_de", "turno", ["reprogramado_de_id"]
    )

    op.create_check_constraint(
        "ck_turno_sobreturno_motivo",
        "turno",
        "(sobreturno IS NOT TRUE OR "
        "(motivo_sobreturno IS NOT NULL AND motivo_sobreturno <> ''))",
    )

    op.drop_constraint("ck_turno_estado", "turno", type_="check")
    op.create_check_constraint(
        "ck_turno_estado",
        "turno",
        f"estado IN ({_lista(ESTADOS_C04)})",
    )

    # GiST parcial: la excepción de sobreturno queda visible en el catálogo.
    op.execute("ALTER TABLE turno DROP CONSTRAINT ex_turno_profesional_sin_solape")
    op.execute("ALTER TABLE turno DROP CONSTRAINT ex_turno_sillon_sin_solape")
    inactivos = _lista(ESTADOS_INACTIVOS)
    op.execute(
        f"""ALTER TABLE turno ADD CONSTRAINT ex_turno_profesional_sin_solape
        EXCLUDE USING gist (
            profesional_id WITH =,
            tstzrange(inicio, fin, '[)') WITH &&
        ) WHERE (estado NOT IN ({inactivos}) AND (sobreturno IS NOT TRUE))"""
    )
    op.execute(
        f"""ALTER TABLE turno ADD CONSTRAINT ex_turno_sillon_sin_solape
        EXCLUDE USING gist (
            sillon_id WITH =,
            tstzrange(inicio, fin, '[)') WITH &&
        ) WHERE (sillon_id IS NOT NULL AND estado NOT IN ({inactivos})
                 AND (sobreturno IS NOT TRUE))"""
    )

    # Token duplicado original-reprogramado/nuevo-activo: unicidad parcial.
    op.drop_constraint("turno_token_publico_key", "turno", type_="unique")
    op.create_index(
        "uq_turno_token_activo",
        "turno",
        ["token_publico"],
        unique=True,
        postgresql_where=sa.text(f"estado NOT IN ({inactivos})"),
    )

    op.create_index("ix_turno_inicio_fin", "turno", ["inicio", "fin"])


def downgrade() -> None:
    op.drop_index("ix_turno_inicio_fin", table_name="turno")
    op.drop_index("uq_turno_token_activo", table_name="turno")
    op.create_unique_constraint("turno_token_publico_key", "turno", ["token_publico"])

    op.execute("ALTER TABLE turno DROP CONSTRAINT ex_turno_profesional_sin_solape")
    op.execute("ALTER TABLE turno DROP CONSTRAINT ex_turno_sillon_sin_solape")
    inactivos = _lista(ESTADOS_INACTIVOS)
    op.execute(
        f"""ALTER TABLE turno ADD CONSTRAINT ex_turno_profesional_sin_solape
        EXCLUDE USING gist (
            profesional_id WITH =,
            tstzrange(inicio, fin, '[)') WITH &&
        ) WHERE (estado NOT IN ({inactivos}))"""
    )
    op.execute(
        f"""ALTER TABLE turno ADD CONSTRAINT ex_turno_sillon_sin_solape
        EXCLUDE USING gist (
            sillon_id WITH =,
            tstzrange(inicio, fin, '[)') WITH &&
        ) WHERE (sillon_id IS NOT NULL AND estado NOT IN ({inactivos}))"""
    )

    op.drop_constraint("ck_turno_estado", "turno", type_="check")
    op.create_check_constraint(
        "ck_turno_estado",
        "turno",
        f"estado IN ({_lista(ESTADOS_PREVIOS)})",
    )
    op.drop_constraint("ck_turno_sobreturno_motivo", "turno", type_="check")

    op.drop_index("ix_turno_reprogramado_de", table_name="turno")
    op.drop_constraint("fk_turno_reprogramado_de", "turno", type_="foreignkey")
    op.drop_column("turno", "reprogramado_de_id")
    op.drop_column("turno", "motivo_sobreturno")
    op.drop_column("turno", "sobreturno")
