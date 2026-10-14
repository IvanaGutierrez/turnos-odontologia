"""C-14 task 1.3 RED: concurrencia real + re-oferta + webhook (R5).

Contrato que la parte 2 (GREEN) debe cumplir:
- Doble pago concurrente (threads reales) por el mismo hueco ofertado:
  EXACTAMENTE UNO resulta `aceptada/asignada` con UN turno; el perdedor
  queda `reembolsado` (refund MP ejecutado) + `pago_reembolsado`
  auditado, sin turno y con su entrada de vuelta en `activa` (R3: el
  GiST decide, nunca turno duplicado ni cargo sin turno).
- Slot ocupado por otro canal entre oferta y pago: el `INSERT` choca
  con la exclusión → pagador a `reembolsado`, entrada a `activa`.
- Expiración: el barredor pasa `pendiente` vencida → `expirada`
  (`oferta_expirada`), devuelve su entrada a `activa` y re-oferta al
  siguiente elegible aún no ofertado para ese hueco.
- Webhook: oferta ya resuelta → `200` + `reembolsado` sin turno;
  aviso sin oferta → flujo C-08 clásico intacto.

Estado parte 1: sin reclamo atómico el webhook cae en `sin_turno` y el
barredor no existe (`ModuleNotFoundError`) → FALLAN en rojo.
Todo dato sintético (R0); type hints siempre (R1); AAA.
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tests.conftest import (
    DNI_ESPERA_FICTICIO_1,
    DNI_ESPERA_FICTICIO_2,
    ID_PRESTACION_CONSULTA_30,
    ID_PROFESIONAL_A,
    ID_SILLON_S1,
    TEL_ESPERA_FICTICIO_1,
    TEL_ESPERA_FICTICIO_2,
    FakeMercadoPagoClient,
    FakeWhatsAppTransport,
    TestSession,
    crear_paciente_espera,
    crear_usuario_ficticio,
    cuerpo_aviso_mp,
    eliminar_usuario_ficticio,
    firmar_aviso_mp,
    inyectar_mp_fake,
    payload_turno,
    secreto_mp_prueba,
)
from tests.integration.test_lista_espera_oferta import (
    _alta_espera,
    _crear_y_cancelar_hueco,
    _diffs,
    _limpiar_prestacion,
    _ofertas,
    _prestacion_sena,
)

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
HUECO = datetime(2026, 11, 19, 10, 0, tzinfo=BA)
SENA_MEDIA = Decimal("5000.00")

TURNOS_URL = "/api/v1/turnos"
WEBHOOK_URL = "/webhooks/mercadopago"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_RECEPCION = "espera.concurrencia.recepcion@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Espera-Concur-1234-no-real"


@pytest_asyncio.fixture()
async def staff() -> AsyncGenerator[None, None]:
    """Recepción ficticia; self-cleanup en RED."""
    await crear_usuario_ficticio(EMAIL_RECEPCION, PASSWORD_FICTICIA, "recepcion")
    yield
    await eliminar_usuario_ficticio(EMAIL_RECEPCION)


async def _access(cliente: AsyncClient) -> str:
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_RECEPCION, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


def _cabeceras(mp_id: str, req_id: str, ts: str) -> tuple[bytes, dict[str, str]]:
    crudo = json.dumps(cuerpo_aviso_mp(mp_id)).encode("utf-8")
    cabeceras = {
        "x-signature": firmar_aviso_mp(
            secreto=secreto_mp_prueba(), mp_payment_id=mp_id,
            request_id=req_id, ts=ts,
        ),
        "x-request-id": req_id,
        "Content-Type": "application/json",
    }
    return crudo, cabeceras


async def _sembrar_oferta_pendiente(
    *,
    espera_id: uuid.UUID,
    hueco_id: uuid.UUID,
    inicio: datetime,
    expira: datetime,
) -> uuid.UUID:
    oferta_id = uuid.uuid4()
    async with TestSession() as sesion:
        await sesion.execute(
            text(
                "INSERT INTO oferta_espera (id, lista_espera_id, hueco_origen_id,"
                " profesional_id, sillon_id, inicio, fin, expira_at, estado)"
                " VALUES (:oid, :eid, :hid, :prof, :sil, :ini, :fin, :exp,'pendiente')"
            ),
            {
                "oid": oferta_id, "eid": espera_id, "hid": hueco_id,
                "prof": ID_PROFESIONAL_A, "sil": ID_SILLON_S1,
                "ini": inicio, "fin": inicio + timedelta(minutes=45), "exp": expira,
            },
        )
        await sesion.execute(
            text("UPDATE lista_espera SET estado = 'ofertada' WHERE id = :eid"),
            {"eid": espera_id},
        )
        await sesion.commit()
    return oferta_id


async def test_doble_pago_concurrente_threads_un_solo_ganador(
    app: object, staff: None
) -> None:
    # Arrange: DOS entradas ofertadas del mismo hueco + DOS pagos aprobados
    # en el Fake (uno por ofertado) con su `metadata.oferta_espera_id`.
    pid = await _prestacion_sena("Limpieza Doble Pago Ficticia", SENA_MEDIA)
    fake = FakeMercadoPagoClient()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),  # type: ignore[arg-type]
            base_url="http://test",
        ) as boot:
            access = await _access(boot)
        p1 = await crear_paciente_espera(
            nombre="Espera Gana Ficticia",
            dni=DNI_ESPERA_FICTICIO_1, telefono=TEL_ESPERA_FICTICIO_1,
        )
        p2 = await crear_paciente_espera(
            nombre="Espera Pierde Ficticia",
            dni=DNI_ESPERA_FICTICIO_2, telefono=TEL_ESPERA_FICTICIO_2,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),  # type: ignore[arg-type]
            base_url="http://test",
        ) as cliente:
            cliente.headers["Authorization"] = f"Bearer {access}"
            e1 = await _alta_espera(
                cliente, access, p1, pid, HUECO - timedelta(days=1), HUECO + timedelta(days=7)
            )
            e2 = await _alta_espera(
                cliente, access, p2, pid, HUECO - timedelta(days=1), HUECO + timedelta(days=7)
            )
        hueco_id = uuid.uuid4()
        ahora = datetime.now(BA)
        o1 = await _sembrar_oferta_pendiente(
            espera_id=uuid.UUID(e1), hueco_id=hueco_id,
            inicio=HUECO, expira=ahora + timedelta(minutes=30),
        )
        o2 = await _sembrar_oferta_pendiente(
            espera_id=uuid.UUID(e2), hueco_id=hueco_id,
            inicio=HUECO, expira=ahora + timedelta(minutes=30),
        )
        mp1, mp2 = "pay-ficticio-doble-gana-0001", "pay-ficticio-doble-pierde-0002"
        fake.programar_pago(
            mp1, estado="aprobado", monto=SENA_MEDIA,
            metadata={"oferta_espera_id": str(o1)},
        )
        fake.programar_pago(
            mp2, estado="aprobado", monto=SENA_MEDIA,
            metadata={"oferta_espera_id": str(o2)},
        )
        inyectar_mp_fake(app, fake)
        cuerpo1, cab1 = _cabeceras(mp1, "req-doble-0001", "1700000201")
        cuerpo2, cab2 = _cabeceras(mp2, "req-doble-0002", "1700000202")
        estados: dict[int, int] = {}

        def _post_en_hilo(n: int) -> None:
            async def _run() -> None:
                async with AsyncClient(
                    transport=ASGITransport(app=app),  # type: ignore[arg-type]
                    base_url="http://test",
                ) as c:
                    cuerpo, cab = (cuerpo1, cab1) if n == 0 else (cuerpo2, cab2)
                    r = await c.post(WEBHOOK_URL, content=cuerpo, headers=cab)
                    estados[n] = r.status_code

            asyncio.run(_run())

        # Act: dos pagos acreditados concurrentes en threads reales.
        hilos = [threading.Thread(target=_post_en_hilo, args=(n,)) for n in (0, 1)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(timeout=60)

        # Assert: ambas 200, UN solo turno, UNA asignada, otro reembolsado.
        assert estados == {0: 200, 1: 200}
        async with TestSession() as sesion:
            n_turnos = await sesion.scalar(
                text(
                    "SELECT count(*) FROM turno WHERE profesional_id = :prof "
                    "AND sillon_id = :sil AND inicio = :ini AND estado <> 'cancelado'"
                ),
                {"prof": ID_PROFESIONAL_A, "sil": ID_SILLON_S1, "ini": HUECO},
            )
            assert int(n_turnos or 0) == 1
            n_aceptadas = await sesion.scalar(
                text(
                    "SELECT count(*) FROM oferta_espera WHERE hueco_origen_id = :hid "
                    "AND estado = 'aceptada'"
                ),
                {"hid": hueco_id},
            )
            assert int(n_aceptadas or 0) == 1
            n_asignadas = await sesion.scalar(
                text(
                    "SELECT count(*) FROM lista_espera WHERE id IN (:a, :b) "
                    "AND estado = 'asignada'"
                ),
                {"a": uuid.UUID(e1), "b": uuid.UUID(e2)},
            )
            assert int(n_asignadas or 0) == 1
            reembolsados = (
                await sesion.execute(
                    text("SELECT count(*) FROM pago WHERE estado = 'reembolsado'")
                )
            ).scalar_one()
            assert int(reembolsados or 0) == 1
        assert len(await _diffs("pago_reembolsado")) == 1
        assert len(await _diffs("lista_espera_asignada")) == 1
    finally:
        await _limpiar_prestacion(pid)


async def test_slot_ocupado_por_otro_canal_reembolsa(
    cliente: AsyncClient, app: object, staff: None
) -> None:
    # Arrange: oferta pendiente + el slot se ocupa por mostrador (prestación
    # SIN seña: jamás debe atraer el fallback de vinculación C-08).
    pid = await _prestacion_sena("Limpieza Ocupada Ficticia", SENA_MEDIA)
    fake = FakeMercadoPagoClient()
    try:
        access = await _access(cliente)
        pac = await crear_paciente_espera(
            nombre="Espera Ocupada Ficticia",
            dni=DNI_ESPERA_FICTICIO_1, telefono=TEL_ESPERA_FICTICIO_1,
        )
        espera_id = await _alta_espera(
            cliente, access, pac, pid, HUECO - timedelta(days=1), HUECO + timedelta(days=7)
        )
        hueco_id = uuid.uuid4()
        oferta_id = await _sembrar_oferta_pendiente(
            espera_id=uuid.UUID(espera_id), hueco_id=hueco_id,
            inicio=HUECO, expira=datetime.now(BA) + timedelta(minutes=30),
        )
        ocupado = await cliente.post(
            TURNOS_URL,
            json=payload_turno(HUECO, prestacion_id=ID_PRESTACION_CONSULTA_30),
            headers={"Authorization": f"Bearer {access}"},
        )
        assert ocupado.status_code == 201
        mp_id = "pay-ficticio-ocupado-0003"
        fake.programar_pago(
            mp_id, estado="aprobado", monto=SENA_MEDIA,
            metadata={"oferta_espera_id": str(oferta_id)},
        )
        inyectar_mp_fake(app, fake)

        # Act: el ofertado paga tras ocuparse el slot.
        crudo, cab = _cabeceras(mp_id, "req-ocupado-0003", "1700000203")
        respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cab)

        # Assert: 200 + reembolsado, sin turno duplicado, entrada activa.
        assert respuesta.status_code == 200
        async with TestSession() as sesion:
            n_slot = await sesion.scalar(
                text(
                    "SELECT count(*) FROM turno WHERE profesional_id = :prof "
                    "AND sillon_id = :sil AND inicio = :ini AND estado <> 'cancelado'"
                ),
                {"prof": ID_PROFESIONAL_A, "sil": ID_SILLON_S1, "ini": HUECO},
            )
            assert int(n_slot or 0) == 1  # solo el de mostrador
            pago_estado = await sesion.scalar(
                text("SELECT estado FROM pago WHERE mp_payment_id = :mp"),
                {"mp": mp_id},
            )
            assert pago_estado == "reembolsado"
            estado_espera = await sesion.scalar(
                text("SELECT estado FROM lista_espera WHERE id = :eid"),
                {"eid": uuid.UUID(espera_id)},
            )
            assert estado_espera == "activa"
        assert len(await _diffs("pago_reembolsado")) == 1
    finally:
        await _limpiar_prestacion(pid)


async def test_expiracion_reoferta_al_siguiente(
    cliente: AsyncClient,
    staff: None,
    transporte_fake: FakeWhatsAppTransport,
) -> None:
    # Arrange: 2 entradas, oferta del primero YA vencida (TTL pasado).
    pid = await _prestacion_sena("Limpieza Expira Ficticia", SENA_MEDIA)
    try:
        access = await _access(cliente)
        p1 = await crear_paciente_espera(
            nombre="Espera Expira Uno Ficticia",
            dni=DNI_ESPERA_FICTICIO_1, telefono=TEL_ESPERA_FICTICIO_1,
        )
        p2 = await crear_paciente_espera(
            nombre="Espera Expira Dos Ficticia",
            dni=DNI_ESPERA_FICTICIO_2, telefono=TEL_ESPERA_FICTICIO_2,
        )
        e1 = await _alta_espera(
            cliente, access, p1, pid, HUECO - timedelta(days=1), HUECO + timedelta(days=7)
        )
        e2 = await _alta_espera(
            cliente, access, p2, pid, HUECO - timedelta(days=1), HUECO + timedelta(days=7)
        )
        hueco_id = uuid.uuid4()
        await _sembrar_oferta_pendiente(
            espera_id=uuid.UUID(e1), hueco_id=hueco_id,
            inicio=HUECO, expira=datetime.now(BA) - timedelta(minutes=5),
        )

        # Act: barredor de expiración (seam que GREEN provee en servicio).
        from app.services import lista_espera as svc_lista_espera

        async with TestSession() as sesion:
            await svc_lista_espera.barrer_ofertas_expiradas(
                sesion, transporte_fake
            )
            await sesion.commit()

        # Assert: primera expirada→activa, segunda ofertada con oferta nueva.
        async with TestSession() as sesion:
            est1 = await sesion.scalar(
                text("SELECT estado FROM lista_espera WHERE id = :eid"),
                {"eid": uuid.UUID(e1)},
            )
            est2 = await sesion.scalar(
                text("SELECT estado FROM lista_espera WHERE id = :eid"),
                {"eid": uuid.UUID(e2)},
            )
            assert est1 == "activa"
            assert est2 == "ofertada"
            n_pend = await sesion.scalar(
                text(
                    "SELECT count(*) FROM oferta_espera WHERE hueco_origen_id = :hid "
                    "AND estado = 'pendiente'"
                ),
                {"hid": hueco_id},
            )
            assert int(n_pend or 0) == 1
            nueva_para = await sesion.scalar(
                text(
                    "SELECT lista_espera_id FROM oferta_espera "
                    "WHERE hueco_origen_id = :hid AND estado = 'pendiente'"
                ),
                {"hid": hueco_id},
            )
            assert nueva_para == uuid.UUID(e2)
        assert len(await _diffs("oferta_expirada")) == 1
    finally:
        await _limpiar_prestacion(pid)


async def test_webhook_oferta_tardia_reembolsa_sin_duplicar(
    cliente: AsyncClient, app: object, staff: None
) -> None:
    # Arrange: oferta YA aceptada (ganador previo) + segundo pago tardío.
    pid = await _prestacion_sena("Limpieza Tardia Ficticia", SENA_MEDIA)
    fake = FakeMercadoPagoClient()
    try:
        access = await _access(cliente)
        pac = await crear_paciente_espera(
            nombre="Espera Tardia Ficticia",
            dni=DNI_ESPERA_FICTICIO_1, telefono=TEL_ESPERA_FICTICIO_1,
        )
        espera_id = await _alta_espera(
            cliente, access, pac, pid, HUECO - timedelta(days=1), HUECO + timedelta(days=7)
        )
        hueco_id = uuid.uuid4()
        oferta_id = await _sembrar_oferta_pendiente(
            espera_id=uuid.UUID(espera_id), hueco_id=hueco_id,
            inicio=HUECO, expira=datetime.now(BA) + timedelta(minutes=30),
        )
        async with TestSession() as sesion:  # ganador previo (simula GREEN)
            await sesion.execute(
                text("UPDATE oferta_espera SET estado = 'aceptada' WHERE id = :oid"),
                {"oid": oferta_id},
            )
            await sesion.execute(
                text("UPDATE lista_espera SET estado = 'asignada' WHERE id = :eid"),
                {"eid": uuid.UUID(espera_id)},
            )
            await sesion.commit()
        mp_id = "pay-ficticio-tardio-0004"
        fake.programar_pago(
            mp_id, estado="aprobado", monto=SENA_MEDIA,
            metadata={"oferta_espera_id": str(oferta_id)},
        )
        inyectar_mp_fake(app, fake)

        # Act: aviso acreditado tardío sobre oferta resuelta.
        crudo, cab = _cabeceras(mp_id, "req-tardio-0004", "1700000204")
        respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cab)

        # Assert: 200 + reembolsado auditado, ningún turno nuevo.
        assert respuesta.status_code == 200
        async with TestSession() as sesion:
            pago_estado = await sesion.scalar(
                text("SELECT estado FROM pago WHERE mp_payment_id = :mp"),
                {"mp": mp_id},
            )
            assert pago_estado == "reembolsado"
            n_turnos = await sesion.scalar(
                text(
                    "SELECT count(*) FROM turno WHERE profesional_id = :prof "
                    "AND inicio = :ini AND canal = 'lista_espera'"
                ),
                {"prof": ID_PROFESIONAL_A, "ini": HUECO},
            )
            assert int(n_turnos or 0) == 0
        assert len(await _diffs("pago_reembolsado")) == 1
    finally:
        await _limpiar_prestacion(pid)


async def test_webhook_sin_oferta_flujo_c08_intacto(
    cliente: AsyncClient, app: object, staff: None
) -> None:
    # Arrange: turno con seña (flujo clásico C-08, sin metadata de oferta).
    pid = await _prestacion_sena("Endodoncia Clásica Ficticia", SENA_MEDIA)
    fake = FakeMercadoPagoClient()
    try:
        access = await _access(cliente)
        creado = await cliente.post(
            TURNOS_URL,
            json=payload_turno(HUECO + timedelta(days=3), prestacion_id=pid),
            headers={"Authorization": f"Bearer {access}"},
        )
        assert creado.status_code == 201
        mp_id = "pay-ficticio-clasico-0005"
        fake.programar_pago(mp_id, estado="aprobado", monto=SENA_MEDIA)
        inyectar_mp_fake(app, fake)

        # Act: aviso sin `oferta_espera_id` (idéntico a C-08).
        crudo, cab = _cabeceras(mp_id, "req-clasico-0005", "1700000205")
        respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cab)

        # Assert: comportamiento C-08 vigente (acreditación, sin cambios).
        assert respuesta.status_code == 200
        async with TestSession() as sesion:
            pago_estado = await sesion.scalar(
                text("SELECT estado FROM pago WHERE mp_payment_id = :mp"),
                {"mp": mp_id},
            )
            assert pago_estado == "acreditado"
    finally:
        await _limpiar_prestacion(pid)


async def test_cancelacion_sin_worker_sin_ofertas_pendientes_de_green(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: entrada elegible + turno futuro (documenta el trigger que
    # GREEN debe cablear: hoy cancelar NO crea ofertas todavía).
    pid = await _prestacion_sena("Limpieza Gatillo Ficticia", SENA_MEDIA)
    try:
        access = await _access(cliente)
        pac = await crear_paciente_espera(
            nombre="Espera Gatillo Ficticia",
            dni=DNI_ESPERA_FICTICIO_1, telefono=TEL_ESPERA_FICTICIO_1,
        )
        await _alta_espera(
            cliente, access, pac, pid, HUECO - timedelta(days=1), HUECO + timedelta(days=7)
        )

        # Act: cancelar el turno futuro.
        await _crear_y_cancelar_hueco(cliente, access, pid, HUECO + timedelta(days=4))

        # Assert: el worker GREEN debe crear la oferta (hoy: cero).
        ofertas = await _ofertas()
        assert len(ofertas) >= 1
        assert {str(o["estado"]) for o in ofertas} == {"pendiente"}
    finally:
        await _limpiar_prestacion(pid)
