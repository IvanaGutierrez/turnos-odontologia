"""C-08 TRIANGULATE: bordes del dominio nuevo no cubiertos por el RED (R5).

Escenarios deterministas (Fake MP programable, datos sintéticos R0):
- `GET` tras acreditar expone `acreditado`; `GET` con MP caído → `503`
  pinneado sin perder el turno; `GET` sin seña → `422`; rate → `429`.
- Webhook: pago desconocido → `200` a conciliar; estado `pendiente` en
  MP (o desconocido) → `200` sin mutar; sin candidato / monto distinto
  / ambigüedad → `200` sin atribuir dinero a ciegas (CRITICO).
- Reclamo del pendiente creado por el link (flujo GET→pago) y del
  pendiente que ya porta `mp_payment_id`, sin duplicar.
- Cuerpo firmado fuera de esquema o no-JSON → `401` ciego.
- Resolución por `metadata` y comprobante idempotente a nivel servicio.

Type hints siempre (R1); sin PII en asserts (R6); secretos solo env (R7).
"""

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, text

from app.core.security import hashear_password
from app.models.entidades import Prestacion, Turno, Usuario
from app.models.pago import Pago
from app.services.pagos import (
    _insertar_pago,
    encolar_comprobante,
    resolver_turno_para_aviso,
)
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

EMAIL_STAFF = "mp.triangulacion.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Mp-Triangulacion-1234-no-real"

REQUEST_ID_FICTICIO = "req-ficticio-tri-0001"
TS_FICTICIO = "1700000009"


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


async def _prestacion_sena(nombre: str) -> uuid.UUID:
    pid = uuid.uuid4()
    async with TestSession() as sesion:
        sesion.add(
            Prestacion(id=pid, nombre=nombre, duracion_min=45, requiere_sena=True)
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
    cliente: AsyncClient, inicio: datetime, prestacion_id: uuid.UUID | None = None
) -> dict[str, object]:
    access = await _access(cliente)
    extras: dict[str, object] = (
        {"prestacion_id": prestacion_id} if prestacion_id is not None else {}
    )
    creado = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio, **extras),  # type: ignore[arg-type]
        headers={"Authorization": f"Bearer {access}"},
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


async def _contar(consulta: str, params: dict[str, object] | None = None) -> int:
    async with TestSession() as sesion:
        return int(await sesion.scalar(text(consulta), params or {}) or 0)


async def test_get_tras_acreditar_expone_acreditado(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: turno con seña acreditado vía webhook (sin GET previo).
    mp_id = "pay-ficticio-tri-acred-0001"
    pid = await _prestacion_sena("Endodoncia Tri Acreditado Ficticia")
    mp_fake.programar_pago(mp_id, estado="aprobado")
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(10, 0).replace(day=10), pid)
        crudo, cabeceras = _aviso_firmado(mp_id)
        aviso = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)
        assert aviso.status_code == 200
        token, firma = extraer_token_pago(
            uuid.UUID(str(creado["id"])), str(creado["token_publico"])
        )

        # Act: abrir el link tras acreditar.
        vista = await cliente.get(f"{PAGAR_URL}/{token}?firma={firma}")

        # Assert: visible como acreditado, turno confirmado.
        assert vista.status_code == 200
        assert vista.json()["estado_pago"] == "acreditado"
        assert float(vista.json()["monto"]) == float(MONTO_SENA_FIJO_FICTICIO)
    finally:
        await _limpiar_prestacion(pid)


