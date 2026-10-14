"""C-13 tasks 1.3 RED: privacidad + auditoría + versionado OS (R6, Ley 25.326).

Contratos que la parte 2 (GREEN) debe cumplir:
- Ningún response/diff/log de OS contiene nro. de afiliado, DNI,
  teléfono ni HCE (PII sintética marcada como sonda).
- Eventos `validacion_os_registrada|afiliacion_creada|
  afiliacion_actualizada` consultables por admin en
  `GET /api/v1/auditoria?entidad&entidad_id`; recepción → `403`.
- Cambio de versión de nomenclador NO altera validaciones congeladas
  (cada `ValidacionCobertura` guarda su `nomenclador_version`).

Estado parte 1: los routers NO existen → FALLAN en rojo (`404`).
Todo dato sintético (R0); type hints siempre (R1); AAA.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, text

from app.models.auditoria import AuditoriaLog
from tests.conftest import (
    DNI_OS_FICTICIO_1,
    ID_PACIENTE_DEMO,
    NRO_AFILIADO_FICTICIO_1,
    TEL_OS_FICTICIO,
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
AUDITORIA_URL = "/api/v1/auditoria"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_ADMIN = "os.priv.admin.ficticio@consultorio.example"
EMAIL_RECEPCION = "os.priv.recepcion.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-OS-Priv-1234-no-real"

SONDA_HCE = "HCE-FICTICIA-SONDA-sin-valor-clinico"


@pytest_asyncio.fixture()
async def usuarios_priv() -> AsyncGenerator[None, None]:
    """Admin + recepción ficticios; self-cleanup en RED."""
    await crear_usuario_ficticio(EMAIL_ADMIN, PASSWORD_FICTICIA, "admin")
    await crear_usuario_ficticio(EMAIL_RECEPCION, PASSWORD_FICTICIA, "recepcion")
    yield
    for email in (EMAIL_ADMIN, EMAIL_RECEPCION):
        await eliminar_usuario_ficticio(email)


async def _access(cliente: AsyncClient, email: str) -> str:
    login = await cliente.post(
        LOGIN_URL, json={"email": email, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


async def test_responses_diffs_y_logs_sin_pii(
    cliente: AsyncClient, usuarios_priv: None, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange: turno + afiliación ficticia; capturo logs del flujo OS.
    headers = {"Authorization": f"Bearer {await _access(cliente, EMAIL_RECEPCION)}"}
    with caplog.at_level(logging.INFO):
        creado = await cliente.post(
            TURNOS_URL, json=payload_turno(inicio_demo(10, 0)), headers=headers
        )
        assert creado.status_code == 201
        turno_id = str(creado.json()["id"])
        os_id = await crear_obra_social_ficticia()
        afiliacion_id = await crear_afiliacion_ficticia(
            paciente_id=ID_PACIENTE_DEMO, obra_social_id=os_id
        )

        # Act: alta duplicada (409), validar (200) e inexistentes (404).
        duplicada = await cliente.post(
            AFILIACIONES_URL,
            json={
                "paciente_id": str(ID_PACIENTE_DEMO),
                "obra_social_id": str(os_id),
                "nro_afiliado": NRO_AFILIADO_FICTICIO_1,
                "vigencia_desde": "2026-01-01",
            },
            headers=headers,
        )
        validada = await cliente.post(
            VALIDAR_URL,
            json={"turno_id": turno_id, "afiliacion_id": str(afiliacion_id)},
            headers=headers,
        )
        fantasma = await cliente.get(
            f"{AFILIACIONES_URL}/00000000-0000-4000-8000-000000000000",
            headers=headers,
        )
        cuerpos = duplicada.text + validada.text + fantasma.text

    # Assert: los flujos existen y jamás exponen PII (nro/DNI/tel/HCE).
    assert duplicada.status_code in (201, 409)
    assert validada.status_code == 200
    assert fantasma.status_code == 404
    for sonda in (NRO_AFILIADO_FICTICIO_1, DNI_OS_FICTICIO_1, TEL_OS_FICTICIO, SONDA_HCE):
        assert sonda not in cuerpos
        assert sonda not in caplog.text
    async with TestSession() as sesion:
        diffs = (
            await sesion.execute(
                select(AuditoriaLog.diff).where(
                    AuditoriaLog.entidad.in_(["validacion_cobertura", "afiliacion_os"])
                )
            )
        ).scalars().all()
    plano = " ".join(str(d) for d in diffs)
    for sonda in (NRO_AFILIADO_FICTICIO_1, DNI_OS_FICTICIO_1, TEL_OS_FICTICIO):
        assert sonda not in plano


async def test_eventos_os_auditados_consultables_por_admin(
    cliente: AsyncClient, usuarios_priv: None
) -> None:
    # Arrange: una validación + un alta ficticias (generan sus eventos).
    headers_recep = {
        "Authorization": f"Bearer {await _access(cliente, EMAIL_RECEPCION)}"
    }
    creado = await cliente.post(
        TURNOS_URL, json=payload_turno(inicio_demo(11, 0)), headers=headers_recep
    )
    assert creado.status_code == 201
    turno_id = str(creado.json()["id"])
    alta = await cliente.post(
        AFILIACIONES_URL,
        json={
            "paciente_id": str(ID_PACIENTE_DEMO),
            "obra_social_id": str(await crear_obra_social_ficticia()),
            "nro_afiliado": NRO_AFILIADO_FICTICIO_1,
            "vigencia_desde": "2026-01-01",
        },
        headers=headers_recep,
    )
    assert alta.status_code == 201
    afiliacion_id = str(alta.json()["id"])
    validada = await cliente.post(
        VALIDAR_URL,
        json={"turno_id": turno_id, "afiliacion_id": afiliacion_id},
        headers=headers_recep,
    )
    assert validada.status_code == 200
    validacion_id = str(validada.json()["validacion_id"])
    headers_admin = {"Authorization": f"Bearer {await _access(cliente, EMAIL_ADMIN)}"}

    # Act: admin filtra por entidad/entidad_id de cada evento OS.
    val = await cliente.get(
        AUDITORIA_URL,
        params={"entidad": "validacion_cobertura", "entidad_id": validacion_id},
        headers=headers_admin,
    )
    afi = await cliente.get(
        AUDITORIA_URL,
        params={"entidad": "afiliacion_os", "entidad_id": afiliacion_id},
        headers=headers_admin,
    )

    # Assert: cada filtro devuelve su evento sin PII en ningún diff.
    assert val.status_code == 200
    assert "validacion_os_registrada" in [f["accion"] for f in val.json()["items"]]
    assert afi.status_code == 200
    assert "afiliacion_creada" in [f["accion"] for f in afi.json()["items"]]
    for respuesta in (val, afi):
        assert NRO_AFILIADO_FICTICIO_1 not in respuesta.text
        assert DNI_OS_FICTICIO_1 not in respuesta.text


async def test_cambio_version_no_altera_validaciones_congeladas(
    cliente: AsyncClient, usuarios_priv: None
) -> None:
    # Arrange: validación registrada con nomenclador v1 ficticio.
    import json

    headers = {"Authorization": f"Bearer {await _access(cliente, EMAIL_RECEPCION)}"}
    creado = await cliente.post(
        TURNOS_URL, json=payload_turno(inicio_demo(12, 0)), headers=headers
    )
    assert creado.status_code == 201
    turno_id = str(creado.json()["id"])
    os_id = await crear_obra_social_ficticia()
    afiliacion_id = await crear_afiliacion_ficticia(
        paciente_id=ID_PACIENTE_DEMO, obra_social_id=os_id
    )
    primera = await cliente.post(
        VALIDAR_URL,
        json={"turno_id": turno_id, "afiliacion_id": str(afiliacion_id)},
        headers=headers,
    )
    assert primera.status_code == 200
    assert primera.json()["nomenclador_version"] == 1
    validacion_id = str(primera.json()["validacion_id"])

    # Act: la OS publica el nomenclador v2 ficticio + nueva validación.
    async with TestSession() as sesion:
        await sesion.execute(
            text(
                "UPDATE obra_social SET nomenclador_version = 2, "
                "nomenclador = CAST(:nom AS JSONB) WHERE id = :id"
            ),
            {
                "id": os_id,
                "nom": json.dumps({"limpieza": {"cubre": False}}),
            },
        )
        await sesion.commit()
    segundo_turno = await cliente.post(
        TURNOS_URL, json=payload_turno(inicio_demo(13, 0)), headers=headers
    )
    assert segundo_turno.status_code == 201
    segunda = await cliente.post(
        VALIDAR_URL,
        json={
            "turno_id": str(segundo_turno.json()["id"]),
            "afiliacion_id": str(afiliacion_id),
        },
        headers=headers,
    )

    # Assert: la previa conserva v1 y su resultado; la nueva usa v2.
    assert segunda.status_code == 200
    assert segunda.json()["nomenclador_version"] == 2
    async with TestSession() as sesion:
        fila = (
            await sesion.execute(
                text(
                    "SELECT nomenclador_version, resultado "
                    "FROM validacion_cobertura WHERE id = :id"
                ),
                {"id": validacion_id},
            )
        ).one()
    assert fila[0] == 1
    assert fila[1] == primera.json()["resultado"]
