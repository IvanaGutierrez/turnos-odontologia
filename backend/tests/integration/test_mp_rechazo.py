"""C-08 tasks 1.4+1.5 RED: rechazo visible + reintento + MP caído (R5).

Contrato que la parte 2 (GREEN) debe cumplir:
- Aviso verificado de pago **rechazado** → `pago pendiente→rechazado`
  (idempotente por `mp_payment_id`), `GET /pagar/:token` expone
  `estado_pago='rechazado'` con link de reintento (nueva preferencia,
  jamás dos pendientes por turno) y el turno sigue `reservado`.
- Confirmar por autogestión con seña pendiente sigue `422
  sena_pendiente` hasta acreditar (regresión C-05, RN-PA-01/02).
- MP caído (Fake `programar_caida`) → se degrada a manual sin perder el
  turno: sigue `reservado`, ningún pago se acredita por defecto y hay
  aviso a recepción; el mismo link permite reintentar.

Estado parte 1: router de cobros NO existe → FALLAN en rojo (`404`).
(El `422 sena_pendiente` de confirmar ya existe por C-05: esos
sub-asserts pasan, pero cada test falla en su assert de cobros.)
Todo dato sintético (R0); type hints siempre (R1).
"""

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

import pytest
import pytest_asyncio
from app.core.security import hashear_password
from app.models.entidades import Prestacion, Turno, Usuario
from httpx import AsyncClient
from sqlalchemy import delete, text

from tests.conftest import (
    MONTO_PRECIO_BASE_FICTICIO,
    MONTO_SENA_FIJO_FICTICIO,
    FakeMercadoPagoClient,
    TestSession,
    cuerpo_aviso_mp,
    extraer_token_pago,
    firmar_aviso_mp,
    inicio_demo,
    inyectar_mp_fake,
    payload_turno,
    secreto_mp_prueba,
)

pytestmark = pytest.mark.integration

PAGAR_URL = "/pagar"
WEBHOOK_URL = "/webhooks/mercadopago"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"
CONFIRMAR_URL = "/api/v1/turnos/publicos"

EMAIL_STAFF = "mp.rechazo.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Mp-Rechazo-1234-no-real"

MP_PAYMENT_FICTICIO = "pay-ficticio-rech-0001"
REQUEST_ID_FICTICIO = "req-ficticio-rech-0001"
TS_FICTICIO = "1700000002"


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


async def _prestacion_sena(nombre: str) -> uuid.UUID:
    pid = uuid.uuid4()
    async with TestSession() as sesion:
        sesion.add(
            Prestacion(
                id=pid, nombre=nombre, duracion_min=45, requiere_sena=True
            )
        )
        await sesion.commit()
        await sesion.execute(
            text(
                "UPDATE prestacion SET precio_base = :pb, sena_monto_fijo = :f "
                "WHERE id = :pid"
            ),
            {
                "pb": MONTO_PRECIO_BASE_FICTICIO,
                "f": MONTO_SENA_FIJO_FICTICIO,
                "pid": pid,
            },
        )
        await sesion.commit()
    return pid


async def _limpiar_prestacion(pid: uuid.UUID) -> None:
    async with TestSession() as sesion:
        await sesion.execute(
            text(
                "DELETE FROM pago WHERE turno_id IN "
                "(SELECT id FROM turno WHERE prestacion_id = :pid)"
            ),
            {"pid": pid},
        )
        await sesion.execute(
            Turno.__table__.delete().where(Turno.prestacion_id == pid)  # type: ignore[arg-type]
        )
        await sesion.execute(
            Prestacion.__table__.delete().where(Prestacion.id == pid)  # type: ignore[arg-type]
        )
        await sesion.commit()


async def _crear_turno(
    cliente: AsyncClient, inicio: datetime, prestacion_id: uuid.UUID
) -> dict[str, object]:
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_STAFF, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    creado = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio, prestacion_id=prestacion_id),
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert creado.status_code == 201
    return dict(creado.json())


def _aviso_firmado(mp_payment_id: str) -> tuple[bytes, dict[str, str]]:
    crudo = json.dumps(cuerpo_aviso_mp(mp_payment_id)).encode("utf-8")
    cabeceras = {
        "x-signature": firmar_aviso_mp(
            secreto=secreto_mp_prueba(),
            mp_payment_id=mp_payment_id,
            request_id=REQUEST_ID_FICTICIO,
            ts=TS_FICTICIO,
        ),
        "x-request-id": REQUEST_ID_FICTICIO,
        "Content-Type": "application/json",
    }
    return crudo, cabeceras


