"""C-09 tasks 1.2 RED: cierre diario unico con conciliacion (R5).

Contrato que la parte 2 (GREEN) debe cumplir:
- `POST /api/v1/caja/cierre {fecha, sede}` (JWT `admin|recepcion`) en
  UNA transaccion: snapshot de totales por metodo desde los
  movimientos del dia/sede, `acreditado_mp` desde `pago`
  (`estado='acreditado'`, fuente C-08 solo lectura),
  `diferencia = total_mp_movimientos - acreditado_mp` →
  `estado_conciliacion='cuadrado'` si `diferencia == 0` y
  `'con_diferencia'` si no; estado `cerrado` + evento `cierre_creado`.
- Segundo cierre del mismo dia/sede (incluso concurrente) → `409`
  con UN solo renglon y UN solo evento (UNIQUE la DB manda).
- `GET /api/v1/caja/cierre?fecha&sede` → `200` con snapshot o `404`.

Supuesto documentado (parte 2 lo honra en `caja.py`): la fecha
operativa del pago es `webhook_recibido_at` (mediodia UTC = manana
ART, mismo dia calendario).

Estado parte 1: el router NO existe → FALLAN en rojo (`404`).
Todo dato sintetico (R0); type hints siempre (R1).
"""

import asyncio
from collections.abc import AsyncGenerator
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import (
    TestSession,
    crear_pago_acreditado_ficticio,
    crear_usuario_ficticio,
    eliminar_usuario_ficticio,
)

pytestmark = pytest.mark.integration

MOVIMIENTOS_URL = "/api/v1/caja/movimientos"
CIERRE_URL = "/api/v1/caja/cierre"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_RECEPCION = "cierre.recepcion.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Cierre-1234-no-real"

SEDE_FICTICIA = "Consultorio"


def _mediodia_utc(dia: int) -> datetime:
    """Fecha operativa ficticia (mediodia UTC = manana ART, mismo dia)."""
    return datetime(2026, 12, dia, 12, 0, tzinfo=ZoneInfo("UTC"))


def _fecha_iso(dia: int) -> str:
    return f"2026-12-{dia:02d}"


@pytest_asyncio.fixture()
async def recepcion_cierre() -> AsyncGenerator[None, None]:
    """Recepcion sintetica; self-cleanup en RED."""
    await crear_usuario_ficticio(EMAIL_RECEPCION, PASSWORD_FICTICIA, "recepcion")
    yield
    await eliminar_usuario_ficticio(EMAIL_RECEPCION)


async def _cabeceras_recepcion(cliente: AsyncClient) -> dict[str, str]:
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_RECEPCION, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _registrar_movimiento(
    cliente: AsyncClient,
    cabeceras: dict[str, str],
    *,
    dia: int,
    metodo: str,
    monto: Decimal,
    tipo: str = "ingreso",
) -> None:
    previo = await cliente.post(
        MOVIMIENTOS_URL,
        json={
            "fecha": _fecha_iso(dia),
            "sede": SEDE_FICTICIA,
            "tipo": tipo,
            "concepto": f"Movimiento ficticio {metodo} dia {dia}",
            "monto": float(monto),
            "metodo": metodo,
        },
        headers=cabeceras,
    )
    assert previo.status_code == 201


async def _contar_cierres(dia: int) -> int:
    async with TestSession() as sesion:
        return int(
            await sesion.scalar(
                text(
                    "SELECT count(*) FROM cierre_diario "
                    "WHERE fecha = :fecha AND sede = :sede"
                ),
                {"fecha": date(2026, 12, dia), "sede": SEDE_FICTICIA},
            )
            or 0
        )


async def _eventos_cierre_creado() -> list[str]:
    async with TestSession() as sesion:
        filas = (
            await sesion.execute(
                text(
                    "SELECT diff::text FROM auditoria_log "
                    "WHERE accion = 'cierre_creado'"
                )
            )
        ).scalars().all()
        return [str(f) for f in filas]


async def test_cierre_compara_y_marca_diferencia_exacta(
    cliente: AsyncClient, recepcion_cierre: None
) -> None:
    # Arrange: MP declarado $10.000 vs acreditado $8.000 (dia 11).
    dia = 11
    cabeceras = await _cabeceras_recepcion(cliente)
    await _registrar_movimiento(
        cliente, cabeceras, dia=dia, metodo="mercadopago",
        monto=Decimal("10000.00"),
    )
    await crear_pago_acreditado_ficticio(
        monto=Decimal("8000.00"),
        fecha_operativa=_mediodia_utc(dia),
        mp_payment_id="pay-ficticio-cierre-dif-0011",
    )

    # Act: cierra el dia.
    respuesta = await cliente.post(
        CIERRE_URL,
        json={"fecha": _fecha_iso(dia), "sede": SEDE_FICTICIA},
        headers=cabeceras,
    )

    # Assert: 201 con diferencia exacta + snapshot de ambos totales.
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert float(cuerpo["diferencia"]) == 2000.00
    assert cuerpo["estado_conciliacion"] == "con_diferencia"
    assert cuerpo["estado"] == "cerrado"
    assert float(cuerpo["total_mp"]) == 10000.00
    assert float(cuerpo["acreditado_mp"]) == 8000.00
    assert len(await _eventos_cierre_creado()) == 1


