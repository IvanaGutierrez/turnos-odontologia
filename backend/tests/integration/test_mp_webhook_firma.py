"""C-08 tasks 1.2+1.5 RED: webhook MP con firma siempre (R5+R6).

Contrato que la parte 2 (GREEN) debe cumplir
(`POST /webhooks/mercadopago`, fuera de `/api/v1`, sin JWT):
- Exige `x-signature: ts=...,v1=...` con
  `v1 = HMAC-SHA256(MP_WEBHOOK_SECRET, "id:{data.id};request-id:{x-request-id};ts:{ts};")`
  comparado con `compare_digest` (el secreto solo vive en env — R7).
- Ausente/inválida/cuerpo alterado/`x-request-id` distinto → `401`
  genérico, sin procesar, sin mutar pagos/turnos, sin auditar contenido
  y sin PII del pagador ni tokens en logs/responses (R6).
- Tras verificar, el estado se confirma contra MP (Fake en tests), no
  solo desde el cuerpo (ver `test_mp_acreditacion.py`).

Estado parte 1: el router NO existe → FALLAN en rojo (`404`).
Todo dato sintético (R0); type hints siempre (R1).
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

import pytest
import pytest_asyncio
from app.core.security import hashear_password
from app.models.entidades import Turno, Usuario
from httpx import AsyncClient
from sqlalchemy import delete, text

from tests.conftest import (
    PAGADOR_DNI_FICTICIO,
    PAGADOR_EMAIL_FICTICIO,
    PAGADOR_TEL_FICTICIO,
    SECRETO_MP_FICTICIO_POR_DEFECTO,
    TestSession,
    cuerpo_aviso_mp,
    firmar_aviso_mp,
    inicio_demo,
    payload_turno,
    secreto_mp_prueba,
)

pytestmark = pytest.mark.integration

WEBHOOK_URL = "/webhooks/mercadopago"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_STAFF = "mp.webhook.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Mp-Webhook-1234-no-real"

MP_PAYMENT_FICTICIO = "pay-ficticio-0001"
REQUEST_ID_FICTICIO = "req-ficticio-0001"
TS_FICTICIO = "1700000000"


@pytest_asyncio.fixture()
async def staff() -> AsyncGenerator[None, None]:
    """Usuario recepción sintético (turno testigo para no-mutación)."""
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


async def _turno_testigo(cliente: AsyncClient, inicio: datetime) -> dict[str, object]:
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_STAFF, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    creado = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio),
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert creado.status_code == 201
    return dict(creado.json())


async def _contar_pagos() -> int:
    async with TestSession() as sesion:
        return int(await sesion.scalar(text("SELECT count(*) FROM pago")) or 0)


async def _auditorias_pago() -> int:
    """Eventos `pago_*` (el 401 jamás audita contenido del aviso)."""
    async with TestSession() as sesion:
        return int(
            await sesion.scalar(
                text("SELECT count(*) FROM auditoria_log WHERE accion LIKE 'pago_%'")
            )
            or 0
        )


def _cabeceras_validas(cuerpo: bytes, secreto: str) -> dict[str, str]:
    import json

    data_id = str(json.loads(cuerpo)["data"]["id"])
    return {
        "x-signature": firmar_aviso_mp(
            secreto=secreto,
            mp_payment_id=data_id,
            request_id=REQUEST_ID_FICTICIO,
            ts=TS_FICTICIO,
        ),
        "x-request-id": REQUEST_ID_FICTICIO,
        "Content-Type": "application/json",
    }


@pytest.mark.parametrize(
    "caso",
    ["sin_firma", "firma_invalida", "cuerpo_alterado", "request_id_distinto"],
)
async def test_firma_ausente_invalida_alterada_o_request_id_distinto_401_sin_procesar(
    cliente: AsyncClient, staff: None, caso: str
) -> None:
    # Arrange: turno testigo + aviso firmado (luego mutado según caso).
    testigo = await _turno_testigo(cliente, inicio_demo(10, 0).replace(day=7))
    secreto = secreto_mp_prueba()
    cuerpo = cuerpo_aviso_mp(MP_PAYMENT_FICTICIO)
    import json

    crudo = json.dumps(cuerpo).encode("utf-8")
    pagos_antes = await _contar_pagos()
    auditorias_antes = await _auditorias_pago()
    if caso == "sin_firma":
        cabeceras: dict[str, str] = {
            "x-request-id": REQUEST_ID_FICTICIO,
            "Content-Type": "application/json",
        }
    elif caso == "firma_invalida":
        cabeceras = {
            "x-signature": firmar_aviso_mp(
                secreto="otro-secreto-ficticio-no-real",
                mp_payment_id=MP_PAYMENT_FICTICIO,
                request_id=REQUEST_ID_FICTICIO,
                ts=TS_FICTICIO,
            ),
            "x-request-id": REQUEST_ID_FICTICIO,
            "Content-Type": "application/json",
        }
    elif caso == "cuerpo_alterado":
        crudo = json.dumps(cuerpo_aviso_mp("pay-ficticio-otro")).encode("utf-8")
        cabeceras = _cabeceras_validas(
            json.dumps(cuerpo).encode("utf-8"), secreto
        )
        cabeceras = {**cabeceras, "Content-Type": "application/json"}
    else:
        cabeceras = _cabeceras_validas(crudo, secreto)
        cabeceras["x-request-id"] = "req-distinto-ficticio"

    # Act: POST sin firma válida.
    respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

    # Assert: 401 ciego — sin mutar, sin auditar, sin PII ni tokens.
    assert respuesta.status_code == 401
    assert PAGADOR_EMAIL_FICTICIO not in respuesta.text
    assert PAGADOR_TEL_FICTICIO not in respuesta.text
    assert PAGADOR_DNI_FICTICIO not in respuesta.text
    assert secreto not in respuesta.text
    assert SECRETO_MP_FICTICIO_POR_DEFECTO not in respuesta.text
    assert MP_PAYMENT_FICTICIO not in respuesta.text
    assert await _contar_pagos() == pagos_antes
    assert await _auditorias_pago() == auditorias_antes
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, uuid.UUID(str(testigo["id"])))
        assert turno is not None and turno.estado == "reservado"
