"""Cálculo de slots C-03: horario − bloqueos − turnos activos (R3/R6).

`horario vigente ∩ ventana` expandido en ranuras de `duracion_min` con paso
fino (15') y filtrado por solape `[inicio, fin)` — la misma semántica que
`repositories/agenda` y que el `EXCLUDE USING gist` con cota `'[)'`.
La DB manda ante carreras (el POST revalida con el núcleo C-01).

Deuda explícita: calendarios recurrentes ricos (feriados rotativos) → C-04.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntidadNoEncontradaError
from app.models.entidades import Prestacion, Profesional
from app.repositories import agenda as repo_agenda
from app.repositories import disponibilidad as repo_disponibilidad

BA = ZoneInfo("America/Argentina/Buenos_Aires")

# Paso fino de la grilla (submúltiplo de las duraciones demo 20/30/45/60').
PASO_SLOT_MIN = 15


class VentanaInvalidaError(ValueError):
    """Ventana `desde/hasta` inválida o mayor al máximo (→ 422 genérico)."""


def tope_max_dias() -> int:
    """`DISPON_MAX_DIAS` legible por env en cada llamada (piloto sin deploy)."""
    try:
        return int(os.environ.get("DISPON_MAX_DIAS", "30"))
    except ValueError:
        return 30


def validar_ventana(desde: datetime, hasta: datetime) -> None:
    if desde >= hasta:
        raise VentanaInvalidaError("desde debe ser anterior a hasta")
    if hasta - desde > timedelta(days=tope_max_dias()):
        raise VentanaInvalidaError("ventana mayor al máximo configurable")


def _solapa(inicio: datetime, fin: datetime, desde: datetime, hasta: datetime) -> bool:
    return inicio < hasta and desde < fin


async def calcular_slots(
    session: AsyncSession,
    *,
    profesional_id: uuid.UUID,
    prestacion_id: uuid.UUID,
    desde: datetime,
    hasta: datetime,
) -> list[dict[str, str]]:
    """Slots libres ordenados `{inicio, fin, profesional_id, prestacion_id}`.

    Lanza `EntidadNoEncontradaError` (→ 404 genérico) o `VentanaInvalidaError`
    (→ 422 genérico). Jamás incluye PII (R6): solo inicios/fines libres.
    """
    validar_ventana(desde, hasta)

    prestacion: Prestacion | None = await repo_agenda.obtener_prestacion(
        session, prestacion_id
    )
    if prestacion is None:
        raise EntidadNoEncontradaError("prestacion")
    profesional: Profesional | None = await repo_agenda.obtener_profesional(
        session, profesional_id
    )
    if profesional is None:
        raise EntidadNoEncontradaError("profesional")

    duracion = timedelta(minutes=int(prestacion.duracion_min))
    horarios = await repo_disponibilidad.obtener_horarios_profesional(
        session, profesional_id
    )

    bloqueos = await repo_disponibilidad.obtener_bloqueos_en_rango(
        session, profesional_id, desde, hasta
    )
    ocupados = [(b.desde, b.hasta) for b in bloqueos]
    turnos = await repo_disponibilidad.obtener_turnos_activos_en_rango(
        session, profesional_id, desde, hasta
    )
    ocupados.extend((t.inicio, t.fin) for t in turnos)

    slots: list[dict[str, str]] = []
    dia = desde.date()
    while dia <= hasta.date():
        for horario in horarios:
            if horario.dia_semana != dia.weekday():
                continue
            if not repo_disponibilidad.horario_vigente_en(horario, dia):
                continue
            base = datetime(dia.year, dia.month, dia.day, tzinfo=BA)
            apertura = base + timedelta(
                hours=horario.hora_inicio.hour, minutes=horario.hora_inicio.minute
            )
            cierre = base + timedelta(
                hours=horario.hora_fin.hour, minutes=horario.hora_fin.minute
            )
            candidato = apertura
            while candidato + duracion <= cierre:
                fin = candidato + duracion
                if (
                    candidato >= desde
                    and fin <= hasta
                    and not any(
                        _solapa(candidato, fin, ini, fin_ocup)
                        for ini, fin_ocup in ocupados
                    )
                ):
                    slots.append(
                        {
                            "inicio": candidato.isoformat(),
                            "fin": fin.isoformat(),
                            "profesional_id": str(profesional_id),
                            "prestacion_id": str(prestacion_id),
                        }
                    )
                candidato += timedelta(minutes=PASO_SLOT_MIN)
        dia += timedelta(days=1)

    slots.sort(key=lambda s: s["inicio"])
    return slots
