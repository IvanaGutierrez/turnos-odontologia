"""Rotación de refresh + reuso → 401 + logout (C-02 RED).

Spec `auth/autenticacion-jwt` + design §3: refresh válido rota el par
(jtis nuevos, fila vieja revocada + `bl:refresh:{jti}` en Redis); reusar
el viejo → 401; logout invalida el vigente. Datos sintéticos (R0).
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
REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"

EMAIL_ROTACION = "login.rotacion.ficticio@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Login-1234-no-real"


@pytest_asyncio.fixture()
async def usuario_rotacion() -> AsyncGenerator[None, None]:
    """Usuario sintético; self-cleanup aunque el test falle (RED)."""
    async with TestSession() as sesion:
        sesion.add(
            Usuario(
                email=EMAIL_ROTACION,
                password_hash=hashear_password(PASSWORD_FICTICIA),
                rol="recepcion",
                activo=True,
            )
        )
        await sesion.commit()
    yield
    async with TestSession() as sesion:
        await sesion.execute(delete(Usuario).where(Usuario.email == EMAIL_ROTACION))
        await sesion.commit()


async def _login_par(
    cliente: AsyncClient,
) -> tuple[str, str]:
    """Arrange compartido: login válido → (access, refresh). Falla en RED."""
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_ROTACION, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    refresco = login.cookies.get("refresh_token")
    assert refresco is not None
    return login.json()["access_token"], refresco


async def test_refresh_valido_rota_par_nuevo(
    cliente: AsyncClient, usuario_rotacion: None
) -> None:
    # Arrange: par inicial (login válido).
    _access_viejo, refresco_viejo = await _login_par(cliente)

    # Act: rotar con el refresh vigente.
    respuesta = await cliente.post(
        REFRESH_URL, headers={"Cookie": f"refresh_token={refresco_viejo}"}
    )

    # Assert: 200 con par nuevo de jtis distintos.
    assert respuesta.status_code == 200
    refresco_nuevo = respuesta.cookies.get("refresh_token")
    assert refresco_nuevo is not None and refresco_nuevo != refresco_viejo
    assert respuesta.json()["access_token"] != _access_viejo


async def test_reuso_refresh_viejo_401_y_revoca_cadena(
    cliente: AsyncClient, usuario_rotacion: None
) -> None:
    # Arrange: par rotado una vez (el viejo queda revocado).
    _access, refresco_viejo = await _login_par(cliente)
    rotacion = await cliente.post(
        REFRESH_URL, headers={"Cookie": f"refresh_token={refresco_viejo}"}
    )
    assert rotacion.status_code == 200

    # Act: reusar el refresh viejo (señal de robo).
    respuesta = await cliente.post(
        REFRESH_URL, headers={"Cookie": f"refresh_token={refresco_viejo}"}
    )

    # Assert: 401 (y en GREEN: cadena de sesiones revocada + auditoría).
    assert respuesta.status_code == 401


async def test_logout_invalida_refresh(
    cliente: AsyncClient, usuario_rotacion: None
) -> None:
    # Arrange: sesión válida (login).
    _access, refresco = await _login_par(cliente)

    # Act: logout y luego intento de refresh con la sesión cerrada.
    cierre = await cliente.post(
        LOGOUT_URL, headers={"Cookie": f"refresh_token={refresco}"}
    )
    posterior = await cliente.post(
        REFRESH_URL, headers={"Cookie": f"refresh_token={refresco}"}
    )

    # Assert: logout 200/204 y refresh posterior 401.
    assert cierre.status_code in (200, 204)
    assert posterior.status_code == 401
