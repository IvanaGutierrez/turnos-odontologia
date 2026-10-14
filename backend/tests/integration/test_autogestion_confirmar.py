"""C-05 task 1.2 RED: confirmar turno con token (idempotente + seña, R5).

Contrato que la parte 2 (GREEN) debe cumplir (`agenda/autogestion-paciente`):
- `POST /api/v1/turnos/publicos/:token/confirmar` sin JWT: `reservado` →
  `confirmado` (`200`) + auditoría `turno_confirmado` sin PII.
- Duplicado (incluso concurrente) → `200` idempotente con UNA sola auditoría.
- Prestación con `requiere_sena` sin pago acreditado → `422`
  (`problema=sena_pendiente` + `url_pago` no vacía) sin mutar el estado
  (el cobro es C-08; aquí no se crea `Pago`).
- Token inválido → `404` idéntico (ver `test_autogestion_ver.py`).

Estado parte 1: el router público NO existe → FALLAN en rojo (404).
Todo dato sintético (R0); type hints siempre (R1).
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.security import hashear_password
from app.models.auditoria import AuditoriaLog
from app.models.entidades import Prestacion, Turno, Usuario
from tests.conftest import (
    DNI_FICTICIO,
    TestSession,
    inicio_demo,
    payload_turno,
)

pytestmark = pytest.mark.integration

AUTOGESTION_URL = "/api/v1/turnos/publicos"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_STAFF = "autogestion.confirmar.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Autogestion-Confirmar-1234-no-real"


@pytest_asyncio.fixture()
async def staff() -> AsyncGenerator[None, None]:
    """Usuario recepción sintético (crea turnos vía núcleo C-01)."""
    async with TestSession() as sesion:
        sesion.add(
            Usuario(
                email=EMAIL_STAFF,
                password_hash=hashear_password(PASSWORD_FICTICIA),
                rol="recepcion",
                activo=True,
            )
        )
        await sesion.commit()
    yield
    async with TestSession() as sesion:
        await sesion.execute(delete(Usuario).where(Usuario.email == EMAIL_STAFF))
        await sesion.commit()


async def _access(cliente: AsyncClient) -> str:
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_STAFF, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


async def _crear(
    cliente: AsyncClient, access: str, inicio: datetime, **extras: object
) -> dict[str, object]:
    """Arrange: turno `reservado` vía núcleo C-01."""
    respuesta = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio, **extras),
        headers={"Authorization": f"Bearer {access}"},
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["estado"] == "reservado"
    return dict(respuesta.json())


async def _auditorias(turno_id: str, accion: str) -> list[AuditoriaLog]:
    async with TestSession() as sesion:
        return list(
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == accion,
                        AuditoriaLog.entidad_id == turno_id,
                    )
                )
            )
            .scalars()
            .all()
        )


async def test_confirmar_reservado_pasa_a_confirmado_y_audita(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno `reservado` sin seña requerida.
    access = await _access(cliente)
    creado = await _crear(cliente, access, inicio_demo(10, 0).replace(day=5))

    # Act: confirmar por token sin JWT.
    respuesta = await cliente.post(
        f"{AUTOGESTION_URL}/{creado['token_publico']}/confirmar"
    )

    # Assert: 200 `confirmado` + UNA auditoría sin PII.
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "confirmado"
    filas = await _auditorias(str(creado["id"]), "turno_confirmado")
    assert len(filas) == 1
    assert DNI_FICTICIO not in str(filas[0].diff)
    assert "5000-0001" not in str(filas[0].diff)


async def test_confirmar_duplicado_idempotente_sin_duplicar_auditoria(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno `reservado` a confirmar dos veces (concurrente).
    access = await _access(cliente)
    creado = await _crear(cliente, access, inicio_demo(12, 0).replace(day=5))
    url = f"{AUTOGESTION_URL}/{creado['token_publico']}/confirmar"

    # Act: doble confirmación simultánea del mismo token.
    primera, segunda = await asyncio.gather(
        cliente.post(url), cliente.post(url)
    )

    # Assert: ambas 200 `confirmado`, UNA sola auditoría, estado final único.
    assert [primera.status_code, segunda.status_code] == [200, 200]
    assert primera.json()["estado"] == "confirmado"
    assert segunda.json()["estado"] == "confirmado"
    assert len(await _auditorias(str(creado["id"]), "turno_confirmado")) == 1
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
        assert turno is not None and turno.estado == "confirmado"


async def test_confirmar_con_sena_pendiente_422_con_url_pago_sin_mutar(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: prestación ficticia con seña + turno `reservado` sobre ella.
    id_sena = uuid.uuid4()
    async with TestSession() as sesion:
        sesion.add(
            Prestacion(
                id=id_sena,
                nombre="Endodoncia Demo Seña Autogestión Ficticia",
                duracion_min=45,
                requiere_sena=True,
            )
        )
        await sesion.commit()
    access = await _access(cliente)
    try:
        creado = await _crear(
            cliente,
            access,
            inicio_demo(14, 0).replace(day=5),
            prestacion_id=id_sena,
        )

        # Act: confirmar con seña pendiente (sin pago acreditado, C-08).
        respuesta = await cliente.post(
            f"{AUTOGESTION_URL}/{creado['token_publico']}/confirmar"
        )

        # Assert: 422 + link de pago, estado intacto, sin auditoría de alta.
        assert respuesta.status_code == 422
        datos = respuesta.json()
        assert datos["problema"] == "sena_pendiente"
        assert datos["url_pago"]
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
            assert turno is not None and turno.estado == "reservado"
        assert await _auditorias(str(creado["id"]), "turno_confirmado") == []
    finally:
        async with TestSession() as sesion:
            await sesion.execute(
                Turno.__table__.delete().where(
                    Turno.prestacion_id == id_sena  # type: ignore[arg-type]
                )
            )
            await sesion.execute(
                Prestacion.__table__.delete().where(
                    Prestacion.id == id_sena  # type: ignore[arg-type]
                )
            )
            await sesion.commit()
