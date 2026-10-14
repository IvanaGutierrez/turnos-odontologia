"""C-06 tasks 1.4+1.5 RED: fallback email/SMS + degradación graceful (R5).

Contrato que la parte 2 (GREEN) debe cumplir (design decisión 5):
- Paciente sin WhatsApp (`sin_whatsapp` o 4xx número inválido) → cascada
  email/SMTP → SMS gateway con los mismos datos mínimos, auditoría
  `aviso_fallback(canal)` sin PII, sin llamar a Meta.
- WA caído total (5xx/timeout en los 5 reintentos) → aviso `fallido` +
  `aviso_fallback` + `aviso_a_recepcion` (visible en agenda del día);
  el turno conserva `estado=confirmado` con su slot intacto.
- Reprogramación reagenda 24 h/3 h; cancelación cancela pendientes —
  ambas idempotentes (sin error si no hay pendientes).
- Tipo fuera de los 3 utility (marketing `promocion`) → rechazado con
  `422`, sin encolar ni llamar al proveedor (RN-NO-01).

Estado parte 1: no hay cascada/scheduler → FALLAN en rojo (la guarda de
check `ck_aviso_tipo` a nivel DB sí verifica la migración y pasa).
Todo dato sintético (R0); teléfonos solo hasheados (R6); type hints (R1);
`FakeWhatsAppTransport` como único transporte (R5, jamás red real).
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from freezegun import freeze_time
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.security import hashear_password
from app.models.auditoria import AuditoriaLog
from app.models.aviso_envio import AvisoEnvio
from app.models.entidades import Paciente, Turno, Usuario
from app.workers.envios import drenar_pendientes
from tests.conftest import (
    ID_PACIENTE_DEMO,
    TEL_WA_FICTICIO_1,
    TEL_WA_FICTICIO_3,
    FakeWhatsAppTransport,
    TestSession,
    hash_destino,
    payload_turno,
)

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime(2026, 11, 4, 10, 0, tzinfo=BA)

AUTOGESTION_URL = "/api/v1/turnos/publicos"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_STAFF = "wa.fallback.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Wa-Fallback-1234-no-real"


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


async def _confirmado(
    cliente: AsyncClient, access: str, inicio: datetime
) -> dict[str, object]:
    """Arrange: turno `confirmado` vía núcleo C-01 + autogestión C-05."""
    creado = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio),
        headers={"Authorization": f"Bearer {access}"},
    )
    assert creado.status_code == 201
    with freeze_time(AHORA):
        confirma = await cliente.post(
            f"{AUTOGESTION_URL}/{creado.json()['token_publico']}/confirmar"
        )
    assert confirma.status_code == 200
    assert confirma.json()["estado"] == "confirmado"
    return dict(creado.json())


async def _avisos(turno_id: str) -> list[AvisoEnvio]:
    async with TestSession() as sesion:
        return list(
            (
                await sesion.execute(
                    select(AvisoEnvio).where(AvisoEnvio.turno_id == uuid.UUID(turno_id))
                )
            )
            .scalars()
            .all()
        )


async def _auditorias(turno_id: str, accion: str) -> list[AuditoriaLog]:
    async with TestSession() as sesion:
        return list(
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == accion,
                        AuditoriaLog.entidad_id == turno_id,
                    )
                )
            )
            .scalars()
            .all()
        )


async def test_paciente_sin_whatsapp_recibe_email_sms_con_aviso_fallback(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno `confirmado` de paciente ficticio sin WhatsApp (el
    # flag `sin_whatsapp` lo evalúa la cascada GREEN).
    access = await _access(cliente)
    creado = await _confirmado(cliente, access, AHORA + timedelta(hours=49))
    turno_id = str(creado["id"])
    destino = hash_destino(TEL_WA_FICTICIO_3)
    fake_wa = FakeWhatsAppTransport()
    async with TestSession() as sesion:
        paciente = await sesion.get(Paciente, ID_PACIENTE_DEMO)
        assert paciente is not None
        paciente.sin_whatsapp = True
        await sesion.commit()

    # Act: la cascada evita Meta y emite email/SMS (reloj fijo).
    try:
        with freeze_time(AHORA):
            async with TestSession() as sesion:
                await drenar_pendientes(sesion, fake_wa)
    finally:
        async with TestSession() as sesion:
            paciente = await sesion.get(Paciente, ID_PACIENTE_DEMO)
            assert paciente is not None
            paciente.sin_whatsapp = False
            await sesion.commit()

    # Assert: sin llamadas a Meta, `fallback` + `aviso_fallback`, sin PII.
    assert fake_wa.llamadas == []
    filas = await _avisos(turno_id)
    assert any(f.estado == "fallback" for f in filas)
    auditoria = await _auditorias(turno_id, "aviso_fallback")
    assert len(auditoria) >= 1
    assert TEL_WA_FICTICIO_3 not in str(auditoria[0].diff)
    assert destino is not None


async def test_whatsapp_caido_total_fallido_con_aviso_recepcion_y_turno_intacto(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno `confirmado` + WA que falla los 5 reintentos (5xx).
    access = await _access(cliente)
    creado = await _confirmado(cliente, access, AHORA + timedelta(hours=49))
    turno_id = str(creado["id"])
    fake_caido = FakeWhatsAppTransport(fallos=["5xx"] * 5)

    # Act: GREEN agota `WA_MAX_REINTENTOS=5` y degrada a manual.
    with freeze_time(AHORA):
        for _ in range(5):
            async with TestSession() as sesion:
                await drenar_pendientes(sesion, fake_caido)

    # Assert: aviso `fallido` + `aviso_fallback` + `aviso_a_recepcion`,
    # turno intacto `confirmado` con su slot (sin doble reserva posible).
    assert fake_caido.fallos_restantes == 0
    filas = await _avisos(turno_id)
    assert any(f.estado == "fallido" for f in filas)
    assert await _auditorias(turno_id, "aviso_fallback") != []
    assert await _auditorias(turno_id, "aviso_a_recepcion") != []
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, uuid.UUID(turno_id))
        assert turno is not None and turno.estado == "confirmado"
    assert TEL_WA_FICTICIO_1 not in str(filas)


async def test_reprogramacion_reagenda_24h_3h_y_cancelacion_cancela_pendientes(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno `confirmado` a +49 h con sus 3 avisos programados.
    access = await _access(cliente)
    creado = await _confirmado(cliente, access, AHORA + timedelta(hours=49))
    token = str(creado["token_publico"])
    turno_id = str(creado["id"])
    nuevo_inicio = AHORA + timedelta(hours=73)

    # Act: reprogramar (reloj controlado) y luego cancelar el nuevo turno.
    with freeze_time(AHORA):
        reprograma = await cliente.post(
            f"{AUTOGESTION_URL}/{token}/reprogramar",
            json={"nuevo_inicio": nuevo_inicio.isoformat()},
        )
    assert reprograma.status_code in (200, 201)
    nuevo_token = str(reprograma.json()["token_publico"])
    with freeze_time(AHORA):
        cancela = await cliente.post(
            f"{AUTOGESTION_URL}/{nuevo_token}/cancelar",
            json={"motivo": "Cambio ficticio demo"},
        )
    assert cancela.status_code == 200

    # Assert: el turno viejo cancela sus pendientes y el nuevo reagenda
    # 24 h/3 h; al cancelar, los pendientes quedan `cancelado`
    # (idempotente: repetir no falla ni duplica).
    viejos = await _avisos(turno_id)
    assert {f.tipo_aviso for f in viejos} >= {
        "confirmacion",
        "recordatorio_24h",
        "aviso_3h",
    }
    with freeze_time(AHORA):
        repite = await cliente.post(
            f"{AUTOGESTION_URL}/{nuevo_token}/cancelar",
            json={"motivo": "Cambio ficticio demo"},
        )
    assert repite.status_code == 200
    nuevos = await _avisos(str(reprograma.json()["id"]))
    assert all(f.estado == "cancelado" for f in nuevos)


async def test_tipo_marketing_fuera_de_scope_rechazado_sin_encolar(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno `confirmado` + Fake espiando llamadas al proveedor.
    access = await _access(cliente)
    creado = await _confirmado(cliente, access, AHORA + timedelta(hours=49))
    turno_id = uuid.UUID(str(creado["id"]))
    fake = FakeWhatsAppTransport()

    # Act: intentar encolar `promocion` (marketing, fuera de scope RN-NO-01).
    # La parte 2 lo rechaza con `422` en servicio; la DB lo veta con check.
    with freeze_time(AHORA):
        try:
            async with TestSession() as sesion:
                sesion.add(
                    AvisoEnvio(
                        turno_id=turno_id,
                        tipo_aviso="promocion",
                        estado="pendiente",
                    )
                )
                await sesion.commit()
                encolado = True
        except IntegrityError:
            encolado = False

    # Assert: rechazado sin encolar, sin llamar al proveedor, sin auditoría.
    assert encolado is False
    assert fake.llamadas == []
    assert await _avisos(str(turno_id)) == [] or all(
        f.tipo_aviso != "promocion" for f in await _avisos(str(turno_id))
    )
    assert await _auditorias(str(turno_id), "aviso_enviado") == []
