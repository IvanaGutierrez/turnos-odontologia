"""C-05 task 1.1 RED: ver turno propio con token y 404 idéntico (R6).

Contrato que la parte 2 (GREEN) debe cumplir (`agenda/autogestion-paciente`):
- `GET /api/v1/turnos/publicos/:token` sin JWT devuelve el turno propio con
  campos mínimos (`estado, inicio, fin, prestacion_nombre,
  profesional_nombre, sede, puede_cancelar_en_termino, horas_limite` y
  `url_pago` solo con seña pendiente): jamás DNI, teléfono, HC, hashes ni
  el propio token (Ley 25.326 minimización).
- Token inexistente, malformado o rotado → `404` con cuerpo byte-idéntico
  al de un token nunca emitido (`problema` genérico, sin distinguir casos
  ni exponer PII en cuerpo ni logs).

Estado parte 1: el router público NO existe → FALLAN en rojo (404 sin
`problema`, el `GET` válido tampoco responde 200).
Todo dato sintético (R0); type hints siempre (R1).
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.security import hashear_password
from app.models.entidades import Usuario
from tests.conftest import (
    DNI_FICTICIO,
    TEL_FICTICIO,
    TestSession,
    inicio_demo,
    payload_turno,
)

pytestmark = pytest.mark.integration

AUTOGESTION_URL = "/api/v1/turnos/publicos"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_STAFF = "autogestion.ver.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Autogestion-Ver-1234-no-real"

CAMPOS_MINIMOS = (
    "estado",
    "inicio",
    "fin",
    "prestacion_nombre",
    "profesional_nombre",
    "sede",
    "puede_cancelar_en_termino",
    "horas_limite",
)


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


async def _crear(cliente: AsyncClient, access: str) -> dict[str, object]:
    """Arrange: turno `reservado` vía núcleo C-01 (devuelve `token_publico`)."""
    respuesta = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio_demo(10, 0)),
        headers={"Authorization": f"Bearer {access}"},
    )
    assert respuesta.status_code == 201
    return dict(respuesta.json())


async def test_ver_turno_con_token_devuelve_campos_minimos_sin_pii(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno `reservado` con token conocido (vía núcleo C-01).
    access = await _access(cliente)
    creado = await _crear(cliente, access)
    token = str(creado["token_publico"])

    # Act: ver propio sin JWT.
    respuesta = await cliente.get(f"{AUTOGESTION_URL}/{token}")

    # Assert: 200 con campos mínimos y sin PII ni el propio token.
    assert respuesta.status_code == 200
    datos = respuesta.json()
    for campo in CAMPOS_MINIMOS:
        assert campo in datos, f"falta campo mínimo: {campo}"
    assert "url_pago" not in datos  # sin seña pendiente no hay link de pago
    cuerpo = respuesta.text
    assert DNI_FICTICIO not in cuerpo
    assert "5000-0001" not in cuerpo
    assert "historia" not in cuerpo.lower()
    assert "token_publico" not in cuerpo
    assert token not in cuerpo
    assert TEL_FICTICIO not in cuerpo


async def test_token_invalido_responde_404_identico_sin_datos(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: un token emitido (para contrastar) + uno nunca emitido.
    access = await _access(cliente)
    creado = await _crear(cliente, access)
    _ = str(creado["token_publico"])
    nunca_emitido = "token-ficticio-nunca-emitido-0000-no-real"
    malformado = "no-es-un-token"

    # Act: tres variantes inválidas (inexistente, malformado).
    r_nunca = await cliente.get(f"{AUTOGESTION_URL}/{nunca_emitido}")
    r_malformado = await cliente.get(f"{AUTOGESTION_URL}/{malformado}")

    # Assert: 404 byte-idénticos con `problema` genérico, sin PII ni horarios.
    assert r_nunca.status_code == 404
    assert r_malformado.status_code == 404
    assert r_nunca.json()["problema"]
    assert r_nunca.content == r_malformado.content
    for respuesta in (r_nunca, r_malformado):
        cuerpo = respuesta.text
        assert DNI_FICTICIO not in cuerpo
        assert "5000-0001" not in cuerpo
        assert "token_publico" not in cuerpo
        assert "inicio" not in respuesta.json()
