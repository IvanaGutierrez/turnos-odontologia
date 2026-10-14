"""C-03 task 1.1 RED: slots = horario − bloqueos − turnos activos.

Contrato que la parte 2 (GREEN) debe cumplir:
- `GET /api/v1/disponibilidad?prestacion_id&profesional_id&desde&hasta`
  → `200` con lista de `{inicio, fin, ...}` de `prestacion.duracion_min`.
- Ventana totalmente ocupada → `200` con lista vacía (jamás slot fantasma).

Estado parte 1: el endpoint NO existe → estos tests FALLAN en rojo.
Todo dato sintético (R0); sin PII real en fixtures ni asserts (R6).
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from tests.conftest import (
    ID_PRESTACION_LIMPIEZA_45,
    ID_PROFESIONAL_A,
    ID_SILLON_S1,
    TURNOS_URL,
    TestSession,
    inicio_demo,
    payload_turno,
)

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
DISPONIBILIDAD_URL = "/api/v1/disponibilidad"

HORA_APERTURA = time(8, 0)
HORA_CIERRE = time(13, 0)


async def _sembrar_horario(
    dia_semana: int,
    hora_inicio: time = HORA_APERTURA,
    hora_fin: time = HORA_CIERRE,
) -> None:
    """Arrange: franja semanal del profesional (ORM directo, sin API aún)."""
    from app.models.disponibilidad import HorarioProfesional

    async with TestSession() as sesion:
        sesion.add(
            HorarioProfesional(
                profesional_id=ID_PROFESIONAL_A,
                dia_semana=dia_semana,
                hora_inicio=hora_inicio,
                hora_fin=hora_fin,
                vigente_desde=None,
                vigente_hasta=None,
                activo=True,
            )
        )
        await sesion.commit()


async def _sembrar_bloqueo(desde: datetime, hasta: datetime) -> None:
    """Arrange: bloqueo puntual del profesional (ORM directo)."""
    from app.models.disponibilidad import Bloqueo

    async with TestSession() as sesion:
        sesion.add(
            Bloqueo(
                profesional_id=ID_PROFESIONAL_A,
                sillon_id=None,
                desde=desde,
                hasta=hasta,
                motivo="Feriado ficticio demo",
                creado_por=None,
            )
        )
        await sesion.commit()


async def _ocupar_con_turno(
    cliente_autenticado: AsyncClient, inicio: datetime
) -> None:
    """Arrange: turno activo vía el camino protegido C-01 (ya en verde)."""
    respuesta = await cliente_autenticado.post(
        TURNOS_URL, json=payload_turno(inicio)
    )
    assert respuesta.status_code == 201


def _ventana_dia(inicio: datetime) -> tuple[str, str]:
    base = inicio.replace(hour=0, minute=0, second=0, microsecond=0)
    return (base.isoformat(), (base + timedelta(days=1)).isoformat())


def _solapa(slot: dict[str, str], desde: datetime, hasta: datetime) -> bool:
    ini = datetime.fromisoformat(slot["inicio"])
    fin = datetime.fromisoformat(slot["fin"])
    return ini < hasta and desde < fin


async def test_slots_excluyen_turno_activo_y_bloqueo(
    cliente: AsyncClient, cliente_autenticado: AsyncClient
) -> None:
    # Arrange: horario 8–13; turno activo 10:00–10:45; bloqueo 12:00–13:00.
    dia = inicio_demo(10, 0).weekday()
    await _sembrar_horario(dia)
    await _ocupar_con_turno(cliente_autenticado, inicio_demo(10, 0))
    await _sembrar_bloqueo(inicio_demo(12, 0), inicio_demo(13, 0))
    desde, hasta = _ventana_dia(inicio_demo(10, 0))

    # Act: consulta pública de disponibilidad.
    respuesta = await cliente.get(
        DISPONIBILIDAD_URL,
        params={
            "prestacion_id": str(ID_PRESTACION_LIMPIEZA_45),
            "profesional_id": str(ID_PROFESIONAL_A),
            "desde": desde,
            "hasta": hasta,
        },
    )

    # Assert: 200 sin ningún slot superpuesto a lo ocupado, con huecos
    # libres antes y después (slots de 45' por la prestación).
    assert respuesta.status_code == 200
    slots = respuesta.json()
    assert isinstance(slots, list)
    assert not any(
        _solapa(s, inicio_demo(10, 0), inicio_demo(10, 45)) for s in slots
    )
    assert not any(
        _solapa(s, inicio_demo(12, 0), inicio_demo(13, 0)) for s in slots
    )
    assert any(
        datetime.fromisoformat(s["fin"]) <= inicio_demo(10, 0) for s in slots
    )
    assert any(
        datetime.fromisoformat(s["inicio"]) >= inicio_demo(10, 45)
        and datetime.fromisoformat(s["fin"]) <= inicio_demo(12, 0)
        for s in slots
    )


async def test_ventana_totalmente_ocupada_devuelve_lista_vacia(
    cliente: AsyncClient, cliente_autenticado: AsyncClient
) -> None:
    # Arrange: horario de un solo slot (10:00–10:45) cubierto por un turno.
    dia = inicio_demo(10, 0).weekday()
    await _sembrar_horario(dia, hora_inicio=time(10, 0), hora_fin=time(10, 45))
    await _ocupar_con_turno(cliente_autenticado, inicio_demo(10, 0))
    desde, hasta = _ventana_dia(inicio_demo(10, 0))

    # Act: consulta pública de disponibilidad.
    respuesta = await cliente.get(
        DISPONIBILIDAD_URL,
        params={
            "prestacion_id": str(ID_PRESTACION_LIMPIEZA_45),
            "profesional_id": str(ID_PROFESIONAL_A),
            "desde": desde,
            "hasta": hasta,
        },
    )

    # Assert: jamás slot fantasma → lista vacía (no un slot que colisione).
    assert respuesta.status_code == 200
    assert respuesta.json() == []


async def test_bloqueo_de_sillon_tambien_excluye_slots(
    cliente: AsyncClient, cliente_autenticado: AsyncClient
) -> None:
    # Arrange: horario 8–13; bloqueo de S1 9:00–10:00 (sede, sin profesional).
    from app.models.disponibilidad import Bloqueo

    dia = inicio_demo(9, 0).weekday()
    await _sembrar_horario(dia)
    async with TestSession() as sesion:
        sesion.add(
            Bloqueo(
                profesional_id=None,
                sillon_id=ID_SILLON_S1,
                desde=inicio_demo(9, 0),
                hasta=inicio_demo(10, 0),
                motivo="Mantenimiento ficticio demo",
                creado_por=None,
            )
        )
        await sesion.commit()
    desde, hasta = _ventana_dia(inicio_demo(9, 0))

    # Act: consulta pública de disponibilidad.
    respuesta = await cliente.get(
        DISPONIBILIDAD_URL,
        params={
            "prestacion_id": str(ID_PRESTACION_LIMPIEZA_45),
            "profesional_id": str(ID_PROFESIONAL_A),
            "desde": desde,
            "hasta": hasta,
        },
    )

    # Assert: ningún slot pisa el bloqueo del sillón.
    assert respuesta.status_code == 200
    slots = respuesta.json()
    assert len(slots) > 0
    assert not any(
        _solapa(s, inicio_demo(9, 0), inicio_demo(10, 0)) for s in slots
    )
