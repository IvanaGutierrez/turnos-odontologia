"""C-14 task 1.2 RED: cancelación → scoring + blast top-N + asignación (R5).

Contrato que la parte 2 (GREEN) debe cumplir (`agenda/lista-espera`):
- Toda cancelación (`cancelado` por token C-05) de un turno futuro
  publica el hueco y ranquea elegibles (`activa` + ventana que cubre +
  misma `prestacion_id`) con
  `score = 100*(P_VENT*w_vent + P_HIST*w_hist + P_VALOR*w_valor)`
  (desempate `created_at` ASC), persistiendo `score` + componentes.
- Crea una `OfertaEspera pendiente` (`expira_at = ahora + TTL`) por
  cada uno del top-N (`LISTA_ESPERA_TOP_N`, default 3): esas entradas
  → `ofertada` + blast WhatsApp con link de seña + `oferta_enviada`.
- Sin elegibles: cero ofertas, cero mensajes, hueco reservable.
- Oferta aceptada (primer webhook acreditado): entrada `asignada` +
  turno `canal=lista_espera` + `pago_acreditado` + comprobante WA +
  `aviso_a_recepcion` visible en la grilla de recepción.
- Ventana vencida: la entrada → `expirada` sin blast ni mensajes.

Estado parte 1: ni worker ni webhook con oferta existen → FALLAN (`404`
en altas, cero ofertas tras cancelar, `sin_turno` en el webhook).
Todo dato sintético (R0); type hints siempre (R1); AAA.
"""

from __future__ import annotations

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
from sqlalchemy import text

from app.models.entidades import Prestacion, Turno
from tests.conftest import (
    DNI_ESPERA_FICTICIO_1,
    DNI_ESPERA_FICTICIO_2,
    DNI_ESPERA_FICTICIO_3,
    DNI_ESPERA_FICTICIO_4,
    ID_PACIENTE_DEMO,
    ID_PROFESIONAL_A,
    ID_PROFESIONAL_B,
    ID_SILLON_S1,
    ID_SILLON_S2,
    LISTA_ESPERA_URL,
    FakeMercadoPagoClient,
    TEL_ESPERA_FICTICIO_1,
    TEL_ESPERA_FICTICIO_2,
    TEL_ESPERA_FICTICIO_3,
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

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime(2026, 10, 20, 10, 0, tzinfo=BA)

TURNOS_URL = "/api/v1/turnos"
AUTOGESTION_URL = "/api/v1/turnos/publicos"
AGENDA_URL = "/api/v1/agenda"
AUDITORIA_URL = "/api/v1/auditoria"
WEBHOOK_URL = "/webhooks/mercadopago"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_ADMIN = "espera.oferta.admin.ficticio@consultorio.example"
EMAIL_RECEPCION = "espera.oferta.recepcion.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Espera-Oferta-1234-no-real"

HUECO = datetime(2026, 11, 18, 10, 0, tzinfo=BA)  # slot ofertado (45 min)
SENA_MEDIA = Decimal("5000.00")


@pytest_asyncio.fixture()
async def staff() -> AsyncGenerator[None, None]:
    """Admin + recepción ficticios; self-cleanup en RED."""
    await crear_usuario_ficticio(EMAIL_ADMIN, PASSWORD_FICTICIA, "admin")
    await crear_usuario_ficticio(EMAIL_RECEPCION, PASSWORD_FICTICIA, "recepcion")
    yield
    for email in (EMAIL_ADMIN, EMAIL_RECEPCION):
        await eliminar_usuario_ficticio(email)


async def _access(cliente: AsyncClient) -> str:
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_RECEPCION, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


async def _access_admin(cliente: AsyncClient) -> str:
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_ADMIN, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


async def _prestacion_sena(nombre: str, monto: Decimal) -> uuid.UUID:
    """Prestación con seña fija sintética (self-cleanup por el llamante)."""
    pid = uuid.uuid4()
    async with TestSession() as sesion:
        sesion.add(
            Prestacion(
                id=pid,
                nombre=nombre,
                duracion_min=45,
                requiere_sena=True,
                precio_base=Decimal("20000.00"),
                sena_monto_fijo=monto,
            )
        )
        await sesion.commit()
    return pid


async def _limpiar_prestacion(pid: uuid.UUID) -> None:
    async with TestSession() as sesion:
        await sesion.execute(
            text("DELETE FROM oferta_espera WHERE lista_espera_id IN "
                 "(SELECT id FROM lista_espera WHERE prestacion_id = :pid)"),
            {"pid": pid},
        )
        await sesion.execute(
            text("DELETE FROM lista_espera WHERE prestacion_id = :pid"),
            {"pid": pid},
        )
        await sesion.execute(
            text("DELETE FROM pago WHERE turno_id IN "
                 "(SELECT id FROM turno WHERE prestacion_id = :pid)"),
            {"pid": pid},
        )
        await sesion.execute(
            text("DELETE FROM turno WHERE prestacion_id = :pid"), {"pid": pid}
        )
        await sesion.execute(
            text("DELETE FROM prestacion WHERE id = :pid"), {"pid": pid}
        )
        await sesion.commit()


async def _alta_espera(
    cliente: AsyncClient,
    access: str,
    paciente_id: uuid.UUID,
    prestacion_id: uuid.UUID,
    desde: datetime,
    hasta: datetime,
) -> str:
    respuesta = await cliente.post(
        LISTA_ESPERA_URL,
        json={
            "paciente_id": str(paciente_id),
            "prestacion_id": str(prestacion_id),
            "profesional_id": str(ID_PROFESIONAL_A),
            "ventana_desde": desde.isoformat(),
            "ventana_hasta": hasta.isoformat(),
        },
        headers={"Authorization": f"Bearer {access}"},
    )
    assert respuesta.status_code == 201
    return str(respuesta.json()["id"])


async def _crear_y_cancelar_hueco(
    cliente: AsyncClient, access: str, prestacion_id: uuid.UUID, inicio: datetime
) -> dict[str, object]:
    """Turno futuro vía C-01 + cancelación por token (reloj del llamante)."""
    creado = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio, prestacion_id=prestacion_id),
        headers={"Authorization": f"Bearer {access}"},
    )
    assert creado.status_code == 201
    cancelado = await cliente.post(
        f"{AUTOGESTION_URL}/{creado.json()['token_publico']}/cancelar",
        json={"motivo": "Viaje ficticio demo"},
    )
    assert cancelado.status_code == 200
    assert cancelado.json()["estado"] == "cancelado"
    return dict(creado.json())


