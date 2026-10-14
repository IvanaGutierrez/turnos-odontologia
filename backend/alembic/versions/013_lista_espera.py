"""013 lista de espera inteligente C-14 (parte 1 RED: solo esquema, R2).

Tablas (2, sin tocar agenda/pago/avisos/auditoría — C-04/C-05/C-06/C-08
solo lectura; el trigger `hueco_liberado`, el scoring y el reclamo
atómico llegan en la parte 2 GREEN):

- `lista_espera`: una anotación `{paciente, prestación, profesional?}`
  con ventana de disponibilidad (`ventana_desde < ventana_hasta`,
  ambos `timestamptz`). `score NUMERIC(6,2)` NULL hasta que el worker
  ranquea el hueco + `score_componentes jsonb` (auditable, sin PII).
  Máquina `activa|ofertada|asignada|expirada` (el servicio la mueve;
  la baja manual y la ventana vencida van a `expirada`). FKs CASCADE
  salvo `profesional_id SET NULL` (la espera sobrevive a la baja del
  profesional; en prod la baja es lógica). Índices `(estado, ventana)`
  para el barrido + lookups por paciente/prestación.
- `oferta_espera`: una oferta expirable por entrada+hueco. El hueco es
  un snapshot congelado (`profesional_id/sillon_id/inicio/fin` copiados
  del turno cancelado + `hueco_origen_id` como agrupador, SIN FK: el
  turno origen puede purgarse y la oferta es historia). La oferta NO
  reserva el slot (decisión madre del design): el turno recién se
  inserta al acreditarse la seña, bajo el GiST vigente (R3). Máquina
  `pendiente|aceptada|expirada|desplazada` + `expira_at` (TTL por env)
  + `mp_preference_id` UNIQUE (un link de seña por oferta).
  UNIQUE parcial `(lista_espera_id, hueco_origen_id) WHERE pendiente`:
  nadie recibe dos ofertas pendientes del mismo hueco (la DB manda).
  Índices `(hueco_origen_id, estado)` (hermanas del hueco) +
  `(estado, expira_at)` (barredor de expiración).

Todo dato de prueba sintético (R0); type hints siempre (R1).
Rollback: `downgrade -1` elimina ambas tablas (orden inverso).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "013_lista_espera"
down_revision = "012_validacion_os"
branch_labels = None
depends_on = None

ESTADOS_ESPERA: tuple[str, ...] = ("activa", "ofertada", "asignada", "expirada")

ESTADOS_OFERTA: tuple[str, ...] = ("pendiente", "aceptada", "expirada", "desplazada")


def _lista(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


def upgrade() -> None:
    op.create_table(
        "lista_espera",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paciente_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("paciente.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "prestacion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prestacion.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profesional_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("profesional.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ventana_desde", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ventana_hasta", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Numeric(6, 2), nullable=True),
        sa.Column(
            "score_componentes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "estado",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'activa'"),
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
            "ventana_desde < ventana_hasta",
            name="ck_lista_espera_ventana",
        ),
        sa.CheckConstraint(
            f"estado IN ({_lista(ESTADOS_ESPERA)})",
            name="ck_lista_espera_estado",
        ),
    )
    op.create_index(
        "ix_lista_espera_estado_ventana",
        "lista_espera",
        ["estado", "ventana_desde", "ventana_hasta"],
    )
    op.create_index(
        "ix_lista_espera_paciente", "lista_espera", ["paciente_id"]
    )
    op.create_index(
        "ix_lista_espera_prestacion", "lista_espera", ["prestacion_id"]
    )

    op.create_table(
        "oferta_espera",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "lista_espera_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lista_espera.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Agrupador del hueco cancelado (snapshot, sin FK — ver docstring).
        sa.Column("hueco_origen_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profesional_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sillon_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fin", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expira_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "estado",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pendiente'"),
        ),
        sa.Column("mp_preference_id", sa.Text(), nullable=True),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("fin > inicio", name="ck_oferta_fin_mayor_inicio"),
        sa.CheckConstraint(
            f"estado IN ({_lista(ESTADOS_OFERTA)})",
            name="ck_oferta_estado",
        ),
        sa.UniqueConstraint("mp_preference_id", name="uq_oferta_mp_preference"),
    )
    op.create_index(
        "ix_oferta_hueco_estado",
        "oferta_espera",
        ["hueco_origen_id", "estado"],
    )
    op.create_index(
        "ix_oferta_espera", "oferta_espera", ["lista_espera_id"]
    )
    op.create_index(
        "ix_oferta_expira", "oferta_espera", ["estado", "expira_at"]
    )
    # Una sola oferta pendiente por entrada+hueco (la DB manda ante
    # doble blast concurrente del mismo hueco).
    op.create_index(
        "uq_oferta_pendiente_por_hueco",
        "oferta_espera",
        ["lista_espera_id", "hueco_origen_id"],
        unique=True,
        postgresql_where=sa.text("estado = 'pendiente'"),
    )


def downgrade() -> None:
    op.drop_index("uq_oferta_pendiente_por_hueco", table_name="oferta_espera")
    op.drop_index("ix_oferta_expira", table_name="oferta_espera")
    op.drop_index("ix_oferta_espera", table_name="oferta_espera")
    op.drop_index("ix_oferta_hueco_estado", table_name="oferta_espera")
    op.drop_table("oferta_espera")
    op.drop_index("ix_lista_espera_prestacion", table_name="lista_espera")
    op.drop_index("ix_lista_espera_paciente", table_name="lista_espera")
    op.drop_index("ix_lista_espera_estado_ventana", table_name="lista_espera")
    op.drop_table("lista_espera")
