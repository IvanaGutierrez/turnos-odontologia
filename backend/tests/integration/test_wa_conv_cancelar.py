"""C-12 task 1.3 RED: "CANCELAR" conversacional con antelación RN-AG-05 (R5).

Contrato que la parte 2 (GREEN) debe cumplir
(`notificaciones/confirmacion-conversacional`):
- "CANCELAR" verificado del remitente del turno `confirmado` con inicio a
  más de `CANCEL_MIN_HOURS` → `cancelado` auditado con `canal=whatsapp` y
  los pendientes 24 h / 3 h (C-06) quedan `cancelado` idempotentemente.
- Dentro de la ventana mínima → rechazo con `CANCEL_POLICY_TEXT`, turno
  intacto (estado + slot) y sin auditoría de baja.
- Intent sobre turno terminal (`atendido`) → `422` conversacional sin mutar.

Estado parte 1: el webhook solo acusa recibo → FALLAN en rojo.
Todo dato sintético (R0); type hints (R1); jamás red real (R5); placeholder
de firma (R7); respuestas/ auditoría sin PII (R6).
"""

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
from app.core.settings import settings
from app.models.auditoria import AuditoriaLog
from app.models.aviso_envio import AvisoEnvio
from app.models.entidades import Paciente, Turno, Usuario
from tests.conftest import TestSession, hash_destino, payload_turno

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime(2026, 11, 4, 10, 0, tzinfo=BA)

WEBHOOK_URL = "/webhooks/whatsapp"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"
AUTOGESTION_URL = "/api/v1/turnos/publicos"

EMAIL_STAFF = "wa.conv.cancelar.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Wa-Conv-Cancelar-1234-no-real"

SECRETO_WEBHOOK_FICTICIO = "secreto-webhook-ficticio-no-real-32b-min"

TEL_REMITENTE = "+54 9 11 15-000-0014"
DNI_REMITENTE = "88300114"


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


async def _crear_confirmado(
    cliente: AsyncClient, access: str, inicio: datetime
) -> dict[str, object]:
    """Arrange: turno `reservado` del remitente + confirmado por token C-05."""
    async with TestSession() as sesion:
        await sesion.execute(delete(Paciente).where(Paciente.dni == DNI_REMITENTE))
        sesion.add(
            Paciente(
                nombre="Remitente Cancelación Ficticia",
                dni=DNI_REMITENTE,
                telefono=TEL_REMITENTE,
                consentimiento_hc=False,
            )
        )
        await sesion.commit()
        paciente_id = (
            await sesion.execute(select(Paciente).where(Paciente.dni == DNI_REMITENTE))
        ).scalar_one().id
    creado = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio, paciente_id=str(paciente_id)),
        headers={"Authorization": f"Bearer {access}"},
    )
    assert creado.status_code == 201
    with freeze_time(AHORA):
        confirmado = await cliente.post(
            f"{AUTOGESTION_URL}/{creado.json()['token_publico']}/confirmar"
        )
    assert confirmado.status_code == 200
    return dict(creado.json())


def _firmar(cuerpo: bytes) -> str:
    firma = hmac.new(
        SECRETO_WEBHOOK_FICTICIO.encode(), cuerpo, hashlib.sha256
    ).hexdigest()
    return f"sha256={firma}"


async def _post_wa(cliente: AsyncClient, wa_id: str, texto: str) -> object:
    cuerpo = json.dumps(
        {
            "wa_message_id": wa_id,
            "remitente": TEL_REMITENTE,
            "remitente_hash": hash_destino(TEL_REMITENTE),
            "timestamp": AHORA.isoformat(),
            "tipo": "texto",
            "texto": texto,
        }
    ).encode("utf-8")
    return await cliente.post(
        WEBHOOK_URL,
        content=cuerpo,
        headers={
            "X-Hub-Signature-256": _firmar(cuerpo),
            "Content-Type": "application/json",
        },
    )