async def _ofertas() -> list[dict[str, object]]:
    async with TestSession() as sesion:
        filas = (
            await sesion.execute(
                text(
                    "SELECT id, lista_espera_id, estado, expira_at FROM oferta_espera"
                )
            )
        ).mappings().all()
        return [dict(f) for f in filas]


async def _espera(espera_id: str) -> dict[str, object]:
    async with TestSession() as sesion:
        fila = (
            await sesion.execute(
                text(
                    "SELECT id, estado, score, score_componentes::text AS comp "
                    "FROM lista_espera WHERE id = :eid"
                ),
                {"eid": uuid.UUID(espera_id)},
            )
        ).mappings().first()
        assert fila is not None
        return dict(fila)


async def _diffs(accion: str) -> list[str]:
    async with TestSession() as sesion:
        filas = (
            await sesion.execute(
                text("SELECT diff::text FROM auditoria_log WHERE accion = :acc"),
                {"acc": accion},
            )
        ).scalars().all()
        return [str(f) for f in filas]


async def _historial(
    paciente_id: uuid.UUID,
    estados: tuple[str, ...],
    desfase_dias: int = 0,
) -> None:
    """Turnos pasados del paciente (profesional B: sin interferir el slot).

    `desfase_dias` escalona historias de distintos pacientes para que sus
    slots nunca choquen con el GiST anti-solapamiento (R3).
    """
    base = datetime(2026, 9, 2, 9, 0, tzinfo=BA) + timedelta(days=desfase_dias)
    async with TestSession() as sesion:
        for i, estado in enumerate(estados):
            inicio = base + timedelta(days=i * 3)
            sesion.add(
                Turno(
                    paciente_id=paciente_id,
                    profesional_id=ID_PROFESIONAL_B,
                    sillon_id=ID_SILLON_S2,
                    prestacion_id=(
                        await sesion.execute(
                            text("SELECT id FROM prestacion LIMIT 1")
                        )
                    ).scalar_one(),
                    inicio=inicio,
                    fin=inicio + timedelta(minutes=30),
                    estado=estado,
                    canal="mostrador",
                    token_publico=f"hist-ficticio-{paciente_id.hex[:8]}-{i:02d}",
                )
            )
        await sesion.commit()


