"""Schemas Pydantic de agenda (independientes del ORM, `from_attributes=True`)."""

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.validators_ar import validar_dni_ar, validar_telefono_ar

Problema409 = Literal["slot_ocupado", "profesional_ocupado", "sillon_ocupado"]

# `en_sala` es alias transitorio de lectura: la grilla lo normaliza a
# `presente` (canónico de check-in, design decisión 2; C-05 consolida).
ESTADO_ALIAS_LECTURA: dict[str, str] = {"en_sala": "presente"}


class PacienteCreate(BaseModel):
    nombre: str
    dni: str
    telefono: str
    consentimiento_hc: bool = False

    @field_validator("dni")
    @classmethod
    def _dni_ar(cls, v: str) -> str:
        return validar_dni_ar(v)

    @field_validator("telefono")
    @classmethod
    def _telefono_ar(cls, v: str) -> str:
        return validar_telefono_ar(v)


class TurnoCreate(BaseModel):
    """La API nunca acepta `fin` libre: se calcula en el servicio (RN-AG-03).

    C-01 RED: el campo `fin` ni siquiera se declara; si el cliente lo envía,
    Pydantic lo ignora (comportamiento verificado en test fin-libre).
    """

    model_config = ConfigDict(extra="ignore")

    paciente_id: uuid.UUID | None = None
    paciente: PacienteCreate | None = None
    profesional_id: uuid.UUID
    sillon_id: uuid.UUID | None = None
    prestacion_id: uuid.UUID
    inicio: AwareDatetime
    motivo_override: str | None = None
    canal: str = "mostrador"

    @model_validator(mode="after")
    def _paciente_xor_id(self) -> Self:
        if (self.paciente is None) == (self.paciente_id is None):
            raise ValueError("Indicar `paciente` o `paciente_id`, exactamente uno")
        return self


class SlotAlternativo(BaseModel):
    inicio: datetime
    fin: datetime


class TurnoRead(BaseModel):
    """Lectura operativa de recepción (C-04: suma `sobreturno`).

    El flag solo lo escribe el endpoint dedicado `POST /turnos/sobreturno`;
    el `TurnoCreate` normal lo ignora (`extra="ignore"`, R3).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    paciente_id: uuid.UUID
    profesional_id: uuid.UUID
    sillon_id: uuid.UUID | None
    prestacion_id: uuid.UUID
    inicio: datetime
    fin: datetime
    estado: str
    token_publico: str
    sobreturno: bool = False


class AgendaItem(BaseModel):
    """Item de grilla día/semana (spec `agenda/agenda-recepcion`, R6).

    Visibilidad por rol: `{id, inicio, fin, estado, profesional_id,
    sillon_id, prestacion_id, sobreturno}` + `paciente_nombre` (necesario
    para operar el día). Jamás DNI, teléfono, HC, hashes ni tokens: ni en
    el cuerpo ni en logs (Ley 25.326 minimización).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    inicio: datetime
    fin: datetime
    estado: str
    profesional_id: uuid.UUID
    sillon_id: uuid.UUID | None
    prestacion_id: uuid.UUID
    sobreturno: bool = False
    paciente_nombre: str | None = None
    # C-14: la grilla de recepción distingue el origen (p. ej. el turno
    # asignado desde la lista de espera viaja con `canal=lista_espera`).
    canal: str = "mostrador"


class SobreturnoCreate(BaseModel):
    """Alta de sobreturno (solo endpoint dedicado, motivo obligatorio).

    Misma base que `TurnoCreate` + `motivo_sobreturno` no vacío; el servicio
    fuerza `sobreturno=true` y audita `sobreturno_creado` (quién/cuándo/por
    qué). El flag en el body normal se ignora (R3, design decisión 1).
    """

    model_config = ConfigDict(extra="ignore")

    paciente_id: uuid.UUID | None = None
    paciente: PacienteCreate | None = None
    profesional_id: uuid.UUID
    sillon_id: uuid.UUID | None = None
    prestacion_id: uuid.UUID
    inicio: AwareDatetime
    motivo_override: str | None = None
    canal: str = "recepcion"
    motivo_sobreturno: str | None = Field(default=None)

    @model_validator(mode="after")
    def _paciente_xor_id(self) -> Self:
        if (self.paciente is None) == (self.paciente_id is None):
            raise ValueError("Indicar `paciente` o `paciente_id`, exactamente uno")
        return self

    @model_validator(mode="after")
    def _motivo_obligatorio(self) -> Self:
        # En `mode="after"` (corre siempre, aun con default `None`): el
        # sobreturno exige motivo no vacío o el endpoint responde 422.
        if self.motivo_sobreturno is None or not self.motivo_sobreturno.strip():
            raise ValueError("El sobreturno exige `motivo_sobreturno` no vacío")
        self.motivo_sobreturno = self.motivo_sobreturno.strip()
        return self


class ReprogramarRequest(BaseModel):
    """Destino de reprogramación (RN-AG-07): `fin` se recalcula en servicio."""

    model_config = ConfigDict(extra="ignore")

    nuevo_inicio: AwareDatetime
    motivo_override: str | None = None


class Error409(BaseModel):
    problema: Problema409
    detalle: str
    slots_alternativos: list[SlotAlternativo]
