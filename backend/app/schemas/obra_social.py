"""Contratos de validación OS preventiva C-13 (documentan sin mirar el código).

- `POST /api/v1/obras-sociales/validar {turno_id, afiliacion_id}`
  (JWT `admin|recepcion|odontologo`): matching en 3 pasos con
  cortocircuito —(a) afiliación vigente del paciente del turno, (b)
  prestación en nomenclador LOCAL vigente, (c) topes/frecuencias contra
  historial local (`fuente: historial_local`)— → `200` con `{resultado:
  cubre|parcial|no_cubre, detalle, validacion_id, nomenclador_version}`
  + `deriva_particular=true` si `no_cubre` (el staff genera el
  presupuesto por el flujo C-07 existente, sin cambios). Validar NUNCA
  muta el turno (solo escribe `ValidacionCobertura` + evento
  `validacion_os_registrada`). Sin permiso → `403` + `acceso_denegado`;
  turno/afiliación inexistente → `404` idéntico; afiliación de otro
  paciente u OS inactiva → `422`. Jamás nro. de afiliado ni DNI en
  responses (R6).
- `GET/POST /api/v1/afiliaciones` y `GET/PATCH/DELETE
  /api/v1/afiliaciones/:id` (JWT solo `admin|recepcion`; `DELETE`
  lógico con `vigente=false`): cada afiliación vincula `{paciente_id,
  obra_social_id, vigencia_desde, vigencia_hasta?}`; el nro. se acepta
  al alta pero se devuelve enmascarado (últimos 4) en toda lectura.
  Duplicada vigente del mismo paciente+OS → `409`; vigencia inválida
  (`hasta < desde`) → `422`. Eventos
  `afiliacion_creada|afiliacion_actualizada` sin PII.

Todo dato sintético (R0); type hints siempre (R1).
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

MASCARA_LARGO = 12


def enmascarar_nro(nro: str) -> str:
    """Últimos 4 en claro, resto tapado (R6: el nro. jamás sale en claro)."""
    ultimos = nro[-4:] if len(nro) >= 4 else nro
    return "*" * MASCARA_LARGO + ultimos


class ValidarRequest(BaseModel):
    """`POST /obras-sociales/validar`: cobertura de UN turno (solo staff)."""

    model_config = ConfigDict(extra="ignore")

    turno_id: uuid.UUID = Field(description="Turno `reservado` a validar.")
    afiliacion_id: uuid.UUID = Field(description="Afiliación del paciente.")


class AfiliacionCreate(BaseModel):
    """`POST /afiliaciones`: alta de vínculo paciente ↔ OS (solo staff)."""

    model_config = ConfigDict(extra="ignore")

    paciente_id: uuid.UUID = Field(description="Paciente (ficticio en tests).")
    obra_social_id: uuid.UUID = Field(description="OS con nomenclador local.")
    nro_afiliado: str = Field(
        min_length=1, max_length=80, description="Nro. ficticio (se enmascara)."
    )
    vigencia_desde: date = Field(description="Inicio de vigencia.")
    vigencia_hasta: date | None = Field(
        default=None, description="Fin de vigencia (NULL = abierta)."
    )


class AfiliacionPatch(BaseModel):
    """`PATCH /afiliaciones/:id`: vigencia y baja/alta lógica (solo staff)."""

    model_config = ConfigDict(extra="ignore")

    vigencia_hasta: date | None = Field(
        default=None, description="Fin de vigencia (NULL = abierta)."
    )
    vigente: bool | None = Field(default=None, description="`false` = baja lógica.")
