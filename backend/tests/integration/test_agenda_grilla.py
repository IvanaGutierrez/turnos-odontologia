"""C-04 task 1.1 RED: grilla día/semana de recepción.

Contrato que la parte 2 (GREEN) debe cumplir (`agenda/agenda-recepcion`):
- `GET /api/v1/agenda?vista=dia&profesional_id&sillon_id&desde` → `200`
  con turnos activos del día filtrados y ordenados por `inicio`; cada item
  `{id, inicio, fin, estado, profesional_id, sillon_id, prestacion_id,
  sobreturno}` + nombre de paciente según rol; jamás DNI/tel/HC.
- `GET /api/v1/agenda?vista=semana&desde&hasta` → `200` agregado por
  profesional+sillón en una query (sin N+1); ventana acotada por
  `AGENDA_SEMANA_MAX_DIAS` (default 7): exceso o `desde >= hasta` → `422`.
- Sin token → `401`; rol sin permiso `turnos` → `403` + `acceso_denegado`.

Estado parte 1: el endpoint NO existe → estos tests FALLAN en rojo (404).
Todo dato sintético (R0); type hints siempre (R1).
"""

import logging
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.security import hashear_password
from app.models.auditoria import AuditoriaLog
from app.models.entidades import Profesional, Usuario
from tests.conftest import (
    DNI_FICTICIO,
    ID_PRESTACION_CONSULTA_30,
    ID_PROFESIONAL_A,
    ID_PROFESIONAL_B,
    ID_SILLON_S1,
    ID_SILLON_S2,
    TEL_FICTICIO,
    TestSession,
    inicio_demo,
    payload_paciente_ficticio,
    payload_turno,
)

pytestmark = pytest.mark.integration

AGENDA_URL = "/api/v1/agenda"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_RECEPCION = "recepcion.grilla.ficticia@consultorio.example"
EMAIL_SIN_PERMISO = "pasante.ficticio@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Grilla-1234-no-real"

DESDE_DIA = "2026-11-03T00:00:00-03:00"
DESDE_SEMANA = "2026-11-03T00:00:00-03:00"
HASTA_SEMANA = "2026-11-10T00:00:00-03:00"

CLAVES_ITEM = {
    "id",
    "inicio",
    "fin",
    "estado",
    "profesional_id",
    "sillon_id",
    "prestacion_id",
    "sobreturno",
}


@pytest_asyncio.fixture()
async def usuarios_grilla() -> None:
    """Recepción + rol sin permiso `turnos`; self-cleanup (R0)."""
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
                email=EMAIL_SIN_PERMISO,
                password_hash=hashear_password(PASSWORD_FICTICIA),
                rol="pasante",
                activo=True,
            )
        )
        await sesion.commit()
    yield
    async with TestSession() as sesion:
        await sesion.execute(
            delete(Usuario).where(
                Usuario.email.in_([EMAIL_RECEPCION, EMAIL_SIN_PERMISO])
            )
        )
        await sesion.commit()


async def _access_para(cliente: AsyncClient, email: str) -> str:
    """Arrange: login y access del usuario pedido."""
    login = await cliente.post(
        LOGIN_URL, json={"email": email, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert isinstance(token, str) and token
    return token


async def _crear_turno_recepcion(
    cliente: AsyncClient, access: str, payload: dict[str, object]
) -> dict[str, object]:
    """Arrange: alta por el núcleo C-01 (existe en GREEN C-01)."""
    respuesta = await cliente.post(
        "/api/v1/turnos",
        json=payload,
        headers={"Authorization": f"Bearer {access}"},
    )
    assert respuesta.status_code == 201
    datos = respuesta.json()
    assert isinstance(datos, dict)
    return datos


async def test_grilla_dia_por_profesional_filtra_y_ordena(
    cliente: AsyncClient, usuarios_grilla: None
) -> None:
    # Arrange: dos turnos de A ese día + uno de B (recepción autenticada).
    access = await _access_para(cliente, EMAIL_RECEPCION)
    auth = {"Authorization": f"Bearer {access}"}
    await _crear_turno_recepcion(cliente, access, payload_turno(inicio_demo(10, 0)))
    await _crear_turno_recepcion(cliente, access, payload_turno(inicio_demo(11, 0)))
    await _crear_turno_recepcion(
        cliente,
        access,
        payload_turno(
            inicio_demo(10, 0),
            profesional_id=ID_PROFESIONAL_B,
            sillon_id=ID_SILLON_S2,
            prestacion_id=ID_PRESTACION_CONSULTA_30,
        ),
    )

    # Act: grilla día filtrada por profesional A.
    respuesta = await cliente.get(
        AGENDA_URL,
        params={
            "vista": "dia",
            "profesional_id": str(ID_PROFESIONAL_A),
            "desde": DESDE_DIA,
        },
        headers=auth,
    )

    # Assert: 200 con exactamente los dos turnos de A ordenados por inicio.
    assert respuesta.status_code == 200
    items = respuesta.json()
    assert isinstance(items, list) and len(items) == 2
    assert CLAVES_ITEM.issubset(items[0].keys())
    assert [i["profesional_id"] for i in items] == [str(ID_PROFESIONAL_A)] * 2
    assert items[0]["inicio"] < items[1]["inicio"]


async def test_grilla_sin_token_401(cliente: AsyncClient) -> None:
    # Arrange: sin header de autorización (nada que limpiar).
    # Act: grilla día sin token.
    respuesta = await cliente.get(
        AGENDA_URL, params={"vista": "dia", "desde": DESDE_DIA}
    )

    # Assert: 401 sin ejecutar nada.
    assert respuesta.status_code == 401


async def test_grilla_rol_sin_permiso_403_y_audita(
    cliente: AsyncClient, usuarios_grilla: None
) -> None:
    # Arrange: access con rol fuera de la matriz (`pasante` no opera `turnos`).
    access = await _access_para(cliente, EMAIL_SIN_PERMISO)

    # Act: grilla día con rol no habilitado.
    respuesta = await cliente.get(
        AGENDA_URL,
        params={"vista": "dia", "desde": DESDE_DIA},
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 403 genérico + `acceso_denegado` auditado (RN-AU-03).
    assert respuesta.status_code == 403
    assert "turnos" not in respuesta.text.lower() or "permiso" in respuesta.text.lower()
    async with TestSession() as sesion:
        filas = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(AuditoriaLog.accion == "acceso_denegado")
                )
            )
            .scalars()
            .all()
        )
    assert len(filas) == 1
    assert filas[0].diff["recurso"] == "turnos"


