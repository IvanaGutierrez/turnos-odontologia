"""Rate limit y bloqueo temporal en login → 429 (C-02 RED).

Spec `auth/autenticacion-jwt` + design §4: tope 5/60 s por IP+email
(clave hasheada `rl:login:{ip}:{sha256(email)}`) → 429 con `Retry-After`;
10 fallidos → bloqueo 900 s (`lock:login:{sha256(email)}`) aunque la
credencial sea correcta. Datos sintéticos (R0).
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

EMAIL_RATELIMIT = "login.ratelimit.ficticio@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Login-1234-no-real"
PASSWORD_INCORRECTA = "Incorrecta-5678-no-real"


@pytest_asyncio.fixture()
async def usuario_ratelimit() -> AsyncGenerator[None, None]:
    """Usuario sintético; self-cleanup aunque el test falle (RED)."""
    async with TestSession() as sesion:
        sesion.add(
            Usuario(
                email=EMAIL_RATELIMIT,
                password_hash=hashear_password(PASSWORD_FICTICIA),
                rol="recepcion",
                activo=True,
            )
        )
        await sesion.commit()
    yield
    async with TestSession() as sesion:
        await sesion.execute(delete(Usuario).where(Usuario.email == EMAIL_RATELIMIT))
        await sesion.commit()


async def test_login_sexto_intento_misma_ip_email_429(
    cliente: AsyncClient, usuario_ratelimit: None
) -> None:
    # Arrange: 5 intentos dentro de la ventana de 60 s (misma IP+email).
    for _ in range(5):
        await cliente.post(
            LOGIN_URL,
            json={"email": EMAIL_RATELIMIT, "password": PASSWORD_INCORRECTA},
        )

    # Act: sexto intento con la misma combinación IP+email.
    respuesta = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_RATELIMIT, "password": PASSWORD_INCORRECTA}
    )

    # Assert: 429 con indicación de reintento, sin procesar la credencial.
    assert respuesta.status_code == 429
    assert respuesta.headers.get("retry-after") is not None


async def test_bloqueo_temporal_tras_10_fallidos_429(
    cliente: AsyncClient, usuario_ratelimit: None
) -> None:
    # Arrange: 10 intentos fallidos (disparan `lock:` de 900 s).
    for _ in range(10):
        await cliente.post(
            LOGIN_URL,
            json={"email": EMAIL_RATELIMIT, "password": PASSWORD_INCORRECTA},
        )

    # Act: credencial correcta durante el bloqueo.
    respuesta = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_RATELIMIT, "password": PASSWORD_FICTICIA}
    )

    # Assert: 429 aunque la credencial sea correcta (bloqueo temporal).
    assert respuesta.status_code == 429
