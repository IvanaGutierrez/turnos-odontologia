"""Doble reserva concurrente por sillón (distinto profesional): una gana, otra 409."""

import asyncio

import pytest
from httpx import AsyncClient

from tests.conftest import (
    ID_PROFESIONAL_A,
    ID_PROFESIONAL_B,
    ID_SILLON_S1,
    TURNOS_URL,
    inicio_demo,
    payload_turno,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow]


async def test_crear_turno_sillon_solapado_concurrente_uno_gana(
    cliente_autenticado: AsyncClient,
) -> None:
    # Arrange: mismo sillón S1, profesionales distintos, rangos superpuestos.
    cuerpo_a = payload_turno(
        inicio_demo(10, 0), profesional_id=ID_PROFESIONAL_A, sillon_id=ID_SILLON_S1
    )
    cuerpo_b = payload_turno(
        inicio_demo(10, 30), profesional_id=ID_PROFESIONAL_B, sillon_id=ID_SILLON_S1
    )

    # Act: dos POST simultáneos sobre S1.
    respuestas = await asyncio.gather(
        cliente_autenticado.post(TURNOS_URL, json=cuerpo_a),
        cliente_autenticado.post(TURNOS_URL, json=cuerpo_b),
    )
    estados = sorted(r.status_code for r in respuestas)

    # Assert: exactamente un 201 y un 409 por sillón con alternativos.
    assert estados == [201, 409]
    perdedora = next(r for r in respuestas if r.status_code == 409)
    cuerpo409 = perdedora.json()
    assert cuerpo409["problema"] == "sillon_ocupado"
    assert len(cuerpo409["slots_alternativos"]) > 0