async def test_grilla_semana_multisillon_agrega(
    cliente: AsyncClient, usuarios_grilla: None
) -> None:
    # Arrange: tercer profesional ficticio + turnos en dos sillones.
    access = await _access_para(cliente, EMAIL_RECEPCION)
    async with TestSession() as sesion:
        sesion.add(
            Profesional(
                id=uuid.UUID("88888888-8888-4888-8888-888888888888"),
                nombre="Profesional Ficticio C",
                matricula="DEMO-MAT-C-003",
                activo=True,
            )
        )
        await sesion.commit()
    try:
        await _crear_turno_recepcion(cliente, access, payload_turno(inicio_demo(10, 0)))
        await _crear_turno_recepcion(
            cliente,
            access,
            payload_turno(
                inicio_demo(10, 0).replace(day=4),
                profesional_id=ID_PROFESIONAL_B,
                sillon_id=ID_SILLON_S2,
                prestacion_id=ID_PRESTACION_CONSULTA_30,
            ),
        )

        # Act: grilla semana multisillón.
        respuesta = await cliente.get(
            AGENDA_URL,
            params={
                "vista": "semana",
                "desde": DESDE_SEMANA,
                "hasta": HASTA_SEMANA,
            },
            headers={"Authorization": f"Bearer {access}"},
        )

        # Assert: 200 con ambos sillones identificados, ordenados por inicio.
        assert respuesta.status_code == 200
        items = respuesta.json()
        assert isinstance(items, list) and len(items) == 2
        sillones = {i["sillon_id"] for i in items}
        assert sillones == {str(ID_SILLON_S1), str(ID_SILLON_S2)}
        assert items[0]["inicio"] <= items[1]["inicio"]
    finally:
        async with TestSession() as sesion:
            await sesion.execute(
                delete(Profesional).where(Profesional.matricula == "DEMO-MAT-C-003")
            )
            await sesion.commit()


async def test_grilla_semana_ventana_excesiva_422(
    cliente: AsyncClient, usuarios_grilla: None
) -> None:
    # Arrange: recepción autenticada (nada que sembrar).
    access = await _access_para(cliente, EMAIL_RECEPCION)
    auth = {"Authorization": f"Bearer {access}"}

    # Act: ventana de 8 días (> AGENDA_SEMANA_MAX_DIAS=7) y rango invertido.
    larga = await cliente.get(
        AGENDA_URL,
        params={
            "vista": "semana",
            "desde": DESDE_SEMANA,
            "hasta": "2026-11-11T00:00:00-03:00",
        },
        headers=auth,
    )
    invertida = await cliente.get(
        AGENDA_URL,
        params={
            "vista": "semana",
            "desde": HASTA_SEMANA,
            "hasta": DESDE_SEMANA,
        },
        headers=auth,
    )

    # Assert: 422 genérico sin revelar turnos ni horarios.
    assert larga.status_code == 422
    assert invertida.status_code == 422
    assert "turno" not in larga.text.lower()
    assert "10:00" not in larga.text and "10:00" not in invertida.text


async def test_grilla_no_filtra_pii_excedente(
    cliente: AsyncClient,
    usuarios_grilla: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: turno de paciente ficticia (PII 100 % sintética, R0).
    access = await _access_para(cliente, EMAIL_RECEPCION)
    nuevo = payload_turno(inicio_demo(10, 0))
    nuevo.pop("paciente_id", None)
    nuevo["paciente"] = payload_paciente_ficticio()
    creado = await _crear_turno_recepcion(cliente, access, nuevo)
    token = creado["token_publico"]

    # Act: grilla día capturando logs.
    with caplog.at_level(logging.INFO):
        respuesta = await cliente.get(
            AGENDA_URL,
            params={"vista": "dia", "desde": DESDE_DIA},
            headers={"Authorization": f"Bearer {access}"},
        )

    # Assert: 200 sin DNI/teléfono/HC/hashes/tokens en cuerpo ni logs.
    assert respuesta.status_code == 200
    cuerpo = respuesta.text
    assert DNI_FICTICIO not in cuerpo
    assert "5000-0001" not in cuerpo
    assert TEL_FICTICIO not in cuerpo
    assert "historia" not in cuerpo.lower()
    assert token not in cuerpo
    assert DNI_FICTICIO not in caplog.text
    assert token not in caplog.text
