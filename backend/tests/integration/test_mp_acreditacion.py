"""C-08 tasks 1.3+1.5 RED: acreditación idempotente + PII (R5+R6).

Contrato que la parte 2 (GREEN) debe cumplir:
- Aviso verificado de pago **aprobado** (estado confirmado contra MP vía
  el `FakeMercadoPagoClient` inyectado, no solo desde el cuerpo) → en UNA
  transacción: `pago pendiente→acreditado` (+ `webhook_recibido_at`), turno
  con seña `reservado→confirmado` (RN-PA-02), evento de caja
  `pago_acreditado` (payload v1 para C-09) + comprobante WA encolado
  (reusa C-06; WA caído no revierte). Responde `200`.
- Mismo `mp_payment_id` duplicado (secuencial o concurrente) → `200` sin
  doble efecto: UN `acreditado`, UN evento, UN comprobante (RN-PA-03,
  UNIQUE `mp_payment_id` + reclamo por estado).
- Si el cuerpo dice aprobado pero MP dice rechazado → manda MP.
- Logs/auditoría/responses solo con `{pago_id, turno_id, monto, estado,
  mp_payment_id, mp_preference_id}`: jamás email/tarjeta/DNI/teléfono ni
  tokens (R6, Ley 25.326).

Estado parte 1: el router NO existe → FALLAN en rojo (`404`).
Todo dato sintético (R0); type hints siempre (R1).
"""

import asyncio
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
    PAGADOR_DNI_FICTICIO,
    PAGADOR_EMAIL_FICTICIO,
    PAGADOR_TEL_FICTICIO,
    SECRETO_MP_FICTICIO_POR_DEFECTO,
    FakeMercadoPagoClient,
    TestSession,
    cuerpo_aviso_mp,
    firmar_aviso_mp,
    inicio_demo,
    inyectar_mp_fake,
    payload_turno,
    secreto_mp_prueba,
)

pytestmark = pytest.mark.integration

WEBHOOK_URL = "/webhooks/mercadopago"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_STAFF = "mp.acreditacion.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Mp-Acreditacion-1234-no-real"

MP_PAYMENT_FICTICIO = "pay-ficticio-acred-0001"
REQUEST_ID_FICTICIO = "req-ficticio-acred-0001"
TS_FICTICIO = "1700000001"


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


def _post_webhook(
    cliente: AsyncClient, mp_payment_id: str, request_id: str = REQUEST_ID_FICTICIO
) -> tuple[bytes, dict[str, str]]:
    """Aviso firmado con el secreto vigente del runner (R7)."""
    crudo = json.dumps(cuerpo_aviso_mp(mp_payment_id)).encode("utf-8")
    cabeceras = {
        "x-signature": firmar_aviso_mp(
            secreto=secreto_mp_prueba(),
            mp_payment_id=mp_payment_id,
            request_id=request_id,
            ts=TS_FICTICIO,
        ),
        "x-request-id": request_id,
        "Content-Type": "application/json",
    }
    return crudo, cabeceras


async def _pago_por_mp(mp_payment_id: str) -> dict[str, object] | None:
    async with TestSession() as sesion:
        fila = (
            await sesion.execute(
                text(
                    "SELECT estado, turno_id, monto, webhook_recibido_at "
                    "FROM pago WHERE mp_payment_id = :mp"
                ),
                {"mp": mp_payment_id},
            )
        ).mappings().first()
        return dict(fila) if fila is not None else None


async def _eventos_pago_acreditado(turno_id: str) -> list[str]:
    async with TestSession() as sesion:
        filas = (
            await sesion.execute(
                text(
                    "SELECT diff::text FROM auditoria_log "
                    "WHERE accion = 'pago_acreditado'"
                )
            )
        ).scalars().all()
        _ = turno_id
        return [str(f) for f in filas]


async def _avisos_para_turno(turno_id: str) -> int:
    async with TestSession() as sesion:
        return int(
            await sesion.scalar(
                text("SELECT count(*) FROM aviso_envio WHERE turno_id = :tid"),
                {"tid": uuid.UUID(turno_id)},
            )
            or 0
        )


