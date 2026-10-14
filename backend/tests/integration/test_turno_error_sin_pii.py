"""El 409 por colisión no filtra PII del otro turno (R6)."""

import logging

import pytest
from httpx import AsyncClient

from tests.conftest import (
    DNI_FICTICIO,
    TURNOS_URL,
    inicio_demo,
    payload_paciente_ficticio,
    payload_turno,
)

pytestmark = pytest.mark.integration


async def test_colision_409_no_expone_dni_telefono(
    cliente_autenticado: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange: turno existente de otro paciente (PII 100 % ficticia).
    existente = payload_turno(
        inicio_demo(10, 0),
        paciente_id=None,  # type: ignore[arg-type]
        paciente=payload_paciente_ficticio(),
    )
    existente.pop("paciente_id", None)
    respuesta_ok = await cliente_autenticado.post(TURNOS_URL, json=existente)
    assert respuesta_ok.status_code == 201

    # Act: colisión sobre el mismo profesional/sillón, capturando logs.
    colision = payload_turno(inicio_demo(10, 15))
    with caplog.at_level(logging.WARNING):
        respuesta = await cliente_autenticado.post(TURNOS_URL, json=colision)

    # Assert: 409 sin DNI/teléfono en cuerpo ni en logs.
    assert respuesta.status_code == 409
    assert DNI_FICTICIO not in respuesta.text
    assert "5000-0001" not in respuesta.text
    assert DNI_FICTICIO not in caplog.text
    assert "5000-0001" not in caplog.text
    datos = respuesta.json()
    assert datos["problema"] in (
        "profesional_ocupado",
        "sillon_ocupado",
        "slot_ocupado",
    )
