"""Schemas públicos C-03 (sin JWT): disponibilidad + reserva online (R6).

La reserva reutiliza `PacienteCreate` (validación AR DNI/E.164) y nunca
acepta `fin` libre: se calcula desde la prestación (RN-AG-03).
"""

import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.schemas.turno import PacienteCreate


class TurnoPublicoCreate(BaseModel):
    """Reserva sin cuenta; `sillon_id` lo asigna recepción (no se expone)."""

    model_config = ConfigDict(extra="ignore")

    prestacion_id: uuid.UUID
    profesional_id: uuid.UUID
    inicio: AwareDatetime
    paciente: PacienteCreate
    codigo_verificacion: str | None = None


class TurnoPublicoRead(BaseModel):
    """Respuesta 201: solo IDs/horarios + token; jamás PII del paciente (R6)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    profesional_id: uuid.UUID
    prestacion_id: uuid.UUID
    inicio: datetime
    fin: datetime
    estado: str
    canal: str
    token_publico: str
    url_pago: str | None = None


class TurnoPropioRead(BaseModel):
    """Ver-propio C-05 (`GET /turnos/publicos/:token`, Ley 25.326).

    Campos mínimos: `estado, inicio, fin`, nombres de prestación /
    profesional / sede, `puede_cancelar_en_termino` (antelación vigente
    contra `CANCEL_MIN_HOURS`) y `horas_limite` (antelación mínima en
    horas exigida para cancelar). `url_pago` solo con seña pendiente.
    Jamás DNI, teléfono, HC, hashes ni el propio token — ni en el cuerpo
    (el token viaja solo en el path, nunca en query) ni en logs.
    """

    model_config = ConfigDict(from_attributes=True)

    estado: str
    inicio: datetime
    fin: datetime
    prestacion_nombre: str
    profesional_nombre: str
    sede: str
    puede_cancelar_en_termino: bool
    horas_limite: int


class CancelarPublicoRequest(BaseModel):
    """Motivo opcional de cancelación (se persiste en el turno, R6).

    El texto lo escribe el paciente: el `diff` de auditoría no lo incluye
    (solo IDs/horarios/estados), el motivo vive en la fila del turno.
    """

    model_config = ConfigDict(extra="ignore")

    motivo: str | None = None


class ReprogramarPublicoRequest(BaseModel):
    """Destino de reprogramación pública (RN-AG-07): `fin` se recalcula.

    Mismo núcleo que el staff (C-04): destino ocupado → `409` con
    alternativos sin mutar; el turno nuevo conserva `token_publico`.
    """

    model_config = ConfigDict(extra="ignore")

    nuevo_inicio: AwareDatetime
