"""RBAC deny-by-default + 401 sin token (C-02 RED).

Spec `auth/autorizacion-rbac`: todo endpoint interno exige JWT y autoriza
contra la matriz (`03_actores_y_roles.md`); combinación no permitida →
403 genérico + evento auditado; sin token → 401 (antes de evaluar roles).

Contratos asumidos para GREEN (documentados; parte 2 los implementa):
- `GET /api/v1/usuarios` → solo `admin` (gestión de usuarios y roles).
- `GET /api/v1/agenda/mia` → `odontologo` (agenda propia).
- `GET /api/v1/configuracion/agenda` → solo `admin`.
Datos 100 % sintéticos (R0).
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.security import hashear_password
from app.models.auditoria import AuditoriaLog
from app.models.entidades import Usuario
from tests.conftest import TestSession

pytestmark = pytest.mark.integration

LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"
USUARIOS_URL = "/api/v1/usuarios"
AGENDA_MIA_URL = "/api/v1/agenda/mia"
CONFIG_AGENDA_URL = "/api/v1/configuracion/agenda"

EMAIL_RECEPCION = "recepcion.ficticia@consultorio.example"
EMAIL_ODONTOLOGO = "odontologo.ficticio@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Login-1234-no-real"


@pytest_asyncio.fixture()
async def usuarios_por_rol() -> AsyncGenerator[None, None]:
    """Recepción + odontólogo sintéticos; self-cleanup en RED."""
    async with TestSession() as sesion:
        sesion.add(
            Usuario(
                email=EMAIL_RECEPCION,
                password_hash=hashear_password(PASSWORD_FICTICIA),
                rol="recepcion",
                activo=True,
            )
        )
        sesion.add(
            Usuario(
                email=EMAIL_ODONTOLOGO,
                password_hash=hashear_password(PASSWORD_FICTICIA),
                rol="odontologo",
                activo=True,
            )
        )
        await sesion.commit()
    yield
    async with TestSession() as sesion:
        await sesion.execute(
            delete(Usuario).where(
                Usuario.email.in_([EMAIL_RECEPCION, EMAIL_ODONTOLOGO])
            )
        )
        await sesion.execute(
            delete(AuditoriaLog).where(
                AuditoriaLog.entidad.in_(["usuario", "configuracion"])
            )
        )
        await sesion.commit()


async def _access_para(cliente: AsyncClient, email: str) -> str:
    """Arrange: login y access del rol pedido. Falla en RED (sin endpoint)."""
    login = await cliente.post(
        LOGIN_URL, json={"email": email, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return login.json()["access_token"]


async def test_recepcion_gestion_usuarios_403(
    cliente: AsyncClient, usuarios_por_rol: None
) -> None:
    # Arrange: access con rol `recepcion`.
    access = await _access_para(cliente, EMAIL_RECEPCION)

    # Act: operación reservada a `admin`.
    respuesta = await cliente.get(
        USUARIOS_URL, headers={"Authorization": f"Bearer {access}"}
    )

    # Assert: 403 genérico (sin enumerar roles) y sin ejecutar la acción.
    assert respuesta.status_code == 403
    assert "admin" not in respuesta.text.lower()


async def test_odontologo_agenda_propia_200_y_config_admin_403(
    cliente: AsyncClient, usuarios_por_rol: None
) -> None:
    # Arrange: access con rol `odontologo`.
    access = await _access_para(cliente, EMAIL_ODONTOLOGO)

    # Act: agenda propia (permitida) + configuración admin (denegada).
    propia = await cliente.get(
        AGENDA_MIA_URL, headers={"Authorization": f"Bearer {access}"}
    )
    config = await cliente.get(
        CONFIG_AGENDA_URL, headers={"Authorization": f"Bearer {access}"}
    )

    # Assert: matriz según `03_actores_y_roles.md`.
    assert [propia.status_code, config.status_code] == [200, 403]


async def test_denegacion_genera_evento_auditoria(
    cliente: AsyncClient, usuarios_por_rol: None
) -> None:
    # Arrange: access con rol `recepcion`.
    access = await _access_para(cliente, EMAIL_RECEPCION)

    # Act: operación reservada a `admin` (denegada).
    respuesta = await cliente.get(
        USUARIOS_URL, headers={"Authorization": f"Bearer {access}"}
    )

    # Assert: 403 + fila de denegación en `auditoria_log` (RN-AU-03).
    assert respuesta.status_code == 403
    async with TestSession() as sesion:
        filas = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "acceso_denegado",
                        AuditoriaLog.entidad == "usuario",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(filas) == 1


async def test_endpoint_sin_token_401(cliente: AsyncClient) -> None:
    # Arrange: sin header de autorización (nada que limpiar).
    # Act: endpoint interno sin token.
    respuesta = await cliente.get(ME_URL)

    # Assert: 401 (no 403) sin ejecutar la acción.
    assert respuesta.status_code == 401