async def test_webhook_valido_acredita_punta_a_punta(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: turno con seña + Fake que confirma el pago como aprobado.
    pid = await _prestacion_sena("Endodoncia Acredita Ficticia")
    mp_fake.programar_pago(
        MP_PAYMENT_FICTICIO, estado="aprobado", monto=MONTO_SENA_FIJO_FICTICIO
    )
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(10, 0).replace(day=8), pid)
        crudo, cabeceras = _post_webhook(cliente, MP_PAYMENT_FICTICIO)

        # Act: aviso verificado de pago aprobado.
        respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

        # Assert: 200 + pago acreditado + turno confirmado + evento + WA.
        assert respuesta.status_code == 200
        pago = await _pago_por_mp(MP_PAYMENT_FICTICIO)
        assert pago is not None and pago["estado"] == "acreditado"
        assert pago["webhook_recibido_at"] is not None
        assert str(pago["turno_id"]) == str(creado["id"])
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
            assert turno is not None and turno.estado == "confirmado"
        eventos = await _eventos_pago_acreditado(str(creado["id"]))
        assert len(eventos) == 1
        assert MP_PAYMENT_FICTICIO in eventos[0]
        assert PAGADOR_EMAIL_FICTICIO not in eventos[0]
        assert await _avisos_para_turno(str(creado["id"])) >= 1
    finally:
        await _limpiar_prestacion(pid)


async def test_estado_manda_mp_no_cuerpo(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: el cuerpo anuncia el pago pero el Fake dice `rechazado`.
    mp_id = "pay-ficticio-diverge-0002"
    pid = await _prestacion_sena("Endodoncia Manda MP Ficticia")
    mp_fake.programar_pago(mp_id, estado="rechazado")
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(11, 0).replace(day=8), pid)
        crudo, cabeceras = _post_webhook(cliente, mp_id)

        # Act: aviso verificado (cuerpo `payment`, MP dice rechazado).
        respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

        # Assert: manda MP — pago `rechazado`, turno sigue pendiente.
        assert respuesta.status_code == 200
        pago = await _pago_por_mp(mp_id)
        assert pago is not None and pago["estado"] == "rechazado"
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
            assert turno is not None and turno.estado == "reservado"
    finally:
        await _limpiar_prestacion(pid)


@pytest.mark.parametrize("modo", ["secuencial", "concurrente"])
async def test_webhook_duplicado_200_sin_doble_efecto(
    cliente: AsyncClient,
    app: object,
    staff: None,
    mp_fake: FakeMercadoPagoClient,
    modo: str,
) -> None:
    # Arrange: turno con seña + pago aprobado en el Fake.
    mp_id = f"pay-ficticio-dupl-{modo}-0003"
    pid = await _prestacion_sena(f"Endodoncia Duplicado {modo.title()} Ficticia")
    mp_fake.programar_pago(mp_id, estado="aprobado")
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(12, 0).replace(day=8), pid)
        crudo, cabeceras = _post_webhook(cliente, mp_id)

        # Act: mismo aviso dos veces (secuencial o concurrente).
        if modo == "secuencial":
            primera = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)
            segunda = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)
        else:
            primera, segunda = await asyncio.gather(
                cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras),
                cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras),
            )

        # Assert: ambas 200, UN acreditado, UN evento, UN comprobante.
        assert [primera.status_code, segunda.status_code] == [200, 200]
        async with TestSession() as sesion:
            n = await sesion.scalar(
                text("SELECT count(*) FROM pago WHERE mp_payment_id = :mp"),
                {"mp": mp_id},
            )
            assert int(n or 0) == 1
        pago = await _pago_por_mp(mp_id)
        assert pago is not None and pago["estado"] == "acreditado"
        assert len(await _eventos_pago_acreditado(str(creado["id"]))) == 1
        assert await _avisos_para_turno(str(creado["id"])) == 1
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
            assert turno is not None and turno.estado == "confirmado"
    finally:
        await _limpiar_prestacion(pid)


async def test_acreditacion_sin_pii_en_responses_auditoria_y_logs(
    cliente: AsyncClient,
    app: object,
    staff: None,
    mp_fake: FakeMercadoPagoClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: flujo de acreditación con PII de pagador en el aviso.
    mp_id = "pay-ficticio-pii-0004"
    pid = await _prestacion_sena("Endodoncia Sin PII Ficticia")
    mp_fake.programar_pago(mp_id, estado="aprobado")
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(13, 0).replace(day=8), pid)
        crudo, cabeceras = _post_webhook(cliente, mp_id)

        # Act: aviso verificado con bloque `pagador` ficticio.
        with caplog.at_level("INFO"):
            respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

        # Assert: 200 y ninguna superficie expone la PII ni el placeholder.
        assert respuesta.status_code == 200
        superficies = [respuesta.text, caplog.text]
        superficies += await _eventos_pago_acreditado(str(creado["id"]))
        for superficie in superficies:
            assert PAGADOR_EMAIL_FICTICIO not in superficie
            assert PAGADOR_TEL_FICTICIO not in superficie
            assert PAGADOR_DNI_FICTICIO not in superficie
            assert SECRETO_MP_FICTICIO_POR_DEFECTO not in superficie
        assert PAGADOR_EMAIL_FICTICIO not in json.dumps(
            (await _pago_por_mp(mp_id)) or {}, default=str
        )
    finally:
        await _limpiar_prestacion(pid)
