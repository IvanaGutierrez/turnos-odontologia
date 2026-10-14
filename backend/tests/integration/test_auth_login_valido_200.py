"""Login válido emite access + refresh (C-02 RED: `POST /auth/login` no existe).

Contrato asumido (spec `auth/autenticacion-jwt` + design §2/§6):
- body `{"access_token": "<jwt>", "token_type": "bearer"}`.
- refresh en cookie `refresh_token` HttpOnly (`samesite=lax`).
Datos 100 % sintéticos (R0).
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

# Credencial ficticia (R0): jamás corresponde a una persona real.
EMAIL_LOGIN_VALIDO = "login.valido.ficticio@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Login-1234-no-real"


@pytest_asyncio.fixture()
async def usuario_login_valido() -> AsyncGenerator[Usuario, None]:
    """Usuario interno sintético; self-cleanup aunque el test falle (RED)."""
    async with TestSession() as sesion:
        sesion.add(
            Usuario(
                email=EMAIL_LOGIN_VALIDO,
                password_hash=hashear_password(PASSWORD_FICTICIA),
                rol="recepcion",
                activo=True,
            )
        )
        await sesion.commit()
    yield Usuario(email=EMAIL_LOGIN_VALIDO, password_hash="", rol="recepcion")
    async with TestSession() as sesion:
        await sesion.execute(delete(Usuario).where(Usuario.email == EMAIL_LOGIN_VALIDO))
        await sesion.commit()


async def test_login_credencial_valida_emite_access_y_refresh(
    cliente: AsyncClient, usuario_login_valido: Usuario
) -> None:
    # Arrange: usuario interno sintético activo (fixture).
    # Act: login con la credencial correcta.
    respuesta = await cliente.post(
        LOGIN_URL,
        json={"email": EMAIL_LOGIN_VALIDO, "password": PASSWORD_FICTICIA},
    )

    # Assert: 200 + access con forma JWT + refresh en cookie HttpOnly.
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["token_type"] == "bearer"
    assert len(datos["access_token"].split(".")) == 3
    refresco = respuesta.cookies.get("refresh_token")
    assert refresco is not None and len(refresco.split(".")) == 3
