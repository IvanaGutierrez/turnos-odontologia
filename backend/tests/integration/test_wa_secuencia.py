"""C-06 tasks 1.1+1.5 RED: secuencia confirmación + 24 h + 3 h (R5).

Contrato que la parte 2 (GREEN) debe cumplir (`notificaciones/...`):
- Al confirmar un turno (`reservado→confirmado`) se encola `confirmacion`
  inmediata con la plantilla `WA_TEMPLATE_CONFIRM` y se programan
  `recordatorio_24h` (`inicio - RECORDATORIO_24H_MIN`) y `aviso_3h`
  (`inicio - AVISO_3H_MIN`); auditoría `aviso_encolado` por tipo, sin PII.
- Con el transporte sano y reloj controlado, un turno `confirmado`
  atraviesa `confirmacion → recordatorio_24h → aviso_3h` en ese orden,
  cada uno `enviado` con `proveedor_msg_id` distinto.
- En ventana 24 h se emite `recordatorio_24h`; en ventana 3 h, `aviso_3h`
  (fecha, hora, sede, link de gestión; jamás DNI/teléfono/HC — R6).

Estado parte 1: no hay scheduler ni transporte → FALLAN en rojo
(cero filas en `aviso_envio`). Reloj freezegun `America/Argentina/Buenos_Aires`.
Todo dato sintético (R0, prefijo `+54 9 11 15-000-XXXX`); en asserts/logs
solo `sha256(tel)[:12]` (R6); type hints siempre (R1); jamás red real —
el único transporte en este archivo es el `FakeWhatsAppTransport` (R5).
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

from app.core.security import hashear_password
from app.models.aviso_envio import AvisoEnvio
from app.models.entidades import Usuario
from app.workers.envios import drenar_pendientes
from tests.conftest import (
    TEL_WA_FICTICIO_1,
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

EMAIL_STAFF = "wa.secuencia.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Wa-Secuencia-1234-no-real"


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


async def _crear_reservado(
    cliente: AsyncClient, access: str, inicio: datetime
) -> dict[str, object]:
    """Arrange: turno `reservado` vía núcleo C-01 (reloj real)."""
    respuesta = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio),
        headers={"Authorization": f"Bearer {access}"},
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["estado"] == "reservado"
    return dict(respuesta.json())


async def _confirmar(cliente: AsyncClient, token_publico: str) -> None:
    """Act: confirmar por token público (reloj congelado por el llamante)."""
    respuesta = await cliente.post(f"{AUTOGESTION_URL}/{token_publico}/confirmar")
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "confirmado"


async def _avisos(turno_id: str) -> list[AvisoEnvio]:
    async with TestSession() as sesion:
        filas = (
            (
                await sesion.execute(
                    select(AvisoEnvio)
                    .where(AvisoEnvio.turno_id == uuid.UUID(turno_id))
                    .order_by(AvisoEnvio.creado_en)
                )
            )
            .scalars()
            .all()
        )
        return list(filas)


async def test_confirmar_turno_encola_confirmacion_inmediata_con_plantilla_utility(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno `reservado` a más de 24 h (las 3 ventanas existen).
    access = await _access(cliente)
    creado = await _crear_reservado(cliente, access, AHORA + timedelta(hours=49))
    destino = hash_destino(TEL_WA_FICTICIO_1)

    # Act: confirmar con reloj controlado (el scheduler encolaría aquí).
    with freeze_time(AHORA):
        await _confirmar(cliente, str(creado["token_publico"]))

    # Assert: UNA `confirmacion` encolada + programados 24 h/3 h, sin PII.
    filas = await _avisos(str(creado["id"]))
    tipos = [f.tipo_aviso for f in filas]
    assert "confirmacion" in tipos
    assert "recordatorio_24h" in tipos
    assert "aviso_3h" in tipos
    assert TEL_WA_FICTICIO_1 not in str(filas)
    assert destino is not None


async def test_secuencia_completa_tres_envios_en_orden_con_ids_distintos(
    cliente: AsyncClient, staff: None, transporte_fake: FakeWhatsAppTransport
) -> None:
    # Arrange: turno `confirmado` con inicio a +49 h de `AHORA`.
    access = await _access(cliente)
    creado = await _crear_reservado(cliente, access, AHORA + timedelta(hours=49))
    inicio = AHORA + timedelta(hours=49)

    # Act: confirmar y drenar el worker en cada ventana (reloj controlado).
    async def _drenar() -> None:
        async with TestSession() as sesion:
            await drenar_pendientes(sesion, transporte_fake)

    with freeze_time(AHORA) as reloj:
        await _confirmar(cliente, str(creado["token_publico"]))
        await _drenar()
        reloj.move_to(inicio - timedelta(hours=24))
        await _drenar()
        reloj.move_to(inicio - timedelta(hours=3))
        await _drenar()

    # Assert: 3 envíos en orden, cada uno `enviado` con id de proveedor único.
    filas = await _avisos(str(creado["id"]))
    assert [f.tipo_aviso for f in filas] == [
        "confirmacion",
        "recordatorio_24h",
        "aviso_3h",
    ]
    assert all(f.estado == "enviado" for f in filas)
    ids_proveedor = [f.proveedor_msg_id for f in filas]
    assert None not in ids_proveedor
    assert len(set(ids_proveedor)) == 3


async def test_ventanas_24h_y_3h_emiten_recordatorio_y_aviso_sin_pii(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: un turno a ~24 h y otro a ~3 h de `AHORA` (reloj real).
    access = await _access(cliente)
    turno_24 = await _crear_reservado(cliente, access, AHORA + timedelta(hours=25))
    turno_3 = await _crear_reservado(cliente, access, AHORA + timedelta(hours=4))

    # Act: confirmar ambos con reloj controlado (el worker emitiría en ventana).
    with freeze_time(AHORA):
        await _confirmar(cliente, str(turno_24["token_publico"]))
        await _confirmar(cliente, str(turno_3["token_publico"]))

    # Assert: cada ventana emite su tipo con datos mínimos, sin PII excedente.
    filas_24 = await _avisos(str(turno_24["id"]))
    filas_3 = await _avisos(str(turno_3["id"]))
    assert "recordatorio_24h" in [f.tipo_aviso for f in filas_24]
    assert "aviso_3h" in [f.tipo_aviso for f in filas_3]
    for filas in (filas_24, filas_3):
        assert TEL_WA_FICTICIO_1 not in str(filas)
        assert "90123456" not in str(filas)
