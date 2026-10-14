"""007 programación de avisos C-06 (GREEN, R2: todo schema vía Alembic).

- `aviso_envio.programado_para TIMESTAMPTZ NULL`: ventana de envío
  (`inicio - RECORDATORIO_24H_MIN / AVISO_3H_MIN`); el worker solo envía
  filas vencidas (`NULL` = inmediato, p. ej. `confirmacion`). Backfill:
  `programado_para = creado_en` en filas preexistentes (vencidas → el
  worker las drena en el próximo ciclo, sin spam histórico porque en
  GREEN aún no hay filas productivas).
- `paciente.sin_whatsapp BOOLEAN NOT NULL DEFAULT FALSE`: el paciente
  sin WhatsApp va directo a la cascada email/SMS sin llamar a Meta.
- Índice `ix_aviso_programado` (reclamo del worker por ventana).

Sin tocar GiST ni constraints de agenda (R3 intacta).
Rollback: `downgrade -1` elimina índice + columnas.
"""

import sqlalchemy as sa
from alembic import op

revision = "007_avisos_programacion"
down_revision = "006_aviso_envio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "aviso_envio",
        sa.Column("programado_para", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE aviso_envio SET programado_para = creado_en")
    op.create_index("ix_aviso_programado", "aviso_envio", ["programado_para"])
    op.add_column(
        "paciente",
        sa.Column(
            "sin_whatsapp",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("paciente", "sin_whatsapp")
    op.drop_index("ix_aviso_programado", table_name="aviso_envio")
    op.drop_column("aviso_envio", "programado_para")
