"""Fin calculado desde la prestación; fin libre ignorado; adyacencia permitida."""

from datetime import datetime as _dt
from datetime import timedelta

import pytest
from httpx import AsyncClient

from tests.conftest import (
    ID_PRESTACION_CONSULTA_30,
    ID_PRESTACION_LIMPIEZA_45,
    ID_PROFESIONAL_A,
    TURNOS_URL,
    inicio_demo,
    payload_turno,
)

pytestmark = pytest.mark.integration


async def test_crear_turno_valido_calcula_fin(cliente_autenticado: AsyncClient) -> None:
    # Arrange: Limpieza 45' con profesional y sillón libres.
    inicio = inicio_demo(10, 0)
    cuerpo = payload_turno(inicio, prestacion_id=ID_PRESTACION_LIMPIEZA_45)

    # Act.
    respuesta = await cliente_autenticado.post(TURNOS_URL, json=cuerpo)

    # Assert: 201 con fin = inicio + 45', estado reservado y token único.
    assert respuesta.status_code == 201
    datos = respuesta.json()
    assert _dt.fromisoformat(datos["fin"]) == inicio + timedelta(minutes=45)
    assert datos["estado"] == "reservado"
    assert datos["token_publico"]


async def test_crear_turno_fin_libre_sin_motivo_se_ignora(
    cliente_autenticado: AsyncClient,
) -> None:
    # Arrange: Consulta 30' pero el cliente envía un fin arbitrario (+2 h).
    inicio = inicio_demo(11, 0)
    cuerpo = payload_turno(
        inicio,
        prestacion_id=ID_PRESTACION_CONSULTA_30,
        fin=(inicio + timedelta(hours=2)).isoformat(),
    )

    # Act.
    respuesta = await cliente_autenticado.post(TURNOS_URL, json=cuerpo)

    # Assert: el fin enviado no surte efecto (inicio + 30').
    assert respuesta.status_code == 201
    datos = respuesta.json()
    assert _dt.fromisoformat(datos["fin"]) == inicio + timedelta(minutes=30)


async def test_crear_turno_adyacente_permitido(
    cliente_autenticado: AsyncClient,
) -> None:
    # Arrange: turno existente 10:00–10:30 del mismo profesional (30').
    primero = payload_turno(inicio_demo(10, 0), prestacion_id=ID_PRESTACION_CONSULTA_30)
    respuesta1 = await cliente_autenticado.post(TURNOS_URL, json=primero)
    assert respuesta1.status_code == 201

    # Act: turno adyacente 10:30–11:00 (fin exclusivo, no colisiona).
    segundo = payload_turno(
        inicio_demo(10, 30),
        profesional_id=ID_PROFESIONAL_A,
        prestacion_id=ID_PRESTACION_CONSULTA_30,
    )
    respuesta2 = await cliente_autenticado.post(TURNOS_URL, json=segundo)

    # Assert: 201 (los rangos '[)' back-to-back están permitidos).
    assert respuesta2.status_code == 201
