"""008 ficha clínica C-07 (GREEN mínimo de esquema, R2: todo schema vía Alembic).

Tablas (7, sin tocar GiST ni agenda — R3 intacta):
- `catalogo_odontograma_estado`: catálogo versionado de estados del
  odontograma. PK compuesta `(version, codigo)`; las entries referencian
  la tupla para preservar historia ante cambios de catálogo (v2 nunca
  reescribe v1). Seed v1 con ~18 estados (ref. DentalSoft).
- `ficha`: HCE por paciente. `anamnesis_cifrada BYTEA` (cifrado app-level
  en parte 2; la columna solo guarda bytes), `consentimiento_en NOT NULL`
  como defensa en profundidad del gate RN-CL-01 (sin snapshot no hay HCE),
  `firmante_usuario_id + firmado_en` (trazabilidad RN-CL-04),
  `clave_id` (rotación de `HCE_CIFRADO_KEY`).
- `odontograma_entry`: una fila por `(ficha_id, pieza_fdi, cara)`.
  `pieza_fdi` con `CHECK 11–48` (el servicio valida FDI real
  11–18/21–28/31–38/41–48); `cara` opcional con check de valores;
  FK compuesta `(catalogo_version, estado_codigo)` al catálogo;
  `UNIQUE (ficha_id, pieza_fdi, cara NULLS NOT DISTINCT)` (upsert por
  pieza) + índice `(ficha_id, pieza_fdi)`.
- `evolucion`: `texto_cifrado BYTEA` + firmante (igual que ficha).
- `presupuesto`: máquina `borrador→aprobado→pagado_parcial|pagado`,
  `borrador→rechazado` (terminal). `total` y `sena_requerida`
  calculados en servicio; firma del paciente (`firma_paciente_en` +
  `firma_hash`) gatea `borrador→aprobado` (RN-CL-03); `version` para
  inmutabilidad post-firma (cambiar exige nueva versión).
- `presupuesto_item`: pieza + prestación + cantidad + precio unitario.
- `plan_tratamiento`: un plan por presupuesto (`UNIQUE presupuesto_id`),
  `etapas JSONB` + índice GIN, `estado` propio y `sena_requerida`
  (consumida por C-08).

Rollback: `downgrade -1` elimina las 7 tablas (orden inverso).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "008_ficha_clinica"
down_revision = "007_avisos_programacion"
branch_labels = None
depends_on = None

CARAS_VALIDAS: tuple[str, ...] = (
    "oclusal",
    "mesial",
    "distal",
    "vestibular",
    "lingual",
    "palatino",
)

ESTADOS_PRESUPUESTO: tuple[str, ...] = (
    "borrador",
    "aprobado",
    "pagado_parcial",
    "pagado",
    "rechazado",
)

ESTADOS_PLAN: tuple[str, ...] = (
    "planificado",
    "en_curso",
    "completado",
    "cancelado",
)

# Seed v1 del catálogo (~18 estados, códigos estables, solo códigos en API).
CATALOGO_V1: tuple[tuple[str, str], ...] = (
    ("sano", "Pieza sana, sin hallazgos"),
    ("cariado", "Lesión de caries activa"),
    ("obturado", "Obturación presente"),
    ("sellante", "Sellante de fosas y fisuras"),
    ("endodoncia", "Tratamiento de conducto realizado"),
    ("corona", "Corona protésica"),
    ("implante", "Implante osteointegrado"),
    ("extraccion_indicada", "Extracción indicada"),
    ("ausente", "Pieza ausente"),
    ("fracturado", "Fractura coronaria o radicular"),
    ("perno_munon", "Perno-muñón"),
    ("inlay", "Incrustación inlay"),
    ("onlay", "Incrustación onlay"),
    ("protesis_fija", "Prótesis fija (puente)"),
    ("protesis_removible", "Prótesis removible"),
    ("ortodoncia", "En tratamiento de ortodoncia"),
    ("vigilancia", "En vigilancia o control"),
    ("tratamiento_periodontal", "En tratamiento periodontal"),
)


def _lista(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


def upgrade() -> None:
    op.create_table(
        "catalogo_odontograma_estado",
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column(
            "activo", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.PrimaryKeyConstraint("version", "codigo", name="pk_catalogo_odo_estado"),
    )
    op.create_table(
        "ficha",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "paciente_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("paciente.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profesional_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("profesional.id"),
            nullable=False,
        ),
        sa.Column("fecha", sa.Date(), server_default=sa.text("CURRENT_DATE")),
        sa.Column("anamnesis_cifrada", postgresql.BYTEA(), nullable=True),
        sa.Column(
            "firmante_usuario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuario.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("firmado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consentimiento_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "clave_id",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'hce-v1'"),
        ),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "odontograma_entry",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "ficha_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ficha.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pieza_fdi", sa.Integer(), nullable=False),
        sa.Column("estado_codigo", sa.Text(), nullable=False),
        sa.Column("catalogo_version", sa.Integer(), nullable=False),
        sa.Column("cara", sa.Text(), nullable=True),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("pieza_fdi BETWEEN 11 AND 48", name="ck_odo_pieza_fdi"),
        sa.CheckConstraint(
            f"(cara IS NULL) OR (cara IN ({_lista(CARAS_VALIDAS)}))",
            name="ck_odo_cara",
        ),
        sa.ForeignKeyConstraint(
            ["catalogo_version", "estado_codigo"],
            ["catalogo_odontograma_estado.version", "catalogo_odontograma_estado.codigo"],
            name="fk_odo_catalogo",
        ),
        sa.UniqueConstraint(
            "ficha_id",
            "pieza_fdi",
            "cara",
            name="uq_odo_ficha_pieza_cara",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_odo_ficha_pieza", "odontograma_entry", ["ficha_id", "pieza_fdi"]
    )
    op.create_table(
        "evolucion",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "ficha_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ficha.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("texto_cifrado", postgresql.BYTEA(), nullable=False),
        sa.Column(
            "firmante_usuario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuario.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("firmado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "clave_id",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'hce-v1'"),
        ),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_evolucion_ficha", "evolucion", ["ficha_id"])
    op.create_table(
        "presupuesto",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "ficha_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ficha.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "estado",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'borrador'"),
        ),
        sa.Column(
            "total",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("moneda", sa.String(3), nullable=False, server_default="'ARS'"),
        sa.Column(
            "sena_requerida",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("firma_paciente_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("firma_hash", sa.Text(), nullable=True),
        sa.Column("motivo_rechazo", sa.Text(), nullable=True),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
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
            f"estado IN ({_lista(ESTADOS_PRESUPUESTO)})",
            name="ck_presupuesto_estado",
        ),
        sa.CheckConstraint("total >= 0", name="ck_presupuesto_total"),
        sa.CheckConstraint("sena_requerida >= 0", name="ck_presupuesto_sena"),
        sa.CheckConstraint("version >= 1", name="ck_presupuesto_version"),
    )
    op.create_index("ix_presupuesto_ficha", "presupuesto", ["ficha_id"])
    op.create_table(
        "presupuesto_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "presupuesto_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("presupuesto.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pieza_fdi", sa.Integer(), nullable=True),
        sa.Column("estado_codigo", sa.Text(), nullable=True),
        sa.Column(
            "prestacion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prestacion.id"),
            nullable=True,
        ),
        sa.Column("detalle", sa.Text(), nullable=True),
        sa.Column(
            "cantidad", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("precio_unitario", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint("cantidad >= 1", name="ck_pitem_cantidad"),
        sa.CheckConstraint("precio_unitario >= 0", name="ck_pitem_precio"),
    )
    op.create_index(
        "ix_pitem_presupuesto", "presupuesto_item", ["presupuesto_id"]
    )
    op.create_table(
        "plan_tratamiento",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "presupuesto_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("presupuesto.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "etapas",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "estado",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'planificado'"),
        ),
        sa.Column(
            "sena_requerida",
            sa.Numeric(12, 2),
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
            f"estado IN ({_lista(ESTADOS_PLAN)})",
            name="ck_plan_estado",
        ),
        sa.CheckConstraint("sena_requerida >= 0", name="ck_plan_sena"),
        sa.UniqueConstraint("presupuesto_id", name="uq_plan_presupuesto"),
    )
    op.create_index(
        "ix_plan_etapas_gin", "plan_tratamiento", ["etapas"], postgresql_using="gin"
    )

    # Seed v1 del catálogo (códigos estables; v2 agrega filas, jamás edita v1).
    tabla_catalogo = sa.table(
        "catalogo_odontograma_estado",
        sa.column("version", sa.Integer()),
        sa.column("codigo", sa.Text()),
        sa.column("descripcion", sa.Text()),
        sa.column("activo", sa.Boolean()),
    )
    op.bulk_insert(
        tabla_catalogo,
        [
            {"version": 1, "codigo": codigo, "descripcion": desc, "activo": True}
            for codigo, desc in CATALOGO_V1
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_plan_etapas_gin", table_name="plan_tratamiento")
    op.drop_table("plan_tratamiento")
    op.drop_index("ix_pitem_presupuesto", table_name="presupuesto_item")
    op.drop_table("presupuesto_item")
    op.drop_index("ix_presupuesto_ficha", table_name="presupuesto")
    op.drop_table("presupuesto")
    op.drop_index("ix_evolucion_ficha", table_name="evolucion")
    op.drop_table("evolucion")
    op.drop_index("ix_odo_ficha_pieza", table_name="odontograma_entry")
    op.drop_table("odontograma_entry")
    op.drop_table("ficha")
    op.drop_table("catalogo_odontograma_estado")