async def test_get_con_mp_caido_503_sin_perder_turno(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: MP caído + turno con seña configurada.
    pid = await _prestacion_sena("Endodoncia Tri Caído Ficticia")
    mp_fake.programar_caida()
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(11, 0).replace(day=10), pid)
        token, firma = extraer_token_pago(
            uuid.UUID(str(creado["id"])), str(creado["token_publico"])
        )

        # Act: abrir el link sin MP.
        vista = await cliente.get(f"{PAGAR_URL}/{token}?firma={firma}")

        # Assert: 503 pinneado — turno reservado, nada acreditado, sin PII.
        assert vista.status_code == 503
        assert "init_point" not in vista.json()
        tid = uuid.UUID(str(creado["id"]))
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, tid)
            assert turno is not None and turno.estado == "reservado"
        assert (
            await _contar(
                "SELECT count(*) FROM pago WHERE turno_id = :tid AND estado = 'pendiente'",
                {"tid": tid},
            )
            == 1
        )
        assert (
            await _contar(
                "SELECT count(*) FROM pago WHERE turno_id = :tid AND estado = 'acreditado'",
                {"tid": tid},
            )
            == 0
        )
        assert (
            await _contar(
                "SELECT count(*) FROM auditoria_log WHERE accion = 'pago_mp_no_disponible'"
            )
            == 1
        )
    finally:
        await _limpiar_prestacion(pid)


async def test_get_turno_sin_sena_422_sin_preferencia(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: turno con prestación SIN seña + Fake inyectado.
    inyectar_mp_fake(app, mp_fake)
    creado = await _crear_turno(cliente, inicio_demo(12, 0).replace(day=10))
    token, firma = extraer_token_pago(
        uuid.UUID(str(creado["id"])), str(creado["token_publico"])
    )

    # Act: abrir el link de un turno sin cobro.
    vista = await cliente.get(f"{PAGAR_URL}/{token}?firma={firma}")

    # Assert: 422 sin preferencia (el Fake no registra llamados).
    assert vista.status_code == 422
    assert vista.json()["problema"] == "sena_sin_configurar"
    prefs = [l for l in mp_fake.llamadas if l["operacion"] == "crear_preferencia"]
    assert prefs == []


async def test_get_rate_limit_429(
    cliente: AsyncClient,
    app: object,
    staff: None,
    mp_fake: FakeMercadoPagoClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange: tope público en 1 + turno con seña.
    monkeypatch.setenv("RATE_PUBLIC_IP_MAX", "1")
    pid = await _prestacion_sena("Endodoncia Tri Rate Ficticia")
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(13, 0).replace(day=10), pid)
        token, firma = extraer_token_pago(
            uuid.UUID(str(creado["id"])), str(creado["token_publico"])
        )

        # Act: dos aperturas seguidas del mismo link.
        primera = await cliente.get(f"{PAGAR_URL}/{token}?firma={firma}")
        segunda = await cliente.get(f"{PAGAR_URL}/{token}?firma={firma}")

        # Assert: la primera pasa y la segunda es 429 con reintento.
        assert primera.status_code == 200
        assert segunda.status_code == 429
        assert segunda.json()["detalle"]
    finally:
        await _limpiar_prestacion(pid)


async def test_webhook_pago_desconocido_200_sin_mutar(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: aviso firmado de un pago que MP no conoce (sin programar).
    mp_id = "pay-ficticio-tri-desconocido-0002"
    pid = await _prestacion_sena("Endodoncia Tri Desconocido Ficticia")
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(10, 0).replace(day=11), pid)
        crudo, cabeceras = _aviso_firmado(mp_id)

        # Act: aviso verificado sin correlato en MP.
        respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

        # Assert: 200 a conciliar manual — nada muta, nada se acredita.
        assert respuesta.status_code == 200
        assert await _contar("SELECT count(*) FROM pago") == 0
        assert (
            await _contar(
                "SELECT count(*) FROM auditoria_log WHERE accion = 'pago_desconocido'"
            )
            == 1
        )
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
            assert turno is not None and turno.estado == "reservado"
    finally:
        await _limpiar_prestacion(pid)


@pytest.mark.parametrize("estado_mp", ["pendiente", "raro-ficticio"])
async def test_webhook_sin_aprobacion_200_sin_mutar(
    cliente: AsyncClient,
    app: object,
    staff: None,
    mp_fake: FakeMercadoPagoClient,
    estado_mp: str,
) -> None:
    # Arrange: MP informa el pago sin aprobar (incl. estado desconocido).
    mp_id = f"pay-ficticio-tri-noaprob-{estado_mp}-0003"
    pid = await _prestacion_sena(f"Endodoncia Tri NoAprob {estado_mp} Ficticia")
    mp_fake.programar_pago(mp_id, estado=estado_mp)
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(11, 0).replace(day=11), pid)
        crudo, cabeceras = _aviso_firmado(mp_id)

        # Act: aviso verificado de pago no aprobado.
        respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

        # Assert: 200 sin acreditar ni rechazar (nunca por defecto).
        assert respuesta.status_code == 200
        assert await _contar("SELECT count(*) FROM pago") == 0
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
            assert turno is not None and turno.estado == "reservado"
    finally:
        await _limpiar_prestacion(pid)


