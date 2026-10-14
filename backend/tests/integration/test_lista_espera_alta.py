"""C-14 task 1.1 RED: alta/consulta/baja de lista de espera (R5).

Contrato que la parte 2 (GREEN) debe cumplir (`agenda/lista-espera`):
- `POST /api/v1/lista-espera` (JWT solo `admin|recepcion`) crea
  `{paciente_id, prestacion_id, profesional_id?, ventana_desde,
  ventana_hasta}` en estado `activa` (`201`) + evento
  `lista_espera_creada` sin PII en el `diff`.
- Ventana inválida (`desde >= hasta`) o pasada → `422` sin crear filas.
- `GET /api/v1/lista-espera?estado` (staff + `odontologo` lectura).
- `DELETE /api/v1/lista-espera/:id` (baja manual → `expirada`, sus
  ofertas `pendiente` → `expirada`, sin mensajes).
- Sin JWT → `401`; odontólogo en escritura → `403` + `acceso_denegado`;
  id inexistente → `404` idéntico sin filtrar datos (R6).

Estado parte 1: el router NO existe → FALLAN en rojo (`404`).
Todo dato sintético (R0); type hints siempre (R1); AAA.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import (
    ID_PRESTACION_LIMPIEZA_45,
    ID_PROFESIONAL_A,
    ID_PACIENTE_DEMO,
    LISTA_ESPERA_URL,
    NRO_AFILIADO_FICTICIO_1,
    TestSession,
    crear_usuario_ficticio,
    eliminar_usuario_ficticio,
)

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")

LOGIN_URL = "/api/v1/auth/login"

EMAIL_ADMIN = "espera.alta.admin.ficticio@consultorio.example"
EMAIL_RECEPCION = "espera.alta.recepcion.ficticia@consultorio.example"
EMAIL_ODONTOLOGO = "espera.alta.odontologo.ficticio@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Espera-Alta-1234-no-real"

VENTANA_DESDE = datetime(2026, 11, 10, 9, 0, tzinfo=BA)
VENTANA_HASTA = datetime(2026, 11, 14, 18, 0, tzinfo=BA)


@pytest_asyncio.fixture()
async def usuarios_espera() -> AsyncGenerator[None, None]:
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


def _alta(
    *,
    desde: datetime = VENTANA_DESDE,
    hasta: datetime = VENTANA_HASTA,
    paciente_id: uuid.UUID = ID_PACIENTE_DEMO,
) -> dict[str, object]:
    return {
        "paciente_id": str(paciente_id),
        "prestacion_id": str(ID_PRESTACION_LIMPIEZA_45),
        "profesional_id": str(ID_PROFESIONAL_A),
        "ventana_desde": desde.isoformat(),
        "ventana_hasta": hasta.isoformat(),
    }


async def _contar_espera() -> int:
    async with TestSession() as sesion:
        return int(
            await sesion.scalar(text("SELECT count(*) FROM lista_espera")) or 0
        )


async def _eventos_creada() -> list[str]:
    async with TestSession() as sesion:
        filas = (
            await sesion.execute(
                text(
                    "SELECT diff::text FROM auditoria_log "
                    "WHERE accion = 'lista_espera_creada'"
                )
            )
        ).scalars().all()
        return [str(f) for f in filas]


async def test_alta_lista_espera_201_activa(
    cliente: AsyncClient, usuarios_espera: None
) -> None:
    # Arrange: JWT de recepción + ventana futura válida.
    headers = {"Authorization": f"Bearer {await _access(cliente, EMAIL_RECEPCION)}"}

    # Act: alta con prestación y ventana futura válida.
    respuesta = await cliente.post(LISTA_ESPERA_URL, json=_alta(), headers=headers)

    # Assert: 201 en `activa` + evento auditado sin PII.
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "activa"
    assert cuerpo["paciente_id"] == str(ID_PACIENTE_DEMO)
    eventos = await _eventos_creada()
    assert len(eventos) == 1
    assert NRO_AFILIADO_FICTICIO_1 not in eventos[0]


async def test_alta_ventana_invalida_422(
    cliente: AsyncClient, usuarios_espera: None
) -> None:
    # Arrange: JWT de recepción.
    headers = {"Authorization": f"Bearer {await _access(cliente, EMAIL_RECEPCION)}"}

    # Act: alta con `desde >= hasta`.
    respuesta = await cliente.post(
        LISTA_ESPERA_URL,
        json=_alta(desde=VENTANA_HASTA, hasta=VENTANA_HASTA),
        headers=headers,
    )

    # Assert: 422 sin crear filas.
    assert respuesta.status_code == 422
    assert await _contar_espera() == 0


async def test_alta_ventana_pasada_422(
    cliente: AsyncClient, usuarios_espera: None
) -> None:
    # Arrange: JWT de recepción + ventana ya terminada (sintética, R0).
    headers = {"Authorization": f"Bearer {await _access(cliente, EMAIL_RECEPCION)}"}
    pasada_desde = datetime(2026, 1, 5, 9, 0, tzinfo=BA)
    pasada_hasta = datetime(2026, 1, 6, 18, 0, tzinfo=BA)

    # Act: alta con ventana en el pasado.
    respuesta = await cliente.post(
        LISTA_ESPERA_URL,
        json=_alta(desde=pasada_desde, hasta=pasada_hasta),
        headers=headers,
    )

    # Assert: 422 sin crear filas ni eventos.
    assert respuesta.status_code == 422
    assert await _contar_espera() == 0
    assert await _eventos_creada() == []


async def test_baja_manual_expira_sin_oferta(
    cliente: AsyncClient, usuarios_espera: None
) -> None:
    # Arrange: entrada dada de alta por recepción.
    headers = {"Authorization": f"Bearer {await _access(cliente, EMAIL_RECEPCION)}"}
    alta = await cliente.post(LISTA_ESPERA_URL, json=_alta(), headers=headers)
    assert alta.status_code == 201
    espera_id = str(alta.json()["id"])

    # Act: baja manual.
    baja = await cliente.delete(f"{LISTA_ESPERA_URL}/{espera_id}", headers=headers)

    # Assert: 200 `expirada`, sin ofertas ni mensajes asociados.
    assert baja.status_code == 200
    assert baja.json()["estado"] == "expirada"
    async with TestSession() as sesion:
        n_ofertas = await sesion.scalar(
            text("SELECT count(*) FROM oferta_espera WHERE lista_espera_id = :eid"),
            {"eid": uuid.UUID(espera_id)},
        )
        assert int(n_ofertas or 0) == 0


async def test_lista_espera_rbac_401_403_y_odontologo_lectura(
    cliente: AsyncClient, usuarios_espera: None
) -> None:
    # Arrange: entrada creada por recepción (para lecturas ajenas).
    headers_recep = {
        "Authorization": f"Bearer {await _access(cliente, EMAIL_RECEPCION)}"
    }
    alta = await cliente.post(
        LISTA_ESPERA_URL, json=_alta(), headers=headers_recep
    )
    assert alta.status_code == 201
    espera_id = str(alta.json()["id"])
    headers_odon = {
        "Authorization": f"Bearer {await _access(cliente, EMAIL_ODONTOLOGO)}"
    }

    # Act: odontólogo escribe, lee y consulta; anónimo consulta.
    alta_odon = await cliente.post(
        LISTA_ESPERA_URL, json=_alta(), headers=headers_odon
    )
    baja_odon = await cliente.delete(
        f"{LISTA_ESPERA_URL}/{espera_id}", headers=headers_odon
    )
    lectura_odon = await cliente.get(
        f"{LISTA_ESPERA_URL}/{espera_id}", headers=headers_odon
    )
    listado_odon = await cliente.get(
        LISTA_ESPERA_URL, params={"estado": "activa"}, headers=headers_odon
    )
    sin_jwt = await cliente.get(LISTA_ESPERA_URL)

    # Assert: escritura odontólogo 403 + acceso_denegado; lectura 200;
    # sin JWT 401.
    assert alta_odon.status_code == 403
    assert alta_odon.json()["detalle"] == "Sin permiso."
    assert baja_odon.status_code == 403
    assert lectura_odon.status_code == 200
    assert listado_odon.status_code == 200
    assert sin_jwt.status_code == 401


async def test_lista_espera_id_inexistente_404_sin_fuga(
    cliente: AsyncClient, usuarios_espera: None
) -> None:
    # Arrange: JWT de recepción + id al azar (sintético, R0).
    headers = {"Authorization": f"Bearer {await _access(cliente, EMAIL_RECEPCION)}"}
    inexistente = str(uuid.uuid4())

    # Act: leer y dar de baja un id que no existe.
    lectura = await cliente.get(f"{LISTA_ESPERA_URL}/{inexistente}", headers=headers)
    baja = await cliente.delete(
        f"{LISTA_ESPERA_URL}/{inexistente}", headers=headers
    )

    # Assert: 404 idéntico sin filtrar datos de otros en espera.
    assert lectura.status_code == 404
    assert baja.status_code == 404
    assert str(ID_PACIENTE_DEMO) not in lectura.text