async def test_cancelacion_dispara_scoring_y_blast_top_n(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: prestación con seña + 4 pacientes con perfiles escalonados
    # (E1 mejor ventana+historial; E2 peor; E3/E4 empate — dirime antigüedad).
    # NOTA: misma `prestacion_id` en las 4 (elegibilidad): P_VALOR es
    # constante intra-hueco y solo se verifica su componente persistido.
    pid = await _prestacion_sena("Limpieza Espera TopN Ficticia", SENA_MEDIA)
    try:
        access = await _access(cliente)
        p1 = await crear_paciente_espera(
            nombre="Espera Uno Ficticia",
            dni=DNI_ESPERA_FICTICIO_1,
            telefono=TEL_ESPERA_FICTICIO_1,
        )
        p2 = await crear_paciente_espera(
            nombre="Espera Dos Ficticia",
            dni=DNI_ESPERA_FICTICIO_2,
            telefono=TEL_ESPERA_FICTICIO_2,
        )
        p3 = await crear_paciente_espera(
            nombre="Espera Tres Ficticia",
            dni=DNI_ESPERA_FICTICIO_3,
            telefono=TEL_ESPERA_FICTICIO_3,
        )
        p4 = await crear_paciente_espera(
            nombre="Espera Cuatro Ficticia", dni=DNI_ESPERA_FICTICIO_4,
            telefono="+54 9 11 5000-0044",
        )
        await _historial(p1, ("atendido", "atendido", "atendido"))
        await _historial(
            p2, ("atendido", "ausente", "ausente", "ausente"), desfase_dias=1
        )
        e1 = await _alta_espera(
            cliente, access, p1, pid, HUECO - timedelta(hours=2), HUECO + timedelta(days=7)
        )
        e2 = await _alta_espera(
            cliente, access, p2, pid, HUECO - timedelta(days=60), HUECO + timedelta(days=60)
        )
        e3 = await _alta_espera(
            cliente, access, p3, pid, HUECO - timedelta(days=7), HUECO + timedelta(days=7)
        )
        e4 = await _alta_espera(
            cliente, access, p4, pid, HUECO - timedelta(days=7), HUECO + timedelta(days=7)
        )
        async with TestSession() as sesion:  # antigüedad determinista E3 < E4
            base = datetime(2026, 10, 1, 10, 0, tzinfo=BA)
            for eid, horas in ((e1, -2), (e3, 0), (e4, 1), (e2, 2)):
                await sesion.execute(
                    text("UPDATE lista_espera SET creado_en = :c WHERE id = :eid"),
                    {"c": base + timedelta(hours=horas), "eid": uuid.UUID(eid)},
                )
            await sesion.commit()

        # Act: cancelar el turno futuro (reloj controlado: fija el TTL).
        # El JWT se emite DENTRO del freeze: el reloj salta al futuro y
        # un token emitido antes estaría vencido (`exp` manda, 401).
        with freeze_time(AHORA):
            access_fresco = await _access(cliente)
            await _crear_y_cancelar_hueco(cliente, access_fresco, pid, HUECO)

        # Assert: top-3 ofertado con oferta pendiente expirable + score.
        ofertas = await _ofertas()
        assert len(ofertas) == 3  # LISTA_ESPERA_TOP_N default (design §5)
        assert {str(o["estado"]) for o in ofertas} == {"pendiente"}
        for oferta in ofertas:
            expira = oferta["expira_at"]
            assert isinstance(expira, datetime)
            assert expira == AHORA + timedelta(minutes=30)  # TTL default
        ofertadas = {str(o["lista_espera_id"]) for o in ofertas}
        assert ofertadas == {e1, e3, e4}
        s1 = await _espera(e1)
        s3 = await _espera(e3)
        s4 = await _espera(e4)
        s2 = await _espera(e2)
        assert (s1["estado"], s3["estado"], s4["estado"]) == (
            "ofertada", "ofertada", "ofertada",
        )
        assert s2["estado"] == "activa"
        assert float(s1["score"]) > float(s3["score"]) == float(s4["score"])
        assert float(s4["score"]) > float(s2["score"])
        for s in (s1, s3, s4, s2):
            comp = json.loads(str(s["comp"]))
            assert {"p_vent", "p_hist", "p_valor"} <= set(comp)
            assert 0.0 < float(comp["p_valor"]) <= 1.0
        enviadas = await _diffs("oferta_enviada")
        assert len(enviadas) == 3
        superficies = " ".join(enviadas)
        for sonda in (
            DNI_ESPERA_FICTICIO_1, DNI_ESPERA_FICTICIO_2,
            TEL_ESPERA_FICTICIO_1, TEL_ESPERA_FICTICIO_2,
        ):
            assert sonda not in superficies
    finally:
        await _limpiar_prestacion(pid)


async def test_sin_elegibles_hueco_libre_sin_ruido(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: espera en OTRA prestación (no cubre el hueco) + turno futuro.
    pid_hueco = await _prestacion_sena("Limpieza Hueco Libre Ficticia", SENA_MEDIA)
    pid_otra = await _prestacion_sena("Consulta Otra Ficticia", SENA_MEDIA)
    try:
        access = await _access(cliente)
        await _alta_espera(
            cliente, access, ID_PACIENTE_DEMO, pid_otra,
            HUECO - timedelta(days=1), HUECO + timedelta(days=7),
        )

        # Act: cancelar el turno futuro.
        await _crear_y_cancelar_hueco(cliente, access, pid_hueco, HUECO + timedelta(days=1))

        # Assert: cero ofertas, cero mensajes; el hueco sigue reservable.
        assert await _ofertas() == []
        assert await _diffs("oferta_enviada") == []
        rebook = await cliente.post(
            TURNOS_URL,
            json=payload_turno(HUECO + timedelta(days=1), prestacion_id=pid_hueco),
            headers={"Authorization": f"Bearer {access}"},
        )
        assert rebook.status_code == 201
    finally:
        await _limpiar_prestacion(pid_hueco)
        await _limpiar_prestacion(pid_otra)


async def test_oferta_aceptada_asigna_turno_sena_y_aviso(
    cliente: AsyncClient, staff: None, app: object
) -> None:
    # Arrange: entrada + oferta pendiente vigente (snapshot del slot libre)
    # + pago aprobado en el Fake con `metadata.oferta_espera_id`.
    pid = await _prestacion_sena("Limpieza Acepta Ficticia", SENA_MEDIA)
    fake = FakeMercadoPagoClient()
    try:
        access = await _access(cliente)
        admin = await _access_admin(cliente)
        pac = await crear_paciente_espera(
            nombre="Espera Acepta Ficticia",
            dni=DNI_ESPERA_FICTICIO_1,
            telefono=TEL_ESPERA_FICTICIO_1,
        )
        espera_id = await _alta_espera(
            cliente, access, pac, pid, HUECO - timedelta(days=1), HUECO + timedelta(days=7)
        )
        hueco_id = uuid.uuid4()
        oferta_id = uuid.uuid4()
        async with TestSession() as sesion:
            await sesion.execute(
                text(
                    "INSERT INTO oferta_espera (id, lista_espera_id, hueco_origen_id,"
                    " profesional_id, sillon_id, inicio, fin, expira_at, estado)"
                    " VALUES (:oid, :eid, :hid, :prof, :sil, :ini, :fin, :exp,'pendiente')"
                ),
                {
                    "oid": oferta_id, "eid": uuid.UUID(espera_id), "hid": hueco_id,
                    "prof": ID_PROFESIONAL_A, "sil": ID_SILLON_S1,
                    "ini": HUECO, "fin": HUECO + timedelta(minutes=45),
                    "exp": datetime.now(BA) + timedelta(minutes=30),
                },
            )
            await sesion.execute(
                text("UPDATE lista_espera SET estado = 'ofertada' WHERE id = :eid"),
                {"eid": uuid.UUID(espera_id)},
            )
            await sesion.commit()
        mp_id = "pay-ficticio-espera-acepta-0001"
        fake.programar_pago(
            mp_id, estado="aprobado", monto=SENA_MEDIA,
            metadata={"oferta_espera_id": str(oferta_id)},
        )
        inyectar_mp_fake(app, fake)
        crudo = json.dumps(cuerpo_aviso_mp(mp_id)).encode("utf-8")
        cabeceras = {
            "x-signature": firmar_aviso_mp(
                secreto=secreto_mp_prueba(), mp_payment_id=mp_id,
                request_id="req-espera-acepta-0001", ts="1700000101",
            ),
            "x-request-id": "req-espera-acepta-0001",
            "Content-Type": "application/json",
        }

        # Act: webhook acreditado con oferta vigente.
        respuesta = await cliente.post(WEBHOOK_URL, content=crudo, headers=cabeceras)

        # Assert: aceptada + turno canal=lista_espera + caja + recepción.
        assert respuesta.status_code == 200
        async with TestSession() as sesion:
            estado_oferta = await sesion.scalar(
                text("SELECT estado FROM oferta_espera WHERE id = :oid"),
                {"oid": oferta_id},
            )
            assert estado_oferta == "aceptada"
            estado_espera = await sesion.scalar(
                text("SELECT estado FROM lista_espera WHERE id = :eid"),
                {"eid": uuid.UUID(espera_id)},
            )
            assert estado_espera == "asignada"
            turno_id = await sesion.scalar(
                text(
                    "SELECT id FROM turno WHERE profesional_id = :prof "
                    "AND inicio = :ini AND canal = 'lista_espera'"
                ),
                {"prof": ID_PROFESIONAL_A, "ini": HUECO},
            )
            assert turno_id is not None
            pago_estado = await sesion.scalar(
                text("SELECT estado FROM pago WHERE mp_payment_id = :mp"),
                {"mp": mp_id},
            )
            assert pago_estado == "acreditado"
        assert len(await _diffs("pago_acreditado")) >= 1
        assert len(await _diffs("lista_espera_asignada")) == 1
        assert len(await _diffs("aviso_a_recepcion")) >= 1
        grilla = await cliente.get(
            AGENDA_URL,
            params={"vista": "dia", "desde": "2026-11-18T00:00:00-03:00"},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert grilla.status_code == 200
        assert any(
            t.get("canal") == "lista_espera" for t in grilla.json()
        )
        _ = admin
    finally:
        await _limpiar_prestacion(pid)


async def test_ventana_vencida_expira_sin_blast(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: entrada con ventana ya vencida (directo en DB: la API
    # rechaza el alta pasada con 422) + turno futuro a cancelar.
    pid = await _prestacion_sena("Limpieza Vencida Ficticia", SENA_MEDIA)
    try:
        access = await _access(cliente)
        pac = await crear_paciente_espera(
            nombre="Espera Vencida Ficticia",
            dni=DNI_ESPERA_FICTICIO_2,
            telefono=TEL_ESPERA_FICTICIO_2,
        )
        espera_id = uuid.uuid4()
        async with TestSession() as sesion:
            await sesion.execute(
                text(
                    "INSERT INTO lista_espera (id, paciente_id, prestacion_id,"
                    " profesional_id, ventana_desde, ventana_hasta, estado)"
                    " VALUES (:eid, :pac, :pid, :prof, :d, :h, 'activa')"
                ),
                {
                    "eid": espera_id, "pac": pac, "pid": pid,
                    "prof": ID_PROFESIONAL_A,
                    "d": datetime(2026, 1, 5, 9, 0, tzinfo=BA),
                    "h": datetime(2026, 1, 6, 18, 0, tzinfo=BA),
                },
            )
            await sesion.commit()

        # Act: cancelar un turno futuro de la misma prestación.
        await _crear_y_cancelar_hueco(cliente, access, pid, HUECO + timedelta(days=2))

        # Assert: la entrada expira sin oferta ni mensajes.
        assert await _ofertas() == []
        assert await _diffs("oferta_enviada") == []
        estado = await _espera(str(espera_id))
        assert estado["estado"] == "expirada"
    finally:
        await _limpiar_prestacion(pid)