async def test_webhook_sin_candidato_200_a_conciliar(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: turno SIN seña (ningún candidato) + pago aprobado en MP.
    mp_id = "pay-ficticio-tri-sincand-0004"
    mp_fake.programar_pago(mp_id, estado="aprobado")
    inyectar_mp_fake(app, mp_fake)
    creado = await _crear_turno(cliente, inicio_demo(12, 0).replace(day=11))
    crudo, cabeceras = _aviso_firmado(mp_id)

    # Act: aviso verificado sin turno resoluble.
    respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

    # Assert: 200 a conciliar — jamás atribuye a ciegas.
    assert respuesta.status_code == 200
    assert await _contar("SELECT count(*) FROM pago") == 0
    assert (
        await _contar(
            "SELECT count(*) FROM auditoria_log WHERE accion = 'pago_sin_turno'"
        )
        == 1
    )
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
        assert turno is not None and turno.estado == "reservado"


async def test_webhook_monto_distinto_no_vincula(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: único candidato pero MP informa otro monto (5000 vs 9999).
    mp_id = "pay-ficticio-tri-monto-0005"
    pid = await _prestacion_sena("Endodoncia Tri Monto Ficticia")
    mp_fake.programar_pago(mp_id, estado="aprobado", monto=Decimal("9999.00"))
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(13, 0).replace(day=11), pid)
        crudo, cabeceras = _aviso_firmado(mp_id)

        # Act: aviso verificado con monto inconsistente.
        respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

        # Assert: 200 a conciliar — el gate de monto bloquea el vínculo.
        assert respuesta.status_code == 200
        assert await _contar("SELECT count(*) FROM pago") == 0
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
            assert turno is not None and turno.estado == "reservado"
    finally:
        await _limpiar_prestacion(pid)


async def test_webhook_ambiguo_no_atribuye(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: DOS turnos con seña pendiente (ambigüedad deliberada).
    mp_id = "pay-ficticio-tri-ambiguo-0006"
    pid_a = await _prestacion_sena("Endodoncia Tri Ambiguo A Ficticia")
    pid_b = await _prestacion_sena("Endodoncia Tri Ambiguo B Ficticia")
    mp_fake.programar_pago(mp_id, estado="aprobado")
    inyectar_mp_fake(app, mp_fake)
    try:
        turno_a = await _crear_turno(cliente, inicio_demo(10, 0).replace(day=12), pid_a)
        turno_b = await _crear_turno(cliente, inicio_demo(11, 0).replace(day=12), pid_b)
        crudo, cabeceras = _aviso_firmado(mp_id)

        # Act: aviso verificado sin metadata y dos candidatos.
        respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

        # Assert: 200 sin acreditar a ninguno (CRITICO: dinero a ciegas jamás).
        assert respuesta.status_code == 200
        assert (
            await _contar("SELECT count(*) FROM pago WHERE estado = 'acreditado'") == 0
        )
        for creado in (turno_a, turno_b):
            async with TestSession() as sesion:
                turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
                assert turno is not None and turno.estado == "reservado"
    finally:
        await _limpiar_prestacion(pid_a)
        await _limpiar_prestacion(pid_b)


async def test_webhook_reclama_pendiente_del_link(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: link abierto (pendiente + preferencia) y pago aprobado luego.
    mp_id = "pay-ficticio-tri-reclamo-0007"
    pid = await _prestacion_sena("Endodoncia Tri Reclamo Ficticia")
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(12, 0).replace(day=12), pid)
        token, firma = extraer_token_pago(
            uuid.UUID(str(creado["id"])), str(creado["token_publico"])
        )
        vista = await cliente.get(f"{PAGAR_URL}/{token}?firma={firma}")
        assert vista.status_code == 200
        mp_fake.programar_pago(mp_id, estado="aprobado")
        crudo, cabeceras = _aviso_firmado(mp_id)

        # Act: aviso verificado del pago (flujo GET→pago).
        respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

        # Assert: UN solo pago (reclamo, no duplicado) acreditado + turno ok.
        assert respuesta.status_code == 200
        tid = uuid.UUID(str(creado["id"]))
        assert (
            await _contar(
                "SELECT count(*) FROM pago WHERE turno_id = :tid", {"tid": tid}
            )
            == 1
        )
        assert (
            await _contar(
                "SELECT count(*) FROM pago WHERE mp_payment_id = :mp", {"mp": mp_id}
            )
            == 1
        )
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, tid)
            assert turno is not None and turno.estado == "confirmado"
        assert (
            await _contar(
                "SELECT count(*) FROM auditoria_log WHERE accion = 'pago_acreditado'"
            )
            == 1
        )
    finally:
        await _limpiar_prestacion(pid)


async def test_webhook_reclama_pendiente_que_ya_porta_mpid(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: pendiente con `mp_payment_id` precargado directo en DB.
    mp_id = "pay-ficticio-tri-claim-0008"
    pid = await _prestacion_sena("Endodoncia Tri Claim Ficticia")
    mp_fake.programar_pago(mp_id, estado="aprobado")
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(13, 0).replace(day=12), pid)
        tid = uuid.UUID(str(creado["id"]))
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, tid)
            assert turno is not None
            sesion.add(
                Pago(
                    paciente_id=turno.paciente_id,
                    turno_id=tid,
                    monto=MONTO_SENA_FIJO_FICTICIO,
                    moneda="ARS",
                    metodo="mercadopago",
                    estado="pendiente",
                    mp_payment_id=mp_id,
                )
            )
            await sesion.commit()
        crudo, cabeceras = _aviso_firmado(mp_id)

        # Act: aviso verificado del mismo `mp_payment_id`.
        respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

        # Assert: la MISMA fila transiciona (sin duplicar) + turno confirmado.
        assert respuesta.status_code == 200
        assert (
            await _contar(
                "SELECT count(*) FROM pago WHERE mp_payment_id = :mp", {"mp": mp_id}
            )
            == 1
        )
        async with TestSession() as sesion:
            estado = await sesion.scalar(
                text("SELECT estado FROM pago WHERE mp_payment_id = :mp"),
                {"mp": mp_id},
            )
            assert estado == "acreditado"
            turno = await sesion.get(Turno, tid)
            assert turno is not None and turno.estado == "confirmado"
    finally:
        await _limpiar_prestacion(pid)


