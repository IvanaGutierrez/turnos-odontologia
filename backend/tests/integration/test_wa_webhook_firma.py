"""C-06 tasks 1.2+1.5 RED: webhook WhatsApp con firma siempre (R5+R6).

Contrato que la parte 2 (GREEN) debe cumplir (`POST /webhooks/whatsapp`,
fuera de `/api/v1`, sin JWT):
- `GET` valida `hub.verify_token == WHATSAPP_VERIFY_TOKEN` (suscripción
  Meta): token ok → `200` con el challenge; erróneo → `403`.
- `POST` exige `X-Hub-Signature-256 = HMAC-SHA256(WHATSAPP_WEBHOOK_SECRET,
  body)` con `compare_digest`: ausente/inválida/cuerpo alterado → `401`
  con cuerpo genérico, sin procesar, sin mutar agenda, sin auditar
  contenido y sin loguear PII.
- Firma válida → `200`, solo acusa recibo + audita (`wa_message_id`,
  `remitente_hash`, `timestamp`, `tipo`); el texto libre jamás se loguea.

Estado parte 1: el router NO existe → FALLAN en rojo (`404`).
Todo dato sintético (R0); el secreto de firma es un placeholder solo de
test (R7, jamás en archivos de app); teléfonos solo hasheados (R6);
type hints siempre (R1); jamás red real (R5).
"""

import hashlib
import hmac
import json
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from freezegun import freeze_time
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.security import hashear_password
from app.models.auditoria import AuditoriaLog
from app.models.entidades import Usuario
from tests.conftest import (
    TEL_WA_FICTICIO_2,
    TestSession,
    hash_destino,
    payload_turno,
)

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime(2026, 11, 4, 10, 0, tzinfo=BA)

WEBHOOK_URL = "/webhooks/whatsapp"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_STAFF = "wa.webhook.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Wa-Webhook-1234-no-real"

# Placeholders solo de test (R7): jamás secretos reales ni de app.
SECRETO_WEBHOOK_FICTICIO = "secreto-webhook-ficticio-no-real-32b-min"
TOKEN_VERIFICACION_FICTICIO = "token-verificacion-ficticio-no-real"
DESAFIO_FICTICIO = "desafio-ficticio-1234"
WA_MESSAGE_ID_FICTICIO = "wamid.ficticio-0001"


@pytest_asyncio.fixture()
async def staff() -> AsyncGenerator[None, None]:
    """Usuario recepción sintético (turno testigo para asserts de no-mutación)."""
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


def _cuerpo_inbound() -> bytes:
    """Payload entrante sintético (remitente solo como hash — R6)."""
    return json.dumps(
        {
            "wa_message_id": WA_MESSAGE_ID_FICTICIO,
            "remitente_hash": hash_destino(TEL_WA_FICTICIO_2),
            "timestamp": AHORA.isoformat(),
            "tipo": "texto",
        }
    ).encode("utf-8")


def _firma(cuerpo: bytes, secreto: str = SECRETO_WEBHOOK_FICTICIO) -> str:
    firma = hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    return f"sha256={firma}"


async def _auditorias_webhook() -> list[AuditoriaLog]:
    async with TestSession() as sesion:
        return list(
            (
                await sesion.execute(
                    select(AuditoriaLog).where(AuditoriaLog.entidad == "aviso_envio")
                )
            )
            .scalars()
            .all()
        )


async def test_verify_con_token_correcto_devuelve_challenge(
    cliente: AsyncClient,
) -> None:
    # Arrange: parámetros de suscripción Meta con el token ficticio esperado.
    # Act: GET de verificación con token correcto.
    respuesta = await cliente.get(
        WEBHOOK_URL,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": TOKEN_VERIFICACION_FICTICIO,
            "hub.challenge": DESAFIO_FICTICIO,
        },
    )

    # Assert: 200 con el challenge en texto plano.
    assert respuesta.status_code == 200
    assert DESAFIO_FICTICIO in respuesta.text


