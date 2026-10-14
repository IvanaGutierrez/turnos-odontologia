"""Doble reserva concurrente por profesional: exactamente una gana (201) y la otra 409."""

import asyncio
from datetime import datetime as _dt
from datetime import timedelta

import pytest
from httpx import AsyncClient

from tests.conftest import TURNOS_URL, inicio_demo, payload_turno

pytestmark = [pytest.mark.integration, pytest.mark.slow]


async def test_crear_turno_profesional_solapado_concurrente_uno_gana(
    cliente_autenticado: AsyncClient,
) -> None:
    # Arrange: slot libre para el profesional (datos sintéticos).
    cuerpo = payload_turno(inicio_demo(10, 0))

    # Act: dos POST idénticos simultáneos.
    respuestas = await asyncio.gather(
        cliente_autenticado.post(TURNOS_URL, json=cuerpo),
        cliente_autenticado.post(TURNOS_URL, json=cuerpo),
    )
    estados = sorted(r.status_code for r in respuestas)

    # Assert: exactamente un 201 y un 409 con alternativos de igual duración.
    assert estados == [201, 409]
    perdedora = next(r for r in respuestas if r.status_code == 409)
    cuerpo409 = perdedora.json()
    assert cuerpo409["problema"] == "profesional_ocupado"
    alternativos = cuerpo409["slots_alternativos"]
    assert len(alternativos) > 0
    primero = alternativos[0]
    dur = _dt.fromisoformat(primero["fin"]) - _dt.fromisoformat(primero["inicio"])
    assert dur == timedelta(minutes=45)
