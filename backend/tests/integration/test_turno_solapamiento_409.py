"""Solapamiento secuencial: 409 por profesional/sillón; distintos sillones → 201."""

import pytest
from httpx import AsyncClient

from tests.conftest import (
    ID_PROFESIONAL_A,
    ID_PROFESIONAL_B,
    ID_SILLON_S1,
    ID_SILLON_S2,
    TURNOS_URL,
    inicio_demo,
    payload_turno,
)

pytestmark = pytest.mark.integration


async def test_crear_turno_profesional_solapado_devuelve_409(
    cliente_autenticado: AsyncClient,
) -> None:
    # Arrange: turno activo del profesional P de 10:00 a 10:30 (consulta 30').
    from tests.conftest import ID_PRESTACION_CONSULTA_30

    existente = payload_turno(
        inicio_demo(10, 0), prestacion_id=ID_PRESTACION_CONSULTA_30
    )
    respuesta_ok = await cliente_autenticado.post(TURNOS_URL, json=existente)
    assert respuesta_ok.status_code == 201

    # Act: turno superpuesto para P de 10:15 a 10:45.
    colision = payload_turno(
        inicio_demo(10, 15), prestacion_id=ID_PRESTACION_CONSULTA_30
    )
    respuesta = await cliente_autenticado.post(TURNOS_URL, json=colision)

    # Assert: 409 profesional_ocupado con alternativos de igual duración.
    assert respuesta.status_code == 409
    datos = respuesta.json()
    assert datos["problema"] == "profesional_ocupado"
    assert len(datos["slots_alternativos"]) > 0


async def test_crear_turno_sillon_solapado_devuelve_409(
    cliente_autenticado: AsyncClient,
) -> None:
    # Arrange: turno activo en S1 de 10:00 a 11:00 (profesional A).
    existente = payload_turno(
        inicio_demo(10, 0),
        profesional_id=ID_PROFESIONAL_A,
        sillon_id=ID_SILLON_S1,
    )
    respuesta_ok = await cliente_autenticado.post(TURNOS_URL, json=existente)
    assert respuesta_ok.status_code == 201

    # Act: profesional B pide S1 de 10:30 a 11:00.
    colision = payload_turno(
        inicio_demo(10, 30),
        profesional_id=ID_PROFESIONAL_B,
        sillon_id=ID_SILLON_S1,
    )
    respuesta = await cliente_autenticado.post(TURNOS_URL, json=colision)

    # Assert: 409 sillon_ocupado con alternativos sobre ese sillón.
    assert respuesta.status_code == 409
    datos = respuesta.json()
    assert datos["problema"] == "sillon_ocupado"
    assert len(datos["slots_alternativos"]) > 0


async def test_crear_turno_mismo_horario_distintos_sillones_permitido(
    cliente_autenticado: AsyncClient,
) -> None:
    # Arrange: turno activo en S1 de 10:00 a 11:00.
    existente = payload_turno(
        inicio_demo(10, 0),
        profesional_id=ID_PROFESIONAL_A,
        sillon_id=ID_SILLON_S1,
    )
    respuesta_ok = await cliente_autenticado.post(TURNOS_URL, json=existente)
    assert respuesta_ok.status_code == 201

    # Act: otro profesional en S2, mismo horario.
    otro = payload_turno(
        inicio_demo(10, 0),
        profesional_id=ID_PROFESIONAL_B,
        sillon_id=ID_SILLON_S2,
    )
    respuesta = await cliente_autenticado.post(TURNOS_URL, json=otro)

    # Assert: 201 (recursos distintos, sin colisión).
    assert respuesta.status_code == 201
