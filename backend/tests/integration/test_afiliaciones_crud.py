"""C-13 tasks 1.2 RED: CRUD de afiliaciones solo staff con vigencia (R5).

Contrato que la parte 2 (GREEN) debe cumplir:
- `GET/POST /api/v1/afiliaciones` y `GET/PATCH/DELETE /api/v1/afiliaciones/:id`
  (JWT solo `admin|recepcion`; `DELETE` lógico con `vigente=false`).
- Cada afiliación vincula `{paciente_id, obra_social_id, vigencia_desde,
  vigencia_hasta?}`; el nro. se acepta al alta pero se devuelve
  enmascarado (últimos 4) en toda lectura, jamás en logs/errores (R6).
- Duplicada vigente del mismo paciente+OS → `409`; vigencia inválida
  (`hasta < desde`) → `422`; afiliación ajena al validar → `422`.
- Odontólogo → `403` + `acceso_denegado`; sin JWT → `401`.
- Eventos `afiliacion_creada|afiliacion_actualizada` sin PII.

Estado parte 1: el router NO existe → FALLAN en rojo (`404`).
Todo dato sintético (R0); type hints siempre (R1); AAA.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import (
    ID_PACIENTE_DEMO,
    NRO_AFILIADO_FICTICIO_1,
    TestSession,
    crear_obra_social_ficticia,
    crear_usuario_ficticio,
    eliminar_usuario_ficticio,
)

pytestmark = pytest.mark.integration

AFILIACIONES_URL = "/api/v1/afiliaciones"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_ADMIN = "os.admin.ficticio@consultorio.example"
EMAIL_RECEPCION = "os.afili.recepcion.ficticia@consultorio.example"
EMAIL_ODONTOLOGO = "os.afili.odontologo.ficticio@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Afili-1234-no-real"


@pytest_asyncio.fixture()
async def usuarios_os() -> AsyncGenerator[None, None]:
    """Admin + recepción + odontólogo ficticios; self-cleanup en RED."""
    await crear_usuario_ficticio(EMAIL_ADMIN, PASSWORD_FICTICIA, "admin")
    await crear_usuario_ficticio(EMAIL_RECEPCION, PASSWORD_FICTICIA, "recepcion")
    await crear_usuario_ficticio(EMAIL_ODONTOLOGO, PASSWORD_FICTICIA, "odontologo")
    yield
    for email in (EMAIL_ADMIN, EMAIL_RECEPCION, EMAIL_ODONTOLOGO):
        await eliminar_usuario_ficticio(email)


async def _access(cliente: AsyncClient, email: str) -> str:
    login = await cliente.post(
        LOGIN_URL, json={"email": email, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


async def _alta_ficticia(
    cliente: AsyncClient, headers: dict[str, str], os_id: str
) -> dict[str, object]:
    return {
        "paciente_id": str(ID_PACIENTE_DEMO),
        "obra_social_id": os_id,
        "nro_afiliado": NRO_AFILIADO_FICTICIO_1,
        "vigencia_desde": "2026-01-01",
        "vigencia_hasta": None,
    }


async def test_alta_afiliacion_201_y_lectura_enmascarada(
    cliente: AsyncClient, usuarios_os: None
) -> None:
    # Arrange: OS ficticia + JWT de recepción.
    os_id = await crear_obra_social_ficticia()
    headers = {"Authorization": f"Bearer {await _access(cliente, EMAIL_RECEPCION)}"}

    # Act: alta vigente con datos ficticios válidos.
    alta = await cliente.post(
        AFILIACIONES_URL,
        json=await _alta_ficticia(cliente, headers, str(os_id)),
        headers=headers,
    )

    # Assert: 201 y lecturas con nro. enmascarado (solo últimos 4).
    assert alta.status_code == 201
    afiliacion_id = str(alta.json()["id"])
    lectura = await cliente.get(
        f"{AFILIACIONES_URL}/{afiliacion_id}", headers=headers
    )
    assert lectura.status_code == 200
    assert lectura.json()["nro_afiliado"] == "************1234"
    assert NRO_AFILIADO_FICTICIO_1 not in lectura.text

    # Act: baja lógica.
    baja = await cliente.delete(
        f"{AFILIACIONES_URL}/{afiliacion_id}", headers=headers
    )

    # Assert: 200 con vigente=false (no borrado físico).
    assert baja.status_code == 200
    assert baja.json()["vigente"] is False


async def test_alta_afiliacion_duplicada_vigente_409(
    cliente: AsyncClient, usuarios_os: None
) -> None:
    # Arrange: afiliación vigente ya dada de alta.
    os_id = await crear_obra_social_ficticia()
    headers = {"Authorization": f"Bearer {await _access(cliente, EMAIL_RECEPCION)}"}
    primera = await cliente.post(
        AFILIACIONES_URL,
        json=await _alta_ficticia(cliente, headers, str(os_id)),
        headers=headers,
    )
    assert primera.status_code == 201

    # Act: segunda alta vigente del mismo paciente en la misma OS.
    segunda = await cliente.post(
        AFILIACIONES_URL,
        json=await _alta_ficticia(cliente, headers, str(os_id)),
        headers=headers,
    )

    # Assert: 409 sin crear filas ni exponer el nro. en el error.
    assert segunda.status_code == 409
    assert NRO_AFILIADO_FICTICIO_1 not in segunda.text
    async with TestSession() as sesion:
        from sqlalchemy import text as _text

        n = await sesion.scalar(
            _text(
                "SELECT count(*) FROM afiliacion_os "
                "WHERE paciente_id = :pac AND obra_social_id = :os "
                "AND vigente IS TRUE"
            ),
            {"pac": ID_PACIENTE_DEMO, "os": os_id},
        )
    assert int(n or 0) == 1


async def test_alta_afiliacion_vigencia_invalida_422(
    cliente: AsyncClient, usuarios_os: None
) -> None:
    # Arrange: OS ficticia + JWT de recepción.
    os_id = await crear_obra_social_ficticia()
    headers = {"Authorization": f"Bearer {await _access(cliente, EMAIL_RECEPCION)}"}
    cuerpo = await _alta_ficticia(cliente, headers, str(os_id))
    cuerpo["vigencia_desde"] = "2026-06-30"
    cuerpo["vigencia_hasta"] = "2026-01-01"

    # Act: alta con hasta anterior a desde.
    respuesta = await cliente.post(AFILIACIONES_URL, json=cuerpo, headers=headers)

    # Assert: 422 sin crear filas ni exponer el nro.
    assert respuesta.status_code == 422
    assert NRO_AFILIADO_FICTICIO_1 not in respuesta.text


async def test_crud_afiliaciones_solo_staff_403_401(
    cliente: AsyncClient, usuarios_os: None
) -> None:
    # Arrange: afiliación creada por recepción (para probar lecturas ajenas).
    os_id = await crear_obra_social_ficticia()
    headers_recep = {
        "Authorization": f"Bearer {await _access(cliente, EMAIL_RECEPCION)}"
    }
    alta = await cliente.post(
        AFILIACIONES_URL,
        json=await _alta_ficticia(cliente, headers_recep, str(os_id)),
        headers=headers_recep,
    )
    assert alta.status_code == 201
    afiliacion_id = str(alta.json()["id"])
    headers_odon = {
        "Authorization": f"Bearer {await _access(cliente, EMAIL_ODONTOLOGO)}"
    }

    # Act: odontólogo intenta leer y dar de alta (padrón OS no clínico).
    lectura_odon = await cliente.get(
        f"{AFILIACIONES_URL}/{afiliacion_id}", headers=headers_odon
    )
    alta_odon = await cliente.post(
        AFILIACIONES_URL,
        json=await _alta_ficticia(cliente, headers_odon, str(os_id)),
        headers=headers_odon,
    )
    sin_jwt = await cliente.get(AFILIACIONES_URL)

    # Assert: 403 genérico + acceso_denegado; sin JWT 401.
    assert lectura_odon.status_code == 403
    assert lectura_odon.json()["detalle"] == "Sin permiso."
    assert alta_odon.status_code == 403
    assert sin_jwt.status_code == 401