async def test_cierre_sin_diferencias_cuadrado(
    cliente: AsyncClient, recepcion_cierre: None
) -> None:
    # Arrange: MP declarado == acreditado ($8.000, dia 12).
    dia = 12
    cabeceras = await _cabeceras_recepcion(cliente)
    await _registrar_movimiento(
        cliente, cabeceras, dia=dia, metodo="mercadopago",
        monto=Decimal("8000.00"),
    )
    await crear_pago_acreditado_ficticio(
        monto=Decimal("8000.00"),
        fecha_operativa=_mediodia_utc(dia),
        mp_payment_id="pay-ficticio-cierre-ok-0012",
    )

    # Act: cierra el dia.
    respuesta = await cliente.post(
        CIERRE_URL,
        json={"fecha": _fecha_iso(dia), "sede": SEDE_FICTICIA},
        headers=cabeceras,
    )

    # Assert: 201 cuadrado con diferencia 0.
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert float(cuerpo["diferencia"]) == 0
    assert cuerpo["estado_conciliacion"] == "cuadrado"


async def test_doble_cierre_secuencial_409_un_renglon(
    cliente: AsyncClient, recepcion_cierre: None
) -> None:
    # Arrange: dia 13 con UN movimiento en efectivo.
    dia = 13
    cabeceras = await _cabeceras_recepcion(cliente)
    await _registrar_movimiento(
        cliente, cabeceras, dia=dia, metodo="efectivo",
        monto=Decimal("2500.00"),
    )

    # Act: dos cierres secuenciales del mismo dia/sede.
    primero = await cliente.post(
        CIERRE_URL,
        json={"fecha": _fecha_iso(dia), "sede": SEDE_FICTICIA},
        headers=cabeceras,
    )
    segundo = await cliente.post(
        CIERRE_URL,
        json={"fecha": _fecha_iso(dia), "sede": SEDE_FICTICIA},
        headers=cabeceras,
    )

    # Assert: 201 + 409, UN renglon y UN evento.
    assert primero.status_code == 201
    assert segundo.status_code == 409
    assert await _contar_cierres(dia) == 1
    assert len(await _eventos_cierre_creado()) == 1


async def test_doble_cierre_concurrente_409_un_renglon(
    cliente: AsyncClient, recepcion_cierre: None
) -> None:
    # Arrange: dia 14 con UN movimiento en efectivo.
    dia = 14
    cabeceras = await _cabeceras_recepcion(cliente)
    await _registrar_movimiento(
        cliente, cabeceras, dia=dia, metodo="efectivo",
        monto=Decimal("3000.00"),
    )

    # Act: dos cierres concurrentes reales del mismo dia/sede.
    primero, segundo = await asyncio.gather(
        cliente.post(
            CIERRE_URL,
            json={"fecha": _fecha_iso(dia), "sede": SEDE_FICTICIA},
            headers=cabeceras,
        ),
        cliente.post(
            CIERRE_URL,
            json={"fecha": _fecha_iso(dia), "sede": SEDE_FICTICIA},
            headers=cabeceras,
        ),
    )

    # Assert: uno 201 y otro 409 (la DB manda), UN renglon, UN evento.
    assert sorted([primero.status_code, segundo.status_code]) == [201, 409]
    assert await _contar_cierres(dia) == 1
    assert len(await _eventos_cierre_creado()) == 1


async def test_consultar_cierre_del_dia_200_con_snapshot(
    cliente: AsyncClient, recepcion_cierre: None
) -> None:
    # Arrange: dia 15 cerrado con efectivo + MP.
    dia = 15
    cabeceras = await _cabeceras_recepcion(cliente)
    await _registrar_movimiento(
        cliente, cabeceras, dia=dia, metodo="efectivo",
        monto=Decimal("2500.00"),
    )
    cierre = await cliente.post(
        CIERRE_URL,
        json={"fecha": _fecha_iso(dia), "sede": SEDE_FICTICIA},
        headers=cabeceras,
    )
    assert cierre.status_code == 201

    # Act: consulta el cierre del dia.
    respuesta = await cliente.get(
        CIERRE_URL,
        params={"fecha": _fecha_iso(dia), "sede": SEDE_FICTICIA},
        headers=cabeceras,
    )

    # Assert: 200 con snapshot, diferencia y estado.
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert float(cuerpo["total_efectivo"]) == 2500.00
    assert cuerpo["estado"] == "cerrado"
    assert "diferencia" in cuerpo


async def test_consultar_cierre_inexistente_404(
    cliente: AsyncClient, recepcion_cierre: None
) -> None:
    # Arrange: recepcion autenticada, dia 16 sin cierre.

    # Act: consulta un dia sin cierre.
    respuesta = await cliente.get(
        CIERRE_URL,
        params={"fecha": _fecha_iso(16), "sede": SEDE_FICTICIA},
        headers=await _cabeceras_recepcion(cliente),
    )

    # Assert: 404 de dominio (no el 404 de ruteo sin `problema`).
    assert respuesta.status_code == 404
    assert respuesta.json()["problema"] == "no_encontrado"
