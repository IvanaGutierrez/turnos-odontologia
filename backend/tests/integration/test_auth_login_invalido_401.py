"""Credencial inválida → 401 genérico sin revelar existencia (C-02 RED).

Spec `auth/autenticacion-jwt`: email inexistente, password incorrecta o
usuario inactivo responden el MISMO 401 genérico; ni la respuesta ni los
logs exponen hashes, tokens ni PII (R6). Datos sintéticos (R0).
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.security import hashear_password
from app.models.entidades import Usuario
from tests.conftest import TestSession

pytestmark = pytest.mark.integration

LOGIN_URL = "/api/v1/auth/login"

EMAIL_INEXISTENTE = "nadie.ficticio@consultorio.example"
EMAIL_REGISTRADO = "login.registrado.ficticio@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Login-1234-no-real"
PASSWORD_INCORRECTA = "Incorrecta-5678-no-real"


@pytest_asyncio.fixture()
async def usuario_registrado() -> AsyncGenerator[None, None]:
    """Usuario sintético; self-cleanup aunque el test falle (RED)."""
    async with TestSession() as sesion:
        sesion.add(
            Usuario(
                email=EMAIL_REGISTRADO,
                password_hash=hashear_password(PASSWORD_FICTICIA),
                rol="recepcion",
                activo=True,
            )
        )
        await sesion.commit()
    yield
    async with TestSession() as sesion:
        await sesion.execute(delete(Usuario).where(Usuario.email == EMAIL_REGISTRADO))
        await sesion.commit()


async def test_login_email_inexistente_401_generico(cliente: AsyncClient) -> None:
    # Arrange: email que jamás se registró (sin fixture: no existe).
    # Act: intento de login.
    respuesta = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_INEXISTENTE, "password": PASSWORD_FICTICIA}
    )

    # Assert: 401 con mensaje genérico (sin revelar inexistencia).
    assert respuesta.status_code == 401
    assert respuesta.json()["detalle"] == "Credenciales inválidas."


async def test_login_password_incorrecta_401_generico(
    cliente: AsyncClient, usuario_registrado: None
) -> None:
    # Arrange: usuario registrado sintético (fixture).
    # Act: password incorrecta.
    respuesta = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_REGISTRADO, "password": PASSWORD_INCORRECTA}
    )

    # Assert: el mismo 401 genérico que con email inexistente.
    assert respuesta.status_code == 401
    assert respuesta.json()["detalle"] == "Credenciales inválidas."


async def test_login_fallido_no_revela_existencia_ni_expone_hash(
    cliente: AsyncClient, usuario_registrado: None
) -> None:
    # Arrange: un email inexistente y uno registrado (fixture).
    # Act: ambos intentos fallidos.
    r_inexistente = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_INEXISTENTE, "password": PASSWORD_FICTICIA}
    )
    r_incorrecta = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_REGISTRADO, "password": PASSWORD_INCORRECTA}
    )

    # Assert: cuerpos idénticos (no distingue casos) y sin secretos/PII.
    assert r_inexistente.status_code == 401
    assert r_incorrecta.status_code == 401
    assert r_inexistente.json() == r_incorrecta.json()
    cuerpo = r_incorrecta.text.lower()
    assert "password_hash" not in cuerpo
    assert "hash-ficticio" not in cuerpo
    assert "telefono" not in cuerpo
