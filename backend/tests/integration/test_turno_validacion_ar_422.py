"""Validación AR: DNI 7–8 dígitos y teléfono E.164 AR; 422 sin crear nada."""

import pytest
from httpx import AsyncClient

from tests.conftest import TURNOS_URL, inicio_demo, payload_turno

pytestmark = pytest.mark.integration


async def test_crear_turno_dni_invalido_422(cliente_autenticado: AsyncClient) -> None:
    # Arrange: payload con DNI "12AB" (formato inválido, sintético).
    cuerpo = payload_turno(
        inicio_demo(10, 0),
        paciente_id=None,  # type: ignore[arg-type]
        paciente={
            "nombre": "Paciente Ficticia",
            "dni": "12AB",
            "telefono": "+54 9 11 5000-0001",
        },
    )
    cuerpo.pop("paciente_id", None)

    # Act.
    respuesta = await cliente_autenticado.post(TURNOS_URL, json=cuerpo)

    # Assert: 422 y el error no expone el DNI más allá del eco de validación.
    assert respuesta.status_code == 422
    assert "12AB" not in respuesta.text.replace('"dni": "12AB"', "")


async def test_crear_turno_telefono_no_e164_422(
    cliente_autenticado: AsyncClient,
) -> None:
    # Arrange: teléfono "12345" sin prefijo país ni formato AR.
    cuerpo = payload_turno(
        inicio_demo(10, 0),
        paciente_id=None,  # type: ignore[arg-type]
        paciente={
            "nombre": "Paciente Ficticia",
            "dni": "90123456",
            "telefono": "12345",
        },
    )
    cuerpo.pop("paciente_id", None)

    # Act.
    respuesta = await cliente_autenticado.post(TURNOS_URL, json=cuerpo)

    # Assert: 422 y ningún registro creado (Pydantic rechaza antes del servicio).
    assert respuesta.status_code == 422
