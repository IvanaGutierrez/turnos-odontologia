"""C-12 task 1.5 RED: seña pendiente por chat + reagendado C-06 (R5).

Contrato que la parte 2 (GREEN) debe cumplir
(`notificaciones/confirmacion-conversacional`):
- Turno `reservado` con `requiere_sena` sin pago `acreditado` (RN-PA-02):
  "SÍ" verificado → responde el link de pago MP sin mutar el estado, sin
  crear ningún `Pago` y sin auditoría de alta.
- Tras acreditar la seña (fixture C-08: `Pago.acreditado` del turno), el
  siguiente "SÍ" confirma normalmente (`confirmado` + `canal=whatsapp`).
- Cada cambio conversacional reagenda vía scheduler C-06: tras confirmar,
  `aviso_envio` trae `confirmacion` + `recordatorio_24h` + `aviso_3h`;
  tras cancelar, esos pendientes quedan `cancelado`.

Estado parte 1: el webhook solo acusa recibo → FALLAN en rojo.
Todo dato sintético (R0, montos ARS de juguete); type hints (R1); jamás red
real (R5); placeholder de firma (R7); sin PII en respuestas/auditoría (R6).
"""

import hashlib
import hmac
import json
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from freezegun import freeze_time
from httpx import AsyncClient
from sqlalchemy import delete, func, select

from app.core.security import hashear_password
from app.models.auditoria import AuditoriaLog
from app.models.aviso_envio import AvisoEnvio
from app.models.entidades import Paciente, Prestacion, Turno, Usuario
from app.models.pago import Pago
from tests.conftest import TestSession, hash_destino, payload_turno

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime(2026, 11, 4, 10, 0, tzinfo=BA)

WEBHOOK_URL = "/webhooks/whatsapp"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_STAFF = "wa.conv.sena.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Wa-Conv-Sena-1234-no-real"

SECRETO_WEBHOOK_FICTICIO = "secreto-webhook-ficticio-no-real-32b-min"

TEL_REMITENTE = "+54 9 11 15-000-0016"
DNI_REMITENTE = "88300116"
MONTO_SENA_FICTICIO = Decimal("5000.00")


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


async def _prestacion_con_sena() -> uuid.UUID:
    """Prestación ficticia con seña de juguete (monto fijo ARS, R0)."""
    pid = uuid.uuid4()
    async with TestSession() as sesion:
        sesion.add(
            Prestacion(
                id=pid,
                nombre="Endodoncia Demo Seña Conversacional Ficticia",
                duracion_min=45,
                requiere_sena=True,
                precio_base=Decimal("20000.00"),
                sena_monto_fijo=MONTO_SENA_FICTICIO,
            )
        )
        await sesion.commit()
    return pid


async def _crear_reservado(
    cliente: AsyncClient,
    access: str,
    inicio: datetime,
    prestacion_id: uuid.UUID | None = None,
) -> dict[str, object]:
    """Arrange: turno `reservado` del remitente vía núcleo C-01."""
    async with TestSession() as sesion:
        await sesion.execute(delete(Paciente).where(Paciente.dni == DNI_REMITENTE))
        sesion.add(
            Paciente(
                nombre="Remitente Seña Ficticia",
                dni=DNI_REMITENTE,
                telefono=TEL_REMITENTE,
                consentimiento_hc=False,
            )
        )
        await sesion.commit()
        paciente_id = (
            await sesion.execute(select(Paciente).where(Paciente.dni == DNI_REMITENTE))
        ).scalar_one().id
    extras: dict[str, object] = {"paciente_id": str(paciente_id)}
    if prestacion_id is not None:
        extras["prestacion_id"] = str(prestacion_id)
    creado = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio, **extras),
        headers={"Authorization": f"Bearer {access}"},
    )
    assert creado.status_code == 201
    return dict(creado.json())


async def _limpiar_prestacion(pid: uuid.UUID) -> None:
    async with TestSession() as sesion:
        await sesion.execute(
            delete(Pago).where(
                Pago.turno_id.in_(
                    select(Turno.id).where(Turno.prestacion_id == pid)
                )
            )
        )
        await sesion.execute(delete(Turno).where(Turno.prestacion_id == pid))
        await sesion.execute(delete(Prestacion).where(Prestacion.id == pid))
        await sesion.commit()


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


