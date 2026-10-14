"""Schemas del catálogo de agenda C-04 (spec `agenda/configuracion-agenda`).

Escritura solo `admin` (recurso `configuracion_agenda`); lectura para
roles con `turnos`/`agenda_propia`. Validaciones de catálogo → 422
genérico sin crear registros (`duracion_min > 0`, `hora_inicio < hora_fin`
con `dia_semana` 0–6, bloqueo con `desde < hasta`).
"""

import uuid
from datetime import date, time
from typing import Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


class ProfesionalCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nombre: str = Field(min_length=1, max_length=200)
    matricula: str = Field(min_length=1, max_length=50)


class ProfesionalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    matricula: str
    activo: bool = True


class SillonCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nombre: str = Field(min_length=1, max_length=100)
    sede: str = Field(default="Consultorio", max_length=100)


class SillonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    sede: str
    activo: bool = True


class PrestacionCreate(BaseModel):
    """Alta de prestación (`duracion_min > 0` o 422, sin crear nada)."""

    model_config = ConfigDict(extra="ignore")

    nombre: str = Field(min_length=1, max_length=150)
    duracion_min: int = Field(gt=0)


class PrestacionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    duracion_min: int


class HorarioCreate(BaseModel):
    """Franja semanal (`dia_semana` 0=lunes…6=domingo, inicio < fin)."""

    model_config = ConfigDict(extra="ignore")

    profesional_id: uuid.UUID
    dia_semana: int = Field(ge=0, le=6)
    hora_inicio: time
    hora_fin: time
    vigente_desde: date | None = None
    vigente_hasta: date | None = None

    @model_validator(mode="after")
    def _horas_ordenadas(self) -> Self:
        if not self.hora_inicio < self.hora_fin:
            raise ValueError("`hora_inicio` debe ser anterior a `hora_fin`")
        return self


class HorarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    profesional_id: uuid.UUID
    dia_semana: int
    hora_inicio: time
    hora_fin: time


class BloqueoCreate(BaseModel):
    """Excepción puntual (`desde < hasta` o 422, sin crear nada)."""

    model_config = ConfigDict(extra="ignore")

    profesional_id: uuid.UUID | None = None
    sillon_id: uuid.UUID | None = None
    desde: AwareDatetime
    hasta: AwareDatetime
    motivo: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _ventana_ordenada(self) -> Self:
        if not self.desde < self.hasta:
            raise ValueError("`desde` debe ser anterior a `hasta`")
        return self


class BloqueoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    profesional_id: uuid.UUID | None
    sillon_id: uuid.UUID | None
    desde: AwareDatetime
    hasta: AwareDatetime
    motivo: str | None = None
