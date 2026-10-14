"""Access expirado o de tipo incorrecto → 401 (C-02 RED, freezegun).

Spec `auth/autenticacion-jwt`: access de 15' vencido, firma inválida o
`type != access` se rechaza en `GET /auth/me` sin devolver el perfil.
Datos sintéticos (R0).
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from freezegun import freeze_time
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.security import hashear_password
from app.models.entidades import Usuario
from tests.conftest import TestSession

pytestmark = pytest.mark.integration

LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"

EMAIL_EXPIRACION = "login.expiracion.ficticio@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Login-1234-no-real"


@pytest_asyncio.fixture()
async def usuario_expiracion() -> AsyncGenerator[None, None]:
    """Usuario sintético; self-cleanup aunque el test falle (RED)."""
    async with TestSession() as sesion:
        sesion.add(
            Usuario(
                email=EMAIL_EXPIRACION,
                password_hash=hashear_password(PASSWORD_FICTICIA),
                rol="recepcion",
                activo=True,
            )
        )
        await sesion.commit()
    yield
    async with TestSession() as sesion:
        await sesion.execute(delete(Usuario).where(Usuario.email == EMAIL_EXPIRACION))
        await sesion.commit()


@freeze_time("2026-11-03 10:00:00")
async def test_access_expirado_me_401(
    cliente: AsyncClient, usuario_expiracion: None
) -> None:
    # Arrange: login válido → access de 15' (hora congelada 10:00).
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_EXPIRACION, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    access = login.json()["access_token"]

    # Act: viajar más allá de los 15' (+16') y pedir el perfil.
    with freeze_time("2026-11-03 10:16:00"):
        respuesta = await cliente.get(
            ME_URL, headers={"Authorization": f"Bearer {access}"}
        )

    # Assert: 401 sin datos del perfil.
    assert respuesta.status_code == 401
    assert "password_hash" not in respuesta.text


@freeze_time("2026-11-03 10:00:00")
async def test_access_con_type_refresh_rechazado_401(
    cliente: AsyncClient, usuario_expiracion: None
) -> None:
    # Arrange: login válido → refresh en cookie HttpOnly.
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_EXPIRACION, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    refresco = login.cookies.get("refresh_token")
    assert refresco is not None

    # Act: usar el refresh como si fuera access en /me.
    respuesta = await cliente.get(
        ME_URL, headers={"Authorization": f"Bearer {refresco}"}
    )

    # Assert: 401 (el endpoint exige `type = access`).
    assert respuesta.status_code == 401
