"""C-12 task 1.1 RED: "SÍ" conversacional confirma el turno del remitente (R5).

Contrato que la parte 2 (GREEN) debe cumplir
(`notificaciones/confirmacion-conversacional`):
- `POST /webhooks/whatsapp` firmado con `{"texto": "SÍ", "remitente": <E.164>}`
  del teléfono del turno `reservado` (sin seña pendiente, inicio futuro) →
  `200` y el turno pasa a `confirmado` + auditoría `turno_confirmado` con
  `canal=whatsapp` (sin PII, R6).
- Variantes (`si`, `confirmo`, `dale`) confirman igual (tabla ES versionada).
- Repetir "SÍ" (ids distintos) sobre el turno ya `confirmado` → acuse
  idempotente sin re-auditar la mutación.

Estado parte 1: el handler conversacional NO existe (el webhook solo acusa
recibo C-06) → FALLAN en rojo (turno intacto, cero auditoría).
Todo dato sintético (R0, prefijo `+54 9 11 15-000-XXXX`); type hints (R1);
Fake inyectado vía app ASGI, jamás red real (R5); sin secretos en archivos:
la firma usa el placeholder de la suite (R7).
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
from app.models.auditoria import AuditoriaLog
from app.models.entidades import Paciente, Turno, Usuario
from tests.conftest import TestSession, hash_destino, payload_turno

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime(2026, 11, 4, 10, 0, tzinfo=BA)

WEBHOOK_URL = "/webhooks/whatsapp"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_STAFF = "wa.conv.confirmar.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Wa-Conv-Confirmar-1234-no-real"

# Placeholder solo de test (R7): iguala al default de settings en este runner.
SECRETO_WEBHOOK_FICTICIO = "secreto-webhook-ficticio-no-real-32b-min"

TEL_REMITENTE = "+54 9 11 15-000-0011"
DNI_REMITENTE = "88300111"


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


async def _crear_paciente() -> uuid.UUID:
    """Paciente ficticio cuyo teléfono es el remitente WA del test (R0)."""
    async with TestSession() as sesion:
        await sesion.execute(delete(Paciente).where(Paciente.dni == DNI_REMITENTE))
        sesion.add(
            Paciente(
                nombre="Remitente Conversacional Ficticia",
                dni=DNI_REMITENTE,
                telefono=TEL_REMITENTE,
                consentimiento_hc=False,
            )
        )
        await sesion.commit()
        fila = (
            await sesion.execute(select(Paciente).where(Paciente.dni == DNI_REMITENTE))
        ).scalar_one()
        return fila.id


async def _crear_reservado(
    cliente: AsyncClient, access: str, inicio: datetime
) -> dict[str, object]:
    """Arrange: turno `reservado` del remitente vía núcleo C-01."""
    paciente_id = await _crear_paciente()
    respuesta = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio, paciente_id=str(paciente_id)),
        headers={"Authorization": f"Bearer {access}"},
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["estado"] == "reservado"
    return dict(respuesta.json())


def _firmar(cuerpo: bytes) -> str:
    firma = hmac.new(
        SECRETO_WEBHOOK_FICTICIO.encode(), cuerpo, hashlib.sha256
    ).hexdigest()
    return f"sha256={firma}"


def _cuerpo_wa(wa_id: str, texto: str) -> bytes:
    """Inbound conversacional: texto libre + remitente E.164 (GREEN lo usa).

    El router C-06 actual ignora estos extras (`extra="ignore"`) y solo acusa
    recibo: por eso estos tests fallan en rojo hasta el GREEN.
    """
    return json.dumps(
        {
            "wa_message_id": wa_id,
            "remitente": TEL_REMITENTE,
            "remitente_hash": hash_destino(TEL_REMITENTE),
            "timestamp": AHORA.isoformat(),
            "tipo": "texto",
            "texto": texto,
        }
    ).encode("utf-8")


async def _enviar_si(cliente: AsyncClient, texto: str, wa_id: str) -> object:
    cuerpo = _cuerpo_wa(wa_id, texto)
    return await cliente.post(
        WEBHOOK_URL,
        content=cuerpo,
        headers={
            "X-Hub-Signature-256": _firmar(cuerpo),
            "Content-Type": "application/json",
        },
    )


async def _estado_turno(turno_id: str) -> str:
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, uuid.UUID(turno_id))
        assert turno is not None
        return str(turno.estado)


async def _auditorias_confirmacion(turno_id: str) -> list[AuditoriaLog]:
    async with TestSession() as sesion:
        return list(
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "turno_confirmado",
                        AuditoriaLog.entidad_id == turno_id,
                    )
                )
            )
            .scalars()
            .all()
        )


async def test_si_valido_confirma_y_audita_con_canal_whatsapp(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno `reservado` sin seña del remitente, inicio a +49 h.
    access = await _access(cliente)
    creado = await _crear_reservado(cliente, access, AHORA + timedelta(hours=49))

    # Act: "SÍ" verificado del teléfono del turno (reloj controlado BA).
    with freeze_time(AHORA):
        respuesta = await _enviar_si(cliente, "SÍ", "wamid.conv-conf-0001")

    # Assert: 200 + `confirmado` + UNA auditoría `canal=whatsapp` sin PII.
    assert respuesta.status_code == 200  # type: ignore[attr-defined]
    assert await _estado_turno(str(creado["id"])) == "confirmado"
    filas = await _auditorias_confirmacion(str(creado["id"]))
    assert len(filas) == 1
    diff = filas[0].diff if isinstance(filas[0].diff, dict) else {}
    assert diff.get("canal") == "whatsapp"
    assert TEL_REMITENTE not in str(filas[0].diff)
    assert DNI_REMITENTE not in str(filas[0].diff)


@pytest.mark.parametrize(
    ("texto", "hora"),
    [("si", 12), ("confirmo", 14), ("dale", 16)],
)
async def test_variantes_de_si_confirman_igual(
    cliente: AsyncClient, staff: None, texto: str, hora: int
) -> None:
    # Arrange: un `reservado` por variante (horas distintas, sin solape).
    access = await _access(cliente)
    creado = await _crear_reservado(
        cliente, access, AHORA.replace(hour=hora, minute=0) + timedelta(days=1)
    )

    # Act: variante del vocabulario confirmar (reloj controlado BA).
    with freeze_time(AHORA):
        respuesta = await _enviar_si(cliente, texto, f"wamid.conv-conf-{hora}")

    # Assert: la variante confirma igual que "SÍ".
    assert respuesta.status_code == 200  # type: ignore[attr-defined]
    assert await _estado_turno(str(creado["id"])) == "confirmado"
    assert len(await _auditorias_confirmacion(str(creado["id"]))) == 1


async def test_si_repetido_idempotente_sin_reauditar(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno `reservado` del remitente.
    access = await _access(cliente)
    creado = await _crear_reservado(cliente, access, AHORA + timedelta(hours=50))

    # Act: "SÍ" dos veces con `wa_message_id` distintos (reloj controlado).
    with freeze_time(AHORA):
        primera = await _enviar_si(cliente, "SÍ", "wamid.conv-conf-rep1")
        segunda = await _enviar_si(cliente, "SÍ", "wamid.conv-conf-rep2")

    # Assert: ambas 200, sigue `confirmado`, UNA sola auditoría de mutación.
    assert primera.status_code == 200  # type: ignore[attr-defined]
    assert segunda.status_code == 200  # type: ignore[attr-defined]
    assert await _estado_turno(str(creado["id"])) == "confirmado"
    assert len(await _auditorias_confirmacion(str(creado["id"]))) == 1
