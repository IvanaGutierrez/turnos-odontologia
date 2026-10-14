"""C-03 task 1.2 RED: disponibilidad sin PII + errores genéricos.

Contrato que la parte 2 (GREEN) debe cumplir:
- Cada item `200` contiene SOLO `{inicio, fin, profesional_id,
  prestacion_id}` (sin DNI/teléfonos/HC de terceros, R6; tampoco en logs).
- `prestacion_id` inexistente → `404` genérico; `desde >= hasta` o ventana
  mayor al máximo → `422` genérico (sin revelar horarios/bloqueos/turnos).

Estado parte 1: el endpoint NO existe → estos tests FALLAN en rojo.
PII 100 % ficticia (R0 + R6).
"""

import logging
import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient

from tests.conftest import (
    DNI_FICTICIO,
    ID_PRESTACION_LIMPIEZA_45,
    ID_PROFESIONAL_A,
    TURNOS_URL,
    inicio_demo,
    payload_paciente_ficticio,
    payload_turno,
)
from tests.integration.test_disponibilidad_excluye_ocupados import (
    DISPONIBILIDAD_URL,
    _sembrar_horario,
)

pytestmark = pytest.mark.integration

TEL_FICTICIO_CORTO = "5000-0001"


async def test_disponibilidad_no_filtra_quien_ocupa(
    cliente: AsyncClient,
    cliente_autenticado: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: turno de otro paciente (PII ficticia) ocupando 10:00–10:45.
    dia = inicio_demo(10, 0).weekday()
    await _sembrar_horario(dia)
    existente = payload_turno(
        inicio_demo(10, 0),
        paciente_id=None,  # type: ignore[arg-type]
        paciente=payload_paciente_ficticio(),
    )
    existente.pop("paciente_id", None)
    respuesta_ok = await cliente_autenticado.post(TURNOS_URL, json=existente)
    assert respuesta_ok.status_code == 201
    base = inicio_demo(10, 0).replace(hour=0, minute=0, second=0, microsecond=0)

    # Act: consulta pública capturando logs.
    with caplog.at_level(logging.INFO):
        respuesta = await cliente.get(
            DISPONIBILIDAD_URL,
            params={
                "prestacion_id": str(ID_PRESTACION_LIMPIEZA_45),
                "profesional_id": str(ID_PROFESIONAL_A),
                "desde": base.isoformat(),
                "hasta": (base + timedelta(days=1)).isoformat(),
            },
        )

    # Assert: shape mínimo sin PII en cuerpo ni en logs.
    assert respuesta.status_code == 200
    for item in respuesta.json():
        assert set(item.keys()) == {
            "inicio",
            "fin",
            "profesional_id",
            "prestacion_id",
        }
    assert DNI_FICTICIO not in respuesta.text
    assert TEL_FICTICIO_CORTO not in respuesta.text
    assert DNI_FICTICIO not in caplog.text
    assert TEL_FICTICIO_CORTO not in caplog.text


async def test_prestacion_inexistente_devuelve_404_generico(
    cliente: AsyncClient,
) -> None:
    # Arrange: UUID sintético que no corresponde a ninguna prestación.
    base = inicio_demo(10, 0).replace(hour=0, minute=0, second=0, microsecond=0)

    # Act: consulta con prestación inexistente.
    respuesta = await cliente.get(
        DISPONIBILIDAD_URL,
        params={
            "prestacion_id": str(uuid.uuid4()),
            "profesional_id": str(ID_PROFESIONAL_A),
            "desde": base.isoformat(),
            "hasta": (base + timedelta(days=1)).isoformat(),
        },
    )

    # Assert: 404 con el shape genérico del dominio (no el `detail` de
    # Starlette: eso probaría solo que la ruta falta, un falso verde),
    # sin revelar horarios, bloqueos ni turnos.
    assert respuesta.status_code == 404
    datos = respuesta.json()
    assert datos["problema"] == "no_encontrado"
    assert "profesional" not in respuesta.text.lower()
    assert "bloqueo" not in respuesta.text.lower()


async def test_ventana_invalida_devuelve_422_generico(
    cliente: AsyncClient,
) -> None:
    # Arrange: ventana invertida (`desde >= hasta`).
    base = inicio_demo(10, 0).replace(hour=0, minute=0, second=0, microsecond=0)

    # Act: consulta con ventana inválida.
    respuesta = await cliente.get(
        DISPONIBILIDAD_URL,
        params={
            "prestacion_id": str(ID_PRESTACION_LIMPIEZA_45),
            "profesional_id": str(ID_PROFESIONAL_A),
            "desde": (base + timedelta(days=1)).isoformat(),
            "hasta": base.isoformat(),
        },
    )

    # Assert: 422 con shape de validación del dominio (un 404 de Starlette
    # por ruta inexistente también falla aquí: nada de falsos verdes),
    # sin revelar agenda interna.
    assert respuesta.status_code == 422
    datos = respuesta.json()
    assert datos["problema"] == "validacion"
    assert DNI_FICTICIO not in respuesta.text
    assert "bloqueo" not in respuesta.text.lower()