async def test_webhook_firmado_fuera_de_esquema_401(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: cuerpo firmado pero sin `type` (fuera del esquema estricto).
    mp_id = "pay-ficticio-tri-esquema-0009"
    crudo = json.dumps({"data": {"id": mp_id}}).encode("utf-8")
    cabeceras = {
        "x-signature": firmar_aviso_mp(
            secreto=secreto_mp_prueba(),
            mp_payment_id=mp_id,
            request_id=REQUEST_ID_FICTICIO,
            ts=TS_FICTICIO,
        ),
        "x-request-id": REQUEST_ID_FICTICIO,
        "Content-Type": "application/json",
    }
    pagos_antes = await _contar("SELECT count(*) FROM pago")

    # Act: POST firmado pero no parseable al esquema.
    respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

    # Assert: 401 ciego sin mutar (nunca acredita lo no autenticado).
    assert respuesta.status_code == 401
    assert respuesta.json() == {"detalle": "No autorizado."}
    assert await _contar("SELECT count(*) FROM pago") == pagos_antes


async def test_webhook_cuerpo_no_json_401(cliente: AsyncClient, staff: None) -> None:
    # Arrange: cuerpo que ni siquiera es JSON.
    pagos_antes = await _contar("SELECT count(*) FROM pago")

    # Act: POST con cuerpo opaco y firma cualquiera.
    respuesta = await cliente.post(
        WEBHOOK_URL,
        content=b"no-es-json-ficticio",
        headers={
            "x-signature": "ts=1,v1=abc",
            "x-request-id": REQUEST_ID_FICTICIO,
            "Content-Type": "application/json",
        },
    )

    # Assert: 401 ciego sin mutar.
    assert respuesta.status_code == 401
    assert await _contar("SELECT count(*) FROM pago") == pagos_antes


async def test_resolver_por_metadata_vincula_y_uuid_invalido_no(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno con seña (candidato) para resolución directa.
    pid = await _prestacion_sena("Endodoncia Tri Metadata Ficticia")
    try:
        creado = await _crear_turno(cliente, inicio_demo(10, 0).replace(day=13), pid)
        tid = uuid.UUID(str(creado["id"]))
        async with TestSession() as sesion:
            # Act: metadata con `turno_id` válido, externo e inválido.
            directo = await resolver_turno_para_aviso(
                sesion, {"turno_id": str(tid)}, MONTO_SENA_FIJO_FICTICIO
            )
            externo = await resolver_turno_para_aviso(
                sesion, {"external_reference": str(tid)}, MONTO_SENA_FIJO_FICTICIO
            )
            invalido = await resolver_turno_para_aviso(
                sesion, {"turno_id": "no-es-uuid"}, MONTO_SENA_FIJO_FICTICIO
            )

        # Assert: la metadata manda; el UUID inválido no vincula.
        assert directo is not None and directo.id == tid
        assert externo is not None and externo.id == tid
        assert invalido is None
    finally:
        await _limpiar_prestacion(pid)


async def test_comprobante_idempotente_ante_doble_encolado(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno con seña para el comprobante.
    pid = await _prestacion_sena("Endodoncia Tri Comprobante Ficticia")
    try:
        creado = await _crear_turno(cliente, inicio_demo(11, 0).replace(day=13), pid)
        tid = uuid.UUID(str(creado["id"]))

        # Act: doble encolado del comprobante (carrera simulada).
        async with TestSession() as sesion:
            await encolar_comprobante(
                sesion, turno_id=tid, monto=MONTO_SENA_FIJO_FICTICIO
            )
            await encolar_comprobante(
                sesion, turno_id=tid, monto=MONTO_SENA_FIJO_FICTICIO
            )
            await sesion.commit()

        # Assert: UN solo comprobante (UNIQUE turno+tipo manda).
        assert (
            await _contar(
                "SELECT count(*) FROM aviso_envio WHERE turno_id = :tid "
                "AND tipo_aviso = 'comprobante_pago'",
                {"tid": tid},
            )
            == 1
        )
    finally:
        await _limpiar_prestacion(pid)


async def test_get_sin_firma_404_identico(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: turno con seña + link válido (control) + Fake inyectado.
    pid = await _prestacion_sena("Endodoncia Tri Sin Firma Ficticia")
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(12, 0).replace(day=13), pid)
        token, firma = extraer_token_pago(
            uuid.UUID(str(creado["id"])), str(creado["token_publico"])
        )

        # Act: GET sin `?firma=` + GET con firma ajena.
        sin_firma = await cliente.get(f"{PAGAR_URL}/{token}")
        ajena = await cliente.get(f"{PAGAR_URL}/{token}?firma={'00' * 16}")

        # Assert: ambos 404 idénticos (misma serialización, sin PII).
        assert sin_firma.status_code == 404
        assert ajena.status_code == 404
        assert sin_firma.json() == ajena.json()
        _ = firma
    finally:
        await _limpiar_prestacion(pid)


async def test_get_doble_concurrente_un_solo_pendiente(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: turno con seña sin pagos + Fake inyectado.
    pid = await _prestacion_sena("Endodoncia Tri Concurrente Ficticia")
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(13, 0).replace(day=13), pid)
        token, firma = extraer_token_pago(
            uuid.UUID(str(creado["id"])), str(creado["token_publico"])
        )

        # Act: dos aperturas concurrentes del mismo link.
        primera, segunda = await asyncio.gather(
            cliente.get(f"{PAGAR_URL}/{token}?firma={firma}"),
            cliente.get(f"{PAGAR_URL}/{token}?firma={firma}"),
        )

        # Assert: ambas 200 con el mismo monto y UN solo pendiente
        # (el perdedor reutiliza la fila del ganador, sin excepción).
        assert [primera.status_code, segunda.status_code] == [200, 200]
        assert primera.json()["init_point"]
        assert segunda.json()["init_point"]
        assert float(primera.json()["monto"]) == float(MONTO_SENA_FIJO_FICTICIO)
        assert float(segunda.json()["monto"]) == float(MONTO_SENA_FIJO_FICTICIO)
        tid = uuid.UUID(str(creado["id"]))
        assert (
            await _contar(
                "SELECT count(*) FROM pago WHERE turno_id = :tid", {"tid": tid}
            )
            == 1
        )
    finally:
        await _limpiar_prestacion(pid)


async def test_webhook_firma_malformada_401(cliente: AsyncClient, staff: None) -> None:
    # Arrange: aviso con `x-signature` sin forma `ts=...,v1=...`.
    mp_id = "pay-ficticio-tri-malformada-0010"
    crudo, cabeceras = _aviso_firmado(mp_id)
    cabeceras["x-signature"] = "basura-sin-igual-ficticia"
    pagos_antes = await _contar("SELECT count(*) FROM pago")

    # Act: POST con firma malformada.
    respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

    # Assert: 401 ciego sin mutar.
    assert respuesta.status_code == 401
    assert respuesta.json() == {"detalle": "No autorizado."}
    assert await _contar("SELECT count(*) FROM pago") == pagos_antes


async def test_webhook_sena_sin_config_no_vincula(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: único candidato con `requiere_sena` pero SIN monto ni %.
    mp_id = "pay-ficticio-tri-sinconf-0011"
    pid = uuid.uuid4()
    async with TestSession() as sesion:
        sesion.add(
            Prestacion(
                id=pid,
                nombre="Endodoncia Tri Sin Config Ficticia",
                duracion_min=45,
                requiere_sena=True,
            )
        )
        await sesion.commit()
    mp_fake.programar_pago(mp_id, estado="aprobado")
    inyectar_mp_fake(app, mp_fake)
    try:
        creado = await _crear_turno(cliente, inicio_demo(10, 0).replace(day=14), pid)
        crudo, cabeceras = _aviso_firmado(mp_id)

        # Act: aviso verificado de pago aprobado.
        respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

        # Assert: 200 a conciliar — sin monto calculable no hay vínculo.
        assert respuesta.status_code == 200
        assert await _contar("SELECT count(*) FROM pago") == 0
        assert (
            await _contar(
                "SELECT count(*) FROM auditoria_log WHERE accion = 'pago_sin_turno'"
            )
            == 1
        )
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
            assert turno is not None and turno.estado == "reservado"
    finally:
        await _limpiar_prestacion(pid)


async def test_comprobante_con_redis_caido_no_revierte(
    cliente: AsyncClient,
    staff: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange: turno con seña + Redis que falla al resolver.
    import app.services.pagos as servicio_pagos

    def _sin_redis() -> None:
        raise RuntimeError("redis-caido-ficticio")

    monkeypatch.setattr(servicio_pagos, "obtener_redis", _sin_redis)
    pid = await _prestacion_sena("Endodoncia Tri Redis Ficticia")
    try:
        creado = await _crear_turno(cliente, inicio_demo(11, 0).replace(day=14), pid)
        tid = uuid.UUID(str(creado["id"]))

        # Act: encolar con Redis caído.
        async with TestSession() as sesion:
            await encolar_comprobante(
                sesion, turno_id=tid, monto=MONTO_SENA_FIJO_FICTICIO
            )
            await sesion.commit()

        # Assert: la fila durable existe igual (la DB manda).
        assert (
            await _contar(
                "SELECT count(*) FROM aviso_envio WHERE turno_id = :tid "
                "AND tipo_aviso = 'comprobante_pago'",
                {"tid": tid},
            )
            == 1
        )
    finally:
        await _limpiar_prestacion(pid)


async def test_comprobante_con_push_fallido_no_revierte(
    cliente: AsyncClient,
    staff: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange: turno con seña + Redis que falla al empujar la cola.
    import app.services.pagos as servicio_pagos

    class _RedisRoto:
        async def rpush(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("cola-caida-ficticia")

    monkeypatch.setattr(servicio_pagos, "obtener_redis", lambda: _RedisRoto())
    pid = await _prestacion_sena("Endodoncia Tri Push Ficticia")
    try:
        creado = await _crear_turno(cliente, inicio_demo(12, 0).replace(day=14), pid)
        tid = uuid.UUID(str(creado["id"]))

        # Act: encolar con cola caída (fail-open).
        async with TestSession() as sesion:
            await encolar_comprobante(
                sesion, turno_id=tid, monto=MONTO_SENA_FIJO_FICTICIO
            )
            await sesion.commit()

        # Assert: la fila durable existe igual (el worker drena por DB).
        assert (
            await _contar(
                "SELECT count(*) FROM aviso_envio WHERE turno_id = :tid "
                "AND tipo_aviso = 'comprobante_pago'",
                {"tid": tid},
            )
            == 1
        )
    finally:
        await _limpiar_prestacion(pid)


@pytest.mark.parametrize(
    "cuerpo",
    [b"[1,2,3]", b'{"data": ["no-es-dict"]}'],
)
async def test_webhook_json_no_dict_401(
    cliente: AsyncClient, staff: None, cuerpo: bytes
) -> None:
    # Arrange: cuerpo JSON válido pero sin forma de aviso.
    pagos_antes = await _contar("SELECT count(*) FROM pago")

    # Act: POST con cuerpo no-aviso y firma cualquiera.
    respuesta = await cliente.post(
        WEBHOOK_URL,
        content=cuerpo,
        headers={
            "x-signature": "ts=1,v1=abc",
            "x-request-id": REQUEST_ID_FICTICIO,
            "Content-Type": "application/json",
        },
    )

    # Assert: 401 ciego sin mutar (sin `data.id` no hay nada que autenticar).
    assert respuesta.status_code == 401
    assert await _contar("SELECT count(*) FROM pago") == pagos_antes


async def test_insertar_pago_conflicto_retorna_none(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno con seña para el pago directo a nivel servicio.
    pid = await _prestacion_sena("Endodoncia Tri Insert Ficticia")
    try:
        creado = await _crear_turno(cliente, inicio_demo(13, 0).replace(day=14), pid)
        tid = uuid.UUID(str(creado["id"]))
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, tid)
            assert turno is not None
            paciente_id = turno.paciente_id
        mp_id = "pay-ficticio-tri-insert-0012"

        # Act: doble inserción del mismo `mp_payment_id` en una transacción.
        async with TestSession() as sesion:
            primero = await _insertar_pago(
                sesion,
                paciente_id=paciente_id,
                turno_id=tid,
                monto=MONTO_SENA_FIJO_FICTICIO,
                moneda="ARS",
                mp_payment_id=mp_id,
                objetivo="pendiente",
            )
            segundo = await _insertar_pago(
                sesion,
                paciente_id=paciente_id,
                turno_id=tid,
                monto=MONTO_SENA_FIJO_FICTICIO,
                moneda="ARS",
                mp_payment_id=mp_id,
                objetivo="pendiente",
            )
            await sesion.rollback()

        # Assert: el ganador inserta, el perdedor recibe `None` sin excepción
        # (la sesión sigue sana: `ON CONFLICT DO NOTHING` no envenena).
        assert primero is not None
        assert segundo is None
    finally:
        await _limpiar_prestacion(pid)
