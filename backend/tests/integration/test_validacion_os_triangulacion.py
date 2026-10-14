"""C-13 TRIANGULATE (GREEN): escenarios del spec sin test RED previo (R5).

Cubre ramas que los 12 tests parte-1 no ejercitan, con el mismo
contrato (`POST /obras-sociales/validar`, CRUD `/afiliaciones`):

- afiliación de otro paciente al validar → `422` genérico sin PII.
- OS inactiva al validar → `422` genérico sin PII.
- `PATCH /afiliaciones/:id` actualiza vigencia + audita sin PII.
- `GET /afiliaciones` devuelve el padrón con nros. enmascarados.

Todo dato sintético (R0: OS, afiliados y pacientes ficticios);
type hints siempre (R1); AAA.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import (
    ID_PACIENTE_DEMO,
    NRO_AFILIADO_FICTICIO_1,
    TURNOS_URL,
    TestSession,
    crear_afiliacion_ficticia,
    crear_obra_social_ficticia,
    crear_usuario_ficticio,
    eliminar_usuario_ficticio,
    inicio_demo,
    payload_turno,
)

pytestmark = pytest.mark.integration

VALIDAR_URL = "/api/v1/obras-sociales/validar"
AFILIACIONES_URL = "/api/v1/afiliaciones"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_RECEPCION = "os.tri.recepcion.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-OS-Tri-1234-no-real"


@pytest_asyncio.fixture()
async def recepcion_tri() -> AsyncGenerator[None, None]:
    """Recepción sintética; self-cleanup."""
    await crear_usuario_ficticio(EMAIL_RECEPCION, PASSWORD_FICTICIA, "recepcion")
    yield
    await eliminar_usuario_ficticio(EMAIL_RECEPCION)


async def _cabeceras(cliente: AsyncClient) -> dict[str, str]:
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_RECEPCION, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_validar_afiliacion_ajena_422_sin_pii(
    cliente: AsyncClient, recepcion_tri: None
) -> None:
    # Arrange: turno del paciente demo + afiliación vigente de OTRO ficticio.
    from tests.conftest import crear_paciente_hc

    headers = await _cabeceras(cliente)
    creado = await cliente.post(
        TURNOS_URL, json=payload_turno(inicio_demo(10, 0)), headers=headers
    )
    assert creado.status_code == 201
    otro = await crear_paciente_hc(
        nombre="Paciente Ficticio Ajeno",
        dni="88300199",
        telefono="+54 9 11 5000-0039",
        consentimiento=True,
    )
    os_id = await crear_obra_social_ficticia()
    afiliacion_ajena = await crear_afiliacion_ficticia(
        paciente_id=otro, obra_social_id=os_id
    )

    # Act: valida el turno demo con la afiliación ajena.
    respuesta = await cliente.post(
        VALIDAR_URL,
        json={
            "turno_id": str(creado.json()["id"]),
            "afiliacion_id": str(afiliacion_ajena),
        },
        headers=headers,
    )

    # Assert: 422 genérico sin exponer el nro. ni el DNI de nadie.
    assert respuesta.status_code == 422
    assert NRO_AFILIADO_FICTICIO_1 not in respuesta.text
    assert "88300199" not in respuesta.text


async def test_validar_os_inactiva_422_sin_pii(
    cliente: AsyncClient, recepcion_tri: None
) -> None:
    # Arrange: OS ficticia desactivada + afiliación vigente del demo.
    headers = await _cabeceras(cliente)
    creado = await cliente.post(
        TURNOS_URL, json=payload_turno(inicio_demo(11, 0)), headers=headers
    )
    assert creado.status_code == 201
    os_id = await crear_obra_social_ficticia()
    afiliacion_id = await crear_afiliacion_ficticia(
        paciente_id=ID_PACIENTE_DEMO, obra_social_id=os_id
    )
    async with TestSession() as sesion:
        await sesion.execute(
            text("UPDATE obra_social SET activa = FALSE WHERE id = :id"),
            {"id": os_id},
        )
        await sesion.commit()

    # Act: valida contra la OS inactiva.
    respuesta = await cliente.post(
        VALIDAR_URL,
        json={
            "turno_id": str(creado.json()["id"]),
            "afiliacion_id": str(afiliacion_id),
        },
        headers=headers,
    )

    # Assert: 422 genérico sin PII.
    assert respuesta.status_code == 422
    assert NRO_AFILIADO_FICTICIO_1 not in respuesta.text


async def test_patch_afiliacion_actualiza_vigencia_200(
    cliente: AsyncClient, recepcion_tri: None
) -> None:
    # Arrange: alta vigente por API.
    headers = await _cabeceras(cliente)
    alta = await cliente.post(
        AFILIACIONES_URL,
        json={
            "paciente_id": str(ID_PACIENTE_DEMO),
            "obra_social_id": str(await crear_obra_social_ficticia()),
            "nro_afiliado": NRO_AFILIADO_FICTICIO_1,
            "vigencia_desde": "2026-01-01",
        },
        headers=headers,
    )
    assert alta.status_code == 201
    afiliacion_id = str(alta.json()["id"])

    # Act: extiende la vigencia.
    parche = await cliente.patch(
        f"{AFILIACIONES_URL}/{afiliacion_id}",
        json={"vigencia_hasta": "2026-12-31"},
        headers=headers,
    )

    # Assert: 200 con la vigencia nueva y el nro. aún enmascarado.
    assert parche.status_code == 200
    cuerpo = parche.json()
    assert cuerpo["vigencia_hasta"] == "2026-12-31"
    assert cuerpo["vigente"] is True
    assert cuerpo["nro_afiliado"] == "************1234"
    assert NRO_AFILIADO_FICTICIO_1 not in parche.text


async def test_list_afiliaciones_enmascara_nros_200(
    cliente: AsyncClient, recepcion_tri: None
) -> None:
    # Arrange: un alta vigente por API.
    headers = await _cabeceras(cliente)
    alta = await cliente.post(
        AFILIACIONES_URL,
        json={
            "paciente_id": str(ID_PACIENTE_DEMO),
            "obra_social_id": str(await crear_obra_social_ficticia()),
            "nro_afiliado": NRO_AFILIADO_FICTICIO_1,
            "vigencia_desde": "2026-01-01",
        },
        headers=headers,
    )
    assert alta.status_code == 201

    # Act: lee el padrón.
    listado = await cliente.get(AFILIACIONES_URL, headers=headers)

    # Assert: 200 y ningún nro. en claro en toda la lista.
    assert listado.status_code == 200
    assert len(listado.json()) >= 1
    assert NRO_AFILIADO_FICTICIO_1 not in listado.text
    for fila in listado.json():
        assert fila["nro_afiliado"].endswith("1234")
        assert fila["nro_afiliado"] != NRO_AFILIADO_FICTICIO_1