async def _turno_db(turno_id: str) -> Turno:
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, uuid.UUID(turno_id))
        assert turno is not None
        sesion.expunge(turno)
        return turno


async def _avisos(turno_id: str) -> list[AvisoEnvio]:
    async with TestSession() as sesion:
        return list(
            (
                await sesion.execute(
                    select(AvisoEnvio).where(
                        AvisoEnvio.turno_id == uuid.UUID(turno_id)
                    )
                )
            )
            .scalars()
            .all()
        )


async def _bajas(turno_id: str) -> list[AuditoriaLog]:
    async with TestSession() as sesion:
        return list(
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "turno_cancelado",
                        AuditoriaLog.entidad_id == turno_id,
                    )
                )
            )
            .scalars()
            .all()
        )


async def test_cancelar_en_termino_cancela_y_apaga_recordatorios(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: `confirmado` a +49 h (las 3 ventanas C-06 programadas).
    access = await _access(cliente)
    creado = await _crear_confirmado(cliente, access, AHORA + timedelta(hours=49))
    assert {a.tipo_aviso for a in await _avisos(str(creado["id"]))} >= {
        "confirmacion",
        "recordatorio_24h",
        "aviso_3h",
    }

    # Act: "CANCELAR" verificado del remitente (reloj controlado BA).
    with freeze_time(AHORA):
        respuesta = await _post_wa(cliente, "wamid.conv-canc-0001", "CANCELAR")

    # Assert: `cancelado` + auditoría whatsapp + pendientes apagados, sin PII.
    assert respuesta.status_code == 200  # type: ignore[attr-defined]
    assert (await _turno_db(str(creado["id"]))).estado == "cancelado"
    filas = await _bajas(str(creado["id"]))
    assert len(filas) == 1
    diff = filas[0].diff if isinstance(filas[0].diff, dict) else {}
    assert diff.get("canal") == "whatsapp"
    assert TEL_REMITENTE not in str(filas[0].diff)
    pendientes = [
        a for a in await _avisos(str(creado["id"])) if a.estado != "cancelado"
    ]
    assert pendientes == []


async def test_cancelar_tardia_rechaza_con_politica_sin_mutar(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: `confirmado` a +2 h (dentro de la ventana mínima de 12 h).
    access = await _access(cliente)
    creado = await _crear_confirmado(cliente, access, AHORA + timedelta(hours=2))
    inicio_antes = (await _turno_db(str(creado["id"]))).inicio

    # Act: "CANCELAR" verificado fuera de término (reloj controlado BA).
    with freeze_time(AHORA):
        respuesta = await _post_wa(cliente, "wamid.conv-canc-0002", "cancelar")

    # Assert: rechazo con la política, turno intacto y sin auditoría de baja.
    assert respuesta.status_code == 200  # type: ignore[attr-defined]
    assert settings.cancel_policy_text[:20] in respuesta.text  # type: ignore[attr-defined]
    turno = await _turno_db(str(creado["id"]))
    assert turno.estado == "confirmado"
    assert turno.inicio == inicio_antes
    assert await _bajas(str(creado["id"])) == []
    assert TEL_REMITENTE not in respuesta.text  # type: ignore[attr-defined]


async def test_cancelar_en_estado_terminal_responde_422_sin_mutar(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno del remitente llevado a `atendido` (terminal).
    access = await _access(cliente)
    creado = await _crear_confirmado(cliente, access, AHORA + timedelta(hours=49))
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
        assert turno is not None
        turno.estado = "atendido"
        await sesion.commit()

    # Act: "CANCELAR" verificado sobre estado terminal (reloj controlado).
    with freeze_time(AHORA):
        respuesta = await _post_wa(cliente, "wamid.conv-canc-0003", "CANCELAR")

    # Assert: 422 conversacional, estado intacto, sin auditoría de baja.
    assert respuesta.status_code == 422  # type: ignore[attr-defined]
    assert (await _turno_db(str(creado["id"]))).estado == "atendido"
    assert await _bajas(str(creado["id"])) == []