async def test_verify_con_token_erroneo_rechaza_sin_exponer(
    cliente: AsyncClient,
) -> None:
    # Arrange: token de verificación incorrecto (suscripción ajena).
    # Act: GET de verificación con token erróneo.
    respuesta = await cliente.get(
        WEBHOOK_URL,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "token-ajeno-ficticio-no-real",
            "hub.challenge": DESAFIO_FICTICIO,
        },
    )

    # Assert: 403 genérico, sin eco del challenge ni del secreto.
    assert respuesta.status_code == 403
    assert DESAFIO_FICTICIO not in respuesta.text
    assert SECRETO_WEBHOOK_FICTICIO not in respuesta.text


async def test_post_con_firma_valida_procesa_y_audita_sin_pii(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno testigo `reservado` + cuerpo firmado correctamente.
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_STAFF, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    creado = await cliente.post(
        TURNOS_URL,
        json=payload_turno(AHORA + timedelta(hours=49)),
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert creado.status_code == 201
    cuerpo = _cuerpo_inbound()

    # Act: POST con firma válida (reloj controlado).
    with freeze_time(AHORA):
        respuesta = await cliente.post(
            WEBHOOK_URL,
            content=cuerpo,
            headers={
                "X-Hub-Signature-256": _firma(cuerpo),
                "Content-Type": "application/json",
            },
        )

    # Assert: 200 idempotente + auditoría sin PII + agenda intacta.
    assert respuesta.status_code == 200
    filas = await _auditorias_webhook()
    assert len(filas) == 1
    assert WA_MESSAGE_ID_FICTICIO in str(filas[0].diff)
    assert TEL_WA_FICTICIO_2 not in str(filas[0].diff)
    assert SECRETO_WEBHOOK_FICTICIO not in str(filas[0].diff)


@pytest.mark.parametrize(
    "caso",
    ["sin_firma", "firma_invalida", "cuerpo_alterado"],
)
async def test_post_con_firma_ausente_invalida_o_alterada_401_sin_procesar(
    cliente: AsyncClient, staff: None, caso: str
) -> None:
    # Arrange: turno testigo + cuerpo base firmado (luego mutado según caso).
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_STAFF, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    creado = await cliente.post(
        TURNOS_URL,
        json=payload_turno(AHORA + timedelta(hours=50)),
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert creado.status_code == 201
    turno_id = str(creado.json()["id"])
    cuerpo = _cuerpo_inbound()
    if caso == "sin_firma":
        cabeceras: dict[str, str] = {"Content-Type": "application/json"}
    elif caso == "firma_invalida":
        cabeceras = {
            "X-Hub-Signature-256": _firma(cuerpo, "otro-secreto-ficticio-no-real"),
            "Content-Type": "application/json",
        }
    else:
        cuerpo = _cuerpo_inbound().replace(b"texto", b"otro-texto")
        cabeceras = {
            "X-Hub-Signature-256": _firma(_cuerpo_inbound()),
            "Content-Type": "application/json",
        }

    # Act: POST sin firma válida (reloj controlado).
    with freeze_time(AHORA):
        respuesta = await cliente.post(WEBHOOK_URL, content=cuerpo, headers=cabeceras)

    # Assert: 401 ciego — sin procesar, sin mutar, sin auditar contenido,
    # sin PII ni distinción de causas en el cuerpo.
    assert respuesta.status_code == 401
    assert TEL_WA_FICTICIO_2 not in respuesta.text
    assert SECRETO_WEBHOOK_FICTICIO not in respuesta.text
    assert WA_MESSAGE_ID_FICTICIO not in respuesta.text
    assert await _auditorias_webhook() == []
    async with TestSession() as sesion:
        from app.models.entidades import Turno

        turno = await sesion.get(Turno, turno_id)  # type: ignore[arg-type]
        assert turno is not None and turno.estado == "reservado"
