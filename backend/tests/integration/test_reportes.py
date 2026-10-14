"""C-11 tasks 1.3 RED: reportes operativos con scoping y CSV (R5).

Contrato que la parte 2 (GREEN) debe cumplir:
- `GET /api/v1/reportes/ocupacion?desde&hasta&profesional_id&sillon_id&sede`
  (JWT, recurso `reportes`): por profesional/sillon
  `{turnos_totales, turnos_activos, horas_ocupadas, ocupacion_pct}` en DB;
  admin full, odontologo solo propio (otro id -> 403),
  recepcion solo dia operativo (otro rango -> 403).
- `GET /api/v1/reportes/ausentismo?...`: `{turnos_finalizados, ausentes,
  ausentismo_pct}`; mismo scoping; jamas PII/HCE.
- `GET /api/v1/reportes/ingresos?desde&hasta&sede`: `{por_metodo, total,
  acreditado_mp, diferencia}` desde movimiento_caja + pago acreditado.
- `GET /api/v1/reportes/:tipo.csv` (recurso `reportes_csv`, admin full y
  odontologo propio; recepcion -> 403): `text/csv; charset=utf-8` con BOM,
  separador `,`, headers fijos en espanol, streaming, `Content-Disposition:
  attachment`, evento `reporte_csv_exportado`; jamas PII.

Estado parte 1: routers NO existen -> todo 404 (rojo genuino).
Todo dato sintetico (R0); type hints siempre (R1).
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.auditoria import AuditoriaLog
from app.models.caja import MovimientoCaja
from app.models.entidades import Turno
from app.models.pago import Pago
from tests.conftest import (
    ID_PACIENTE_DEMO,
    ID_PRESTACION_CONSULTA_30,
    ID_PRESTACION_LIMPIEZA_45,
    ID_PROFESIONAL_A,
    ID_PROFESIONAL_B,
    ID_SILLON_S1,
    ID_SILLON_S2,
    TestSession,
    crear_usuario_ficticio,
    eliminar_usuario_ficticio,
)

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")

OCUPACION_URL = "/api/v1/reportes/ocupacion"
AUSENTISMO_URL = "/api/v1/reportes/ausentismo"
INGRESOS_URL = "/api/v1/reportes/ingresos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_ADMIN = "reportes.c11.admin@consultorio.example"
EMAIL_ODONTOLOGO = "reportes.c11.odontologo@consultorio.example"
EMAIL_RECEPCION = "reportes.c11.recepcion@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Rep-C11-0001-no-real"

SEDE_FICTICIA = "Consultorio"

# PII sintetica marcada (del paciente demo + ficticia): jamas en reportes (R6).
DNI_MARCADO = "90876543"
TEL_MARCADO = "+54 9 11 5000-0002"
NOMBRE_MARCADO = "Paciente Demo Ficticia"
EMAIL_MARCADO = "reportes.c11.admin@consultorio.example"

HEADERS_OCUPACION = (
    "periodo_desde,periodo_hasta,dimension,dimension_id,"
    "turnos_totales,turnos_activos,horas_ocupadas,ocupacion_pct"
)
HEADERS_AUSENTISMO = (
    "periodo_desde,periodo_hasta,profesional_id,"
    "turnos_finalizados,ausentes,ausentismo_pct"
)
HEADERS_INGRESOS = (
    "periodo_desde,periodo_hasta,metodo,monto,total,acreditado_mp,diferencia"
)


@pytest_asyncio.fixture()
async def roles_reportes() -> AsyncGenerator[None, None]:
    """Admin + odontologo + recepcion sinteticos; self-cleanup en RED."""
    await crear_usuario_ficticio(EMAIL_ADMIN, PASSWORD_FICTICIA, "admin")
    await crear_usuario_ficticio(EMAIL_ODONTOLOGO, PASSWORD_FICTICIA, "odontologo")
    await crear_usuario_ficticio(EMAIL_RECEPCION, PASSWORD_FICTICIA, "recepcion")
    yield
    for email in (EMAIL_ADMIN, EMAIL_ODONTOLOGO, EMAIL_RECEPCION):
        await eliminar_usuario_ficticio(email)
    async with TestSession() as sesion:
        await sesion.execute(
            delete(AuditoriaLog).where(
                AuditoriaLog.accion.in_(
                    ["reporte_csv_exportado", "acceso_denegado"]
                )
            )
        )
        await sesion.commit()


async def _access_para(cliente: AsyncClient, email: str) -> str:
    # Arrange: login del rol pedido.
    login = await cliente.post(
        LOGIN_URL, json={"email": email, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


async def _crear_turnos_ocupacion() -> None:
    """40 turnos prof-A/S2 (20 activos) + 40 prof-B/S1 (10 activos), nov 2026.

    Activos = `reservado`; inactivos = `cancelado`. Inicios horarios
    distintos (sin solapamiento fisico, R3 intacto).
    """
    base = datetime(2026, 11, 10, 8, 0, tzinfo=BA)
    turnos: list[Turno] = []
    for i in range(40):
        inicio = base + timedelta(hours=i)
        estado = "reservado" if i < 20 else "cancelado"
        turnos.append(
            Turno(
                paciente_id=ID_PACIENTE_DEMO,
                profesional_id=ID_PROFESIONAL_A,
                sillon_id=ID_SILLON_S2,
                prestacion_id=ID_PRESTACION_LIMPIEZA_45,
                inicio=inicio,
                fin=inicio + timedelta(minutes=30),
                estado=estado,
                canal="mostrador",
                token_publico=f"c11-ocu-a-{i:04d}-ficticio-no-real-{uuid.uuid4().hex[:8]}",
            )
        )
    for i in range(40):
        inicio = base + timedelta(hours=i, minutes=15)
        estado = "reservado" if i < 10 else "cancelado"
        turnos.append(
            Turno(
                paciente_id=ID_PACIENTE_DEMO,
                profesional_id=ID_PROFESIONAL_B,
                sillon_id=ID_SILLON_S1,
                prestacion_id=ID_PRESTACION_CONSULTA_30,
                inicio=inicio,
                fin=inicio + timedelta(minutes=30),
                estado=estado,
                canal="mostrador",
                token_publico=f"c11-ocu-s1-{i:04d}-ficticio-no-real-{uuid.uuid4().hex[:8]}",
            )
        )
    async with TestSession() as sesion:
        sesion.add_all(turnos)
        await sesion.commit()


async def _crear_turnos_ausentismo() -> None:
    """90 finalizados (40 presente + 41 atendido + 9 ausente) en noviembre."""
    base = datetime(2026, 11, 3, 8, 0, tzinfo=BA)
    turnos: list[Turno] = []
    for i in range(90):
        if i < 40:
            estado = "presente"
        elif i < 81:
            estado = "atendido"
        else:
            estado = "ausente"
        inicio = base + timedelta(hours=i)
        turnos.append(
            Turno(
                paciente_id=ID_PACIENTE_DEMO,
                profesional_id=ID_PROFESIONAL_A,
                sillon_id=ID_SILLON_S1,
                prestacion_id=ID_PRESTACION_LIMPIEZA_45,
                inicio=inicio,
                fin=inicio + timedelta(minutes=30),
                estado=estado,
                canal="mostrador",
                token_publico=f"c11-aus-{i:04d}-ficticio-no-real-{uuid.uuid4().hex[:8]}",
            )
        )
    async with TestSession() as sesion:
        sesion.add_all(turnos)
        await sesion.commit()


async def _crear_ingresos_dia(dia: date) -> None:
    """Movimientos ficticios + pago acreditado: efectivo 10000, MP 8000/8000."""
    mediodia_utc = datetime(dia.year, dia.month, dia.day, 12, 0, tzinfo=ZoneInfo("UTC"))
    async with TestSession() as sesion:
        sesion.add(
            MovimientoCaja(
                fecha=dia,
                sede=SEDE_FICTICIA,
                tipo="ingreso",
                concepto="Ingreso ficticio C11 en efectivo",
                monto=Decimal("10000.00"),
                metodo="efectivo",
                usuario_id=None,
                pago_id=None,
                origen="manual",
            )
        )
        sesion.add(
            MovimientoCaja(
                fecha=dia,
                sede=SEDE_FICTICIA,
                tipo="ingreso",
                concepto="Ingreso ficticio C11 mercadopago",
                monto=Decimal("8000.00"),
                metodo="mercadopago",
                usuario_id=None,
                pago_id=None,
                origen="manual",
            )
        )
        sesion.add(
            Pago(
                paciente_id=None,
                turno_id=None,
                monto=Decimal("8000.00"),
                moneda="ARS",
                metodo="mercadopago",
                estado="acreditado",
                mp_payment_id=f"pay-ficticio-c11-ing-{dia.isoformat()}",
                mp_preference_id=f"pref-ficticia-c11-ing-{dia.isoformat()}",
                webhook_recibido_at=mediodia_utc,
            )
        )
        await sesion.commit()


def _assert_sin_pii(texto: str) -> None:
    bajo = texto.lower()
    for marcador in (
        DNI_MARCADO.lower(),
        TEL_MARCADO.lower(),
        NOMBRE_MARCADO.lower(),
        "anamnesis",
        "historia_clinica",
        "password_hash",
        "token",
    ):
        assert marcador not in bajo


async def test_ocupacion_numeros_esperados_por_profesional_y_sillon(
    cliente: AsyncClient, roles_reportes: None
) -> None:
    # Arrange: 40/20 en prof-A (50 %) + 40/10 en sillon-1 (25 %).
    await _crear_turnos_ocupacion()
    access = await _access_para(cliente, EMAIL_ADMIN)
    cabeceras = {"Authorization": f"Bearer {access}"}
    # Act: ocupacion semanal admin.
    respuesta = await cliente.get(
        OCUPACION_URL,
        params={"desde": "2026-11-10", "hasta": "2026-11-16"},
        headers=cabeceras,
    )
    # Assert: 200 con 50 % prof-A y 25 % sillon-1, solo IDs y conteos.
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    por_prof = {str(f["profesional_id"]): f for f in cuerpo["por_profesional"]}
    por_sillon = {str(f["sillon_id"]): f for f in cuerpo["por_sillon"]}
    assert por_prof[str(ID_PROFESIONAL_A)]["ocupacion_pct"] == 50
    assert por_prof[str(ID_PROFESIONAL_A)]["turnos_activos"] == 20
    assert por_sillon[str(ID_SILLON_S1)]["ocupacion_pct"] == 25
    assert por_sillon[str(ID_SILLON_S1)]["turnos_activos"] == 10
    _assert_sin_pii(respuesta.text)


async def test_odontologo_ve_propios_y_ajeno_403(
    cliente: AsyncClient, roles_reportes: None
) -> None:
    # Arrange: datos de dos profesionales + JWT odontologo.
    await _crear_turnos_ocupacion()
    access = await _access_para(cliente, EMAIL_ODONTOLOGO)
    cabeceras = {"Authorization": f"Bearer {access}"}
    # Act: sin filtro (propios) + con id ajeno (azar imposible = propio).
    propia = await cliente.get(
        OCUPACION_URL,
        params={"desde": "2026-11-10", "hasta": "2026-11-16"},
        headers=cabeceras,
    )
    ajena = await cliente.get(
        OCUPACION_URL,
        params={
            "desde": "2026-11-10",
            "hasta": "2026-11-16",
            "profesional_id": str(uuid.uuid4()),
        },
        headers=cabeceras,
    )
    # Assert: propia 200 acotada a un profesional; ajena 403 sin datos.
    assert propia.status_code == 200
    cuerpo = propia.json()
    assert len(cuerpo["por_profesional"]) == 1
    assert ajena.status_code == 403


async def test_recepcion_fuera_del_dia_operativo_403(
    cliente: AsyncClient, roles_reportes: None
) -> None:
    # Arrange: JWT recepcion.
    access = await _access_para(cliente, EMAIL_RECEPCION)
    cabeceras = {"Authorization": f"Bearer {access}"}
    # Act: pide semana pasada (fuera de hoy).
    respuesta = await cliente.get(
        OCUPACION_URL,
        params={"desde": "2026-11-10", "hasta": "2026-11-16"},
        headers=cabeceras,
    )
    # Assert: 403 generico sin agregacion.
    assert respuesta.status_code == 403


async def test_ausentismo_10_por_ciento_sin_pii(
    cliente: AsyncClient, roles_reportes: None
) -> None:
    # Arrange: 90 finalizados con 9 ausentes.
    await _crear_turnos_ausentismo()
    access = await _access_para(cliente, EMAIL_ADMIN)
    # Act: ausentismo mensual admin.
    respuesta = await cliente.get(
        AUSENTISMO_URL,
        params={"desde": "2026-11-01", "hasta": "2026-11-30"},
        headers={"Authorization": f"Bearer {access}"},
    )
    # Assert: 200 con 10 %, solo agregados.
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["turnos_finalizados"] == 90
    assert cuerpo["ausentes"] == 9
    assert cuerpo["ausentismo_pct"] == 10
    _assert_sin_pii(respuesta.text)


async def test_ingresos_por_metodo_con_diferencia_cero(
    cliente: AsyncClient, roles_reportes: None
) -> None:
    # Arrange: efectivo 10000 + MP 8000 declarado/acreditado.
    dia = date(2026, 11, 15)
    await _crear_ingresos_dia(dia)
    access = await _access_para(cliente, EMAIL_ADMIN)
    # Act: ingresos del dia.
    respuesta = await cliente.get(
        INGRESOS_URL,
        params={"desde": "2026-11-15", "hasta": "2026-11-15"},
        headers={"Authorization": f"Bearer {access}"},
    )
    # Assert: por_metodo + total 18000 + diferencia 0.
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert float(cuerpo["por_metodo"]["efectivo"]) == 10000.0
    assert float(cuerpo["por_metodo"]["mercadopago"]) == 8000.0
    assert float(cuerpo["total"]) == 18000.0
    assert float(cuerpo["diferencia"]) == 0.0
    _assert_sin_pii(respuesta.text)


async def test_csv_ingresos_headers_bom_y_montos_iguales_json(
    cliente: AsyncClient, roles_reportes: None
) -> None:
    # Arrange: ingresos del dia + JWT admin.
    dia = date(2026, 11, 15)
    await _crear_ingresos_dia(dia)
    access = await _access_para(cliente, EMAIL_ADMIN)
    cabeceras = {"Authorization": f"Bearer {access}"}
    # Act: JSON + CSV del mismo rango.
    json_resp = await cliente.get(
        INGRESOS_URL,
        params={"desde": "2026-11-15", "hasta": "2026-11-15"},
        headers=cabeceras,
    )
    csv_resp = await cliente.get(
        "/api/v1/reportes/ingresos.csv",
        params={"desde": "2026-11-15", "hasta": "2026-11-15"},
        headers=cabeceras,
    )
    # Assert: CSV 200 text/csv con BOM, headers exactos, montos == JSON,
    # Content-Disposition attachment y evento exportado.
    assert json_resp.status_code == 200
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "attachment" in csv_resp.headers["content-disposition"]
    assert csv_resp.content[:3] == b"\xef\xbb\xbf"
    texto = csv_resp.content.decode("utf-8-sig")
    primera = texto.splitlines()[0].strip()
    assert primera == HEADERS_INGRESOS
    assert "8000" in texto and "10000" in texto
    _assert_sin_pii(texto)
    async with TestSession() as sesion:
        eventos = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "reporte_csv_exportado"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(eventos) == 1


async def test_csv_nunca_expone_pii_y_montos_igualan_json(
    cliente: AsyncClient, roles_reportes: None
) -> None:
    # Arrange: ocupacion + ausentismo + ingresos con PII marcada en DB.
    await _crear_turnos_ocupacion()
    await _crear_ingresos_dia(date(2026, 11, 15))
    access = await _access_para(cliente, EMAIL_ADMIN)
    cabeceras = {"Authorization": f"Bearer {access}"}
    # Act: descarga los 3 CSV del dia/semana.
    respuestas = []
    for tipo, params in (
        ("ocupacion", {"desde": "2026-11-10", "hasta": "2026-11-16"}),
        ("ausentismo", {"desde": "2026-11-01", "hasta": "2026-11-30"}),
        ("ingresos", {"desde": "2026-11-15", "hasta": "2026-11-15"}),
    ):
        resp = await cliente.get(
            f"/api/v1/reportes/{tipo}.csv", params=params, headers=cabeceras
        )
        assert resp.status_code == 200
        respuestas.append((tipo, resp))
    # Assert: ningun campo coincide con PII marcada.
    for tipo, resp in respuestas:
        texto = resp.content.decode("utf-8-sig")
        _assert_sin_pii(texto)
        assert EMAIL_MARCADO.lower() not in texto.lower()


async def test_recepcion_pide_csv_403(
    cliente: AsyncClient, roles_reportes: None
) -> None:
    # Arrange: JWT recepcion.
    access = await _access_para(cliente, EMAIL_RECEPCION)
    # Act: cualquier CSV.
    respuesta = await cliente.get(
        "/api/v1/reportes/ingresos.csv",
        params={"desde": "2026-11-15", "hasta": "2026-11-15"},
        headers={"Authorization": f"Bearer {access}"},
    )
    # Assert: 403 generico sin contenido ni evento de exportacion.
    assert respuesta.status_code == 403
    async with TestSession() as sesion:
        eventos = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "reporte_csv_exportado"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert eventos == []