async def test_pago_rechazado_visible_con_reintento_y_turno_pendiente(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: turno con seña + Fake que informa el pago como rechazado.
    pid = await _prestacion_sena("Endodoncia Rechazo Ficticia")
    mp_fake.programar_pago(MP_PAYMENT_FICTICIO, estado="rechazado")
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(10, 0).replace(day=9), pid)
        crudo, cabeceras = _aviso_firmado(MP_PAYMENT_FICTICIO)

        # Act: aviso verificado de pago rechazado.
        respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

        # Assert: 200 + `rechazado` visible con reintento, turno pendiente.
        assert respuesta.status_code == 200
        async with TestSession() as sesion:
            estado = await sesion.scalar(
                text("SELECT estado FROM pago WHERE mp_payment_id = :mp"),
                {"mp": MP_PAYMENT_FICTICIO},
            )
            assert estado == "rechazado"
        token, firma = extraer_token_pago(
            uuid.UUID(str(creado["id"])), str(creado["token_publico"])
        )
        vista = await cliente.get(f"{PAGAR_URL}/{token}?firma={firma}")
        assert vista.status_code == 200
        assert vista.json()["estado_pago"] == "rechazado"
        assert vista.json()["init_point"]
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
            assert turno is not None and turno.estado == "reservado"
    finally:
        await _limpiar_prestacion(pid)


async def test_reintento_tras_rechazo_no_duplica_pendiente(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: pago rechazado ya visible en el link.
    mp_id = "pay-ficticio-reintento-0002"
    pid = await _prestacion_sena("Endodoncia Reintento Ficticia")
    mp_fake.programar_pago(mp_id, estado="rechazado")
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(11, 0).replace(day=9), pid)
        crudo, cabeceras = _aviso_firmado(mp_id)
        aviso = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)
        assert aviso.status_code == 200
        token, firma = extraer_token_pago(
            uuid.UUID(str(creado["id"])), str(creado["token_publico"])
        )

        # Act: reintentar con el mismo link dos veces.
        primero = await cliente.get(f"{PAGAR_URL}/{token}?firma={firma}")
        segundo = await cliente.get(f"{PAGAR_URL}/{token}?firma={firma}")

        # Assert: mismo link vigente y jamás dos pendientes por turno.
        assert primero.status_code == 200
        assert segundo.status_code == 200
        assert primero.json()["init_point"] == segundo.json()["init_point"]
        async with TestSession() as sesion:
            n = await sesion.scalar(
                text(
                    "SELECT count(*) FROM pago WHERE turno_id = :tid "
                    "AND estado = 'pendiente'"
                ),
                {"tid": uuid.UUID(str(creado["id"]))},
            )
            assert int(n or 0) <= 1
    finally:
        await _limpiar_prestacion(pid)


async def test_confirmar_con_sena_pendiente_sigue_422_hasta_acreditar(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: turno con seña sin pago acreditado (regresión C-05).
    mp_id = "pay-ficticio-sena422-0003"
    pid = await _prestacion_sena("Endodoncia Sena 422 Ficticia")
    mp_fake.programar_pago(mp_id, estado="aprobado")
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(12, 0).replace(day=9), pid)
        url_confirmar = f"{CONFIRMAR_URL}/{creado['token_publico']}/confirmar"

        # Act: confirmar antes de acreditar.
        antes = await cliente.post(url_confirmar)

        # Assert: 422 `sena_pendiente` con link, estado intacto...
        assert antes.status_code == 422
        assert antes.json()["problema"] == "sena_pendiente"
        assert antes.json()["url_pago"]

        # ...y tras acreditar vía webhook el turno queda confirmado.
        crudo, cabeceras = _aviso_firmado(mp_id)
        aviso = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)
        assert aviso.status_code == 200
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
            assert turno is not None and turno.estado == "confirmado"
    finally:
        await _limpiar_prestacion(pid)


async def test_mp_caido_degrada_a_manual_sin_perder_turno(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: MP caído (el Fake levanta `FakeMPError` en todo llamado).
    mp_id = "pay-ficticio-caido-0004"
    pid = await _prestacion_sena("Endodoncia MP Caído Ficticia")
    mp_fake.programar_caida()
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(13, 0).replace(day=9), pid)
        crudo, cabeceras = _aviso_firmado(mp_id)

        # Act: aviso que no puede confirmarse contra MP.
        respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

        # Assert: degrada a manual — turno `reservado`, nada acreditado por
        # defecto, respuesta sin PII (acepta 200/502/503 según GREEN).
        assert respuesta.status_code in (200, 502, 503)
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
            assert turno is not None and turno.estado == "reservado"
            n = await sesion.scalar(
                text(
                    "SELECT count(*) FROM pago WHERE turno_id = :tid "
                    "AND estado = 'acreditado'"
                ),
                {"tid": uuid.UUID(str(creado["id"]))},
            )
            assert int(n or 0) == 0
        assert "pagador.sintetico" not in respuesta.text
    finally:
        await _limpiar_prestacion(pid)
