"""Seed demo idempotente: doble ejecución no duplica (escenario semilla del spec)."""

import pytest
from sqlalchemy import func, select

from app import seed_demo
from app.models.entidades import Paciente, Prestacion, Profesional, Sillon, Usuario
from tests.conftest import TestSession

pytestmark = pytest.mark.integration


async def test_seed_demo_doble_ejecucion_no_duplica() -> None:
    # Arrange + Act: dos corridas seguidas del seed (datos sintéticos).
    async with TestSession() as sesion:
        await seed_demo.seed(sesion)
        await seed_demo.seed(sesion)

        async def contar(modelo: object) -> int:
            resultado = await sesion.execute(select(func.count()).select_from(modelo))
            return resultado.scalar_one()

        total_admins = await contar(Usuario)
        total_sillones = await contar(Sillon)
        total_prestaciones = await contar(Prestacion)
        total_profesionales = await contar(Profesional)
        total_pacientes = await contar(Paciente)

    # Assert: consultorio ficticio completo y sin duplicados.
    assert total_admins == 1
    assert total_prestaciones == 6
    assert total_pacientes == 1
    assert total_sillones >= 1
    assert total_profesionales >= 1
