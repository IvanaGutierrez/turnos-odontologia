"""Schemas Pydantic clínicos C-07 (independientes del ORM, R2).

Shapes `201/422/403`: creación de ficha gated por consentimiento, batch
de odontograma FDI por pieza, evoluciones firmadas, presupuestos nacidos
de hallazgos con firma del paciente, planes con seña y exportación Ley
25.326 (7 secciones). Sin narrativa clínica en respuestas salvo exportación
al tratante (R6 minimización).

Máquina de presupuesto: `borrador→aprobado` (exige firma) `→pagado_parcial
|pagado` (solo vía C-08), `borrador→rechazado` terminal (con motivo).
Cualquier otra transición → `422` (estado intacto).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CaraOdontograma = Literal[
    "oclusal", "mesial", "distal", "vestibular", "lingual", "palatino"
]

CARAS_VALIDAS: frozenset[str] = frozenset(
    {"oclusal", "mesial", "distal", "vestibular", "lingual", "palatino"}
)

ESTADOS_PRESUPUESTO: frozenset[str] = frozenset(
    {"borrador", "aprobado", "pagado_parcial", "pagado", "rechazado"}
)


class FichaCreate(BaseModel):
    """`POST /fichas`: solo `paciente_id` (+ `anamnesis` opcional ficticia)."""

    model_config = ConfigDict(extra="ignore")

    paciente_id: uuid.UUID
    anamnesis: str | None = Field(default=None, max_length=8000)


class FichaRead(BaseModel):
    """Lectura minimizada (jamás anamnesis en claro, R6)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    paciente_id: uuid.UUID
    firmante_usuario_id: uuid.UUID | None = None


class FichaPatch(BaseModel):
    """`PATCH /fichas/:id`: re-firma del tratante (solo odontólogo)."""

    model_config = ConfigDict(extra="ignore")

    anamnesis: str | None = Field(default=None, max_length=8000)


class OdontogramaEntryIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pieza_fdi: int
    estado_codigo: str = Field(min_length=1, max_length=60)
    cara: str | None = None


class OdontogramaBatchIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entries: list[OdontogramaEntryIn] = Field(min_length=1, max_length=64)


class OdontogramaEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pieza_fdi: int
    estado_codigo: str
    catalogo_version: int
    cara: str | None = None


class OdontogramaBatchRead(BaseModel):
    entries: list[OdontogramaEntryRead]


class EvolucionCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    texto: str = Field(min_length=1, max_length=8000)


class EvolucionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ficha_id: uuid.UUID


class HallazgoIn(BaseModel):
    """Item nacido de hallazgo (precio en el hallazgo en C-07, R0 ficticio)."""

    model_config = ConfigDict(extra="ignore")

    pieza_fdi: int | None = None
    estado_codigo: str | None = None
    cantidad: int = Field(default=1, ge=1, le=32)
    precio_unitario: Decimal = Field(ge=0)


class PresupuestoCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ficha_id: uuid.UUID
    desde_hallazgos: list[HallazgoIn] = Field(min_length=1, max_length=64)


class PresupuestoItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pieza_fdi: int | None = None
    estado_codigo: str | None = None
    cantidad: int
    precio_unitario: Decimal


class PresupuestoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    estado: str
    total: Decimal
    items: list[PresupuestoItemRead] = Field(default_factory=list)


class FirmaIn(BaseModel):
    """Registro firma+fecha del paciente (táctil/registro, RN-CL-03)."""

    model_config = ConfigDict(extra="ignore")

    firma: str = Field(min_length=1, max_length=500)
    fecha: date


class RechazoIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    motivo: str = Field(min_length=1, max_length=500)


class TransicionIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    estado_destino: str


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    presupuesto_id: uuid.UUID
    etapas: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    sena_requerida: Decimal = Field(default=Decimal(0), ge=0)


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    presupuesto_id: uuid.UUID
    estado: str
    sena_requerida: Decimal


class PacienteContactoPatch(BaseModel):
    """Contacto editable por recepción (nombre/teléfono; jamás clínica)."""

    model_config = ConfigDict(extra="ignore")

    nombre: str | None = Field(default=None, max_length=200)
    telefono: str | None = Field(default=None, max_length=25)