async def _acreditar_sena(turno_id: str) -> None:
    """Fixture C-08: `Pago.acreditado` del turno (monto de juguete, R0)."""
    async with TestSession() as sesion:
        sesion.add(
            Pago(
                turno_id=uuid.UUID(turno_id),
                monto=MONTO_SENA_FICTICIO,
                moneda="ARS",
                metodo="mercadopago",
                estado="acreditado",
                mp_payment_id=f"pago-wa-conv-ficticio-{uuid.uuid4().hex[:8]}",
                webhook_recibido_at=AHORA,
            )
        )
        await sesion.commit()


async def _pagos_de(turno_id: str) -> int:
    async with TestSession() as sesion:
        total = await sesion.execute(
            select(func.count())
            .select_from(Pago)
            .where(Pago.turno_id == uuid.UUID(turno_id))
        )
        return int(total.scalar_one())


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


async def test_sena_pendiente_responde_link_mp_sin_confirmar(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: `reservado` con seña requerida y ningún pago.
    access = await _access(cliente)
    pid = await _prestacion_con_sena()
    try:
        creado = await _crear_reservado(
            cliente, access, AHORA + timedelta(hours=49), prestacion_id=pid
        )

        # Act: "SÍ" verificado con seña pendiente (reloj controlado BA).
        with freeze_time(AHORA):
            respuesta = await _post_wa(cliente, "wamid.conv-sena-0001", "SÍ")

        # Assert: link de pago, estado intacto, sin Pago ni alta auditada.
        assert respuesta.status_code == 200  # type: ignore[attr-defined]
        cuerpo = respuesta.text.lower()  # type: ignore[attr-defined]
        assert "pag" in cuerpo and "http" in cuerpo
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
            assert turno is not None and turno.estado == "reservado"
        assert await _pagos_de(str(creado["id"])) == 0
        async with TestSession() as sesion:
            altas = (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "turno_confirmado",
                        AuditoriaLog.entidad_id == str(creado["id"]),
                    )
                )
            ).scalars().all()
        assert list(altas) == []
    finally:
        await _limpiar_prestacion(pid)


async def test_sena_acreditada_confirma_normal_por_chat(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: `reservado` con seña + pago `acreditado` (fixture C-08).
    access = await _access(cliente)
    pid = await _prestacion_con_sena()
    try:
        creado = await _crear_reservado(
            cliente, access, AHORA + timedelta(hours=49), prestacion_id=pid
        )
        await _acreditar_sena(str(creado["id"]))

        # Act: "SÍ" verificado con seña acreditada (reloj controlado BA).
        with freeze_time(AHORA):
            respuesta = await _post_wa(cliente, "wamid.conv-sena-0002", "SÍ")

        # Assert: confirma + audita `canal=whatsapp`, sin PII.
        assert respuesta.status_code == 200  # type: ignore[attr-defined]
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
            assert turno is not None and turno.estado == "confirmado"
            filas = (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "turno_confirmado",
                        AuditoriaLog.entidad_id == str(creado["id"]),
                    )
                )
            ).scalars().all()
        assert len(list(filas)) == 1
    finally:
        await _limpiar_prestacion(pid)


async def test_cambio_conversacional_reagenda_24h_3h_y_cancelar_apaga(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: `reservado` sin seña del remitente, inicio a +49 h.
    access = await _access(cliente)
    creado = await _crear_reservado(cliente, access, AHORA + timedelta(hours=49))

    # Act: "SÍ" conversacional y luego "CANCELAR" (reloj controlado BA).
    with freeze_time(AHORA):
        confirma = await _post_wa(cliente, "wamid.conv-sena-0003", "SÍ")
        assert confirma.status_code == 200  # type: ignore[attr-defined]
        tipos = {a.tipo_aviso for a in await _avisos(str(creado["id"]))}
        cancela = await _post_wa(cliente, "wamid.conv-sena-0004", "CANCELAR")
        assert cancela.status_code == 200  # type: ignore[attr-defined]

    # Assert: confirmar programó la secuencia; cancelar la apagó.
    assert tipos >= {"confirmacion", "recordatorio_24h", "aviso_3h"}
    finales = await _avisos(str(creado["id"]))
    assert finales != []
    assert all(a.estado == "cancelado" for a in finales)
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
        assert turno is not None and turno.estado == "cancelado"
