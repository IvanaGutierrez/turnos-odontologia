"""C-06 tasks 1.3+1.5 RED: reintentos con backoff e idempotencia (R5).

Contrato que la parte 2 (GREEN) debe cumplir (cola `wa:envios` +
`workers/envios.py`, design decisiones 2–3):
- Transporte 5xx×2 luego ok para el mismo `(turno_id, tipo_aviso)` →
  UN único envío observable (`enviado` una vez, `intentos=3`), con
  `proveedor_msg_id` durable; los 4xx no se reintentan.
- Doble encolado concurrente del mismo `(turno_id, tipo)` → un solo
  envío (deduplicación `SET NX` + `UNIQUE` durable).
- Webhook duplicado con el mismo `wa_message_id` → `200` idempotente
  sin duplicar el envío ni la auditoría.

Estado parte 1: no hay workers/scheduler/webhook → FALLAN en rojo.
El `FakeWhatsAppTransport` (inyectado en tests, jamás red real) modela
los fallos programables; la parte 2 lo cablea al worker vía
`WA_TRANSPORT=fake`. Todo dato sintético (R0); teléfonos solo hasheados
(R6); type hints siempre (R1).
"""

import asyncio
import hashlib
import hmac
import json
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from freezegun import freeze_time
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.security import hashear_password
from app.models.aviso_envio import AvisoEnvio
from app.models.entidades import Usuario
from app.services.avisos import encolar_aviso
from app.workers.envios import drenar_pendientes
from tests.conftest import (
    TEL_WA_FICTICIO_1,
    FakeWaError,  # noqa: F401 (contrato del Fake: la parte 2 lo drena)
    FakeWhatsAppTransport,
    TestSession,
    hash_destino,
    payload_turno,
)

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime(2026, 11, 4, 10, 0, tzinfo=BA)

WEBHOOK_URL = "/webhooks/whatsapp"
AUTOGESTION_URL = "/api/v1/turnos/publicos"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_STAFF = "wa.reintentos.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Wa-Reintentos-1234-no-real"

SECRETO_WEBHOOK_FICTICIO = "secreto-webhook-ficticio-no-real-32b-min"


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


async def _confirmado(cliente: AsyncClient, inicio: datetime) -> dict[str, object]:
    """Arrange: turno `confirmado` vía núcleo C-01 + autogestión C-05."""
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
    with freeze_time(AHORA):
        confirma = await cliente.post(
            f"{AUTOGESTION_URL}/{creado.json()['token_publico']}/confirmar"
        )
    assert confirma.status_code == 200
    assert confirma.json()["estado"] == "confirmado"
    return dict(creado.json())


async def _avisos(turno_id: str, tipo: str) -> list[AvisoEnvio]:
    async with TestSession() as sesion:
        return list(
            (
                await sesion.execute(
                    select(AvisoEnvio).where(
                        AvisoEnvio.turno_id == uuid.UUID(turno_id),
                        AvisoEnvio.tipo_aviso == tipo,
                    )
                )
            )
            .scalars()
            .all()
        )


async def test_reintento_tras_5xx_envia_una_sola_vez_con_intentos_3(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno `confirmado` + Fake que falla 5xx×2 y luego responde ok.
    creado = await _confirmado(cliente, AHORA + timedelta(hours=49))
    turno_id = str(creado["id"])
    fake = FakeWhatsAppTransport(fallos=["5xx", "5xx"])

    # Act: el worker drena con el Fake inyectado (dos reintentos, al
    # tercero entrega); el Fake modela 5xx×2→ok, jamás red real (R5).
    async def _drenar() -> None:
        async with TestSession() as sesion:
            await drenar_pendientes(sesion, fake)

    with freeze_time(AHORA):
        await _drenar()
        await _drenar()
        await _drenar()
        proveedor_id = fake.llamadas[-1]["proveedor_msg_id"] if fake.llamadas else ""

    # Assert: el worker (parte 2) deja UN `enviado` con `intentos=3` y el
    # `proveedor_msg_id` durable del tercer intento — sin duplicar.
    assert proveedor_id.startswith("wamid.ficticio-")
    filas = await _avisos(turno_id, "confirmacion")
    assert len(filas) == 1
    assert filas[0].estado == "enviado"
    assert filas[0].intentos == 3
    assert filas[0].proveedor_msg_id == proveedor_id


async def test_doble_encolado_concurrente_un_solo_envio(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno `reservado` (sin confirmar: el scheduler aún no
    # programó nada para aislar la barrera de deduplicación).
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
    turno_id = uuid.UUID(str(creado.json()["id"]))
    fake = FakeWhatsAppTransport()

    # Act: doble encolado concurrente del mismo `(turno_id, tipo)` por el
    # scheduler — el `UNIQUE` durable deja pasar solo uno (barrera GREEN).
    async def _encolar() -> bool:
        async with TestSession() as sesion:
            creado_ok = await encolar_aviso(
                sesion,
                turno_id=turno_id,
                tipo_aviso="confirmacion",
                programado_para=AHORA,
                destino_hash=hash_destino(TEL_WA_FICTICIO_1),
                redis=None,
            )
            await sesion.commit()
            return creado_ok

    with freeze_time(AHORA):
        resultados = await asyncio.gather(_encolar(), _encolar())

    # Assert: UNA sola fila durable y UN solo envío al proveedor.
    assert sorted(resultados) == [False, True]
    filas = await _avisos(str(turno_id), "confirmacion")
    assert len(filas) == 1
    with freeze_time(AHORA):
        async with TestSession() as sesion:
            await drenar_pendientes(sesion, fake)
        proveedor_id = fake.llamadas[0]["proveedor_msg_id"]
    assert len(fake.llamadas) == 1
    assert proveedor_id.startswith("wamid.ficticio-")
    # Assert: el worker reclama la fila y la deja `enviado`.
    filas = await _avisos(str(turno_id), "confirmacion")
    assert filas[0].estado == "enviado"
    assert filas[0].proveedor_msg_id == proveedor_id


async def test_webhook_duplicado_mismo_wa_message_id_200_sin_duplicar(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno `confirmado` + cuerpo entrante firmado (sintético).
    creado = await _confirmado(cliente, AHORA + timedelta(hours=49))
    cuerpo = json.dumps(
        {
            "wa_message_id": "wamid.ficticio-duplicado-0001",
            "remitente_hash": hash_destino(TEL_WA_FICTICIO_1),
            "timestamp": AHORA.isoformat(),
            "tipo": "confirmacion",
            "turno_id": str(creado["id"]),
        }
    ).encode("utf-8")
    firma = hmac.new(
        SECRETO_WEBHOOK_FICTICIO.encode(), cuerpo, hashlib.sha256
    ).hexdigest()
    cabeceras = {
        "X-Hub-Signature-256": f"sha256={firma}",
        "Content-Type": "application/json",
    }

    # Act: el proveedor reintenta el mismo `wa_message_id` dos veces.
    with freeze_time(AHORA):
        primera = await cliente.post(WEBHOOK_URL, content=cuerpo, headers=cabeceras)
        segunda = await cliente.post(WEBHOOK_URL, content=cuerpo, headers=cabeceras)

    # Assert: `200` idempotente en ambas, sin duplicar envío ni PII en bodies.
    assert [primera.status_code, segunda.status_code] == [200, 200]
    assert TEL_WA_FICTICIO_1 not in primera.text + segunda.text
    filas = await _avisos(str(creado["id"]), "confirmacion")
    assert len(filas) <= 1
