"""C-09 tasks 1.1 RED: movimientos de caja por metodo (R5+R6).

Contrato que la parte 2 (GREEN) debe cumplir:
- `POST /api/v1/caja/movimientos` (JWT `admin|recepcion`) crea UN
  movimiento `{fecha, sede, tipo, concepto 1-280, monto > 0 ARS,
  metodo}` con `usuario_id` del operador → `201` + evento
  `movimiento_registrado` (sin concepto crudo en el diff — R6).
- Metodo fuera del catalogo / monto <= 0 / concepto vacio → `422`
  sin crear movimiento ni evento.
- `GET /api/v1/caja/movimientos?fecha&sede` → `200` con los del dia.
- Sin JWT → `401`; odontologo → `403` generico sin mutar nada.

Estado parte 1: el router NO existe → FALLAN en rojo (`404`).
Todo dato sintetico (R0); type hints siempre (R1).
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, text

from app.models.entidades import Usuario
from tests.conftest import (
    TestSession,
    crear_usuario_ficticio,
    eliminar_usuario_ficticio,
)

pytestmark = pytest.mark.integration

MOVIMIENTOS_URL = "/api/v1/caja/movimientos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_RECEPCION = "caja.recepcion.ficticia@consultorio.example"
EMAIL_ADMIN = "caja.admin.ficticio@consultorio.example"
EMAIL_ODONTOLOGO = "caja.odontologo.ficticio@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Caja-1234-no-real"

FECHA_FICTICIA = "2026-12-10"
SEDE_FICTICIA = "Consultorio"

METODOS_VALIDOS: tuple[str, ...] = (
    "efectivo",
    "transferencia",
    "tarjeta",
    "mercadopago",
)


@pytest_asyncio.fixture()
async def usuarios_caja() -> AsyncGenerator[None, None]:
    """Admin + recepcion + odontologo sinteticos; self-cleanup en RED."""
    await crear_usuario_ficticio(EMAIL_ADMIN, PASSWORD_FICTICIA, "admin")
    await crear_usuario_ficticio(EMAIL_RECEPCION, PASSWORD_FICTICIA, "recepcion")
    await crear_usuario_ficticio(
        EMAIL_ODONTOLOGO, PASSWORD_FICTICIA, "odontologo"
    )
    yield
    for email in (EMAIL_ADMIN, EMAIL_RECEPCION, EMAIL_ODONTOLOGO):
        await eliminar_usuario_ficticio(email)


async def _access_recepcion(cliente: AsyncClient) -> str:
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_RECEPCION, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


def _payload_movimiento(
    metodo: str,
    *,
    tipo: str = "ingreso",
    monto: float = 2500.00,
    concepto: str = "Cobro consulta ficticia",
    fecha: str = FECHA_FICTICIA,
) -> dict[str, object]:
    return {
        "fecha": fecha,
        "sede": SEDE_FICTICIA,
        "tipo": tipo,
        "concepto": concepto,
        "monto": monto,
        "metodo": metodo,
    }


async def _contar_movimientos() -> int:
    async with TestSession() as sesion:
        return int(
            await sesion.scalar(text("SELECT count(*) FROM movimiento_caja")) or 0
        )


async def _eventos_movimiento_registrado() -> list[str]:
    async with TestSession() as sesion:
        filas = (
            await sesion.execute(
                text(
                    "SELECT diff::text FROM auditoria_log "
                    "WHERE accion = 'movimiento_registrado'"
                )
            )
        ).scalars().all()
        return [str(f) for f in filas]


@pytest.mark.parametrize("metodo", METODOS_VALIDOS)
async def test_movimiento_ingreso_por_metodo_201_y_auditado(
    cliente: AsyncClient, usuarios_caja: None, metodo: str
) -> None:
    # Arrange: recepcion autenticada + payload valido del metodo.
    token = await _access_recepcion(cliente)
    cabeceras = {"Authorization": f"Bearer {token}"}

    # Act: registra UN ingreso.
    respuesta = await cliente.post(
        MOVIMIENTOS_URL, json=_payload_movimiento(metodo), headers=cabeceras
    )

    # Assert: 201 con tipo/metodo/monto/usuario_id + evento sin PII.
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["tipo"] == "ingreso"
    assert cuerpo["metodo"] == metodo
    assert float(cuerpo["monto"]) == 2500.00
    async with TestSession() as sesion:
        usuario_id = await sesion.scalar(
            select(Usuario.id).where(Usuario.email == EMAIL_RECEPCION)
        )
        assert usuario_id is not None
        assert cuerpo["usuario_id"] == str(usuario_id)
    eventos = await _eventos_movimiento_registrado()
    assert len(eventos) == 1
    assert metodo in eventos[0]
    assert "Cobro consulta ficticia" not in eventos[0]


async def test_movimiento_egreso_201(
    cliente: AsyncClient, usuarios_caja: None
) -> None:
    # Arrange: recepcion autenticada + egreso en efectivo.
    token = await _access_recepcion(cliente)
    cabeceras = {"Authorization": f"Bearer {token}"}

    # Act: registra UN egreso.
    respuesta = await cliente.post(
        MOVIMIENTOS_URL,
        json=_payload_movimiento(
            "efectivo", tipo="egreso", concepto="Compra insumos ficticia"
        ),
        headers=cabeceras,
    )

    # Assert: 201 con tipo egreso + evento.
    assert respuesta.status_code == 201
    assert respuesta.json()["tipo"] == "egreso"
    assert len(await _eventos_movimiento_registrado()) == 1


async def test_movimiento_metodo_invalido_422_sin_efectos(
    cliente: AsyncClient, usuarios_caja: None
) -> None:
    # Arrange: recepcion autenticada + metodo fuera del catalogo.
    token = await _access_recepcion(cliente)
    cabeceras = {"Authorization": f"Bearer {token}"}

    # Act: metodo 'cheque' (fuera de catalogo).
    respuesta = await cliente.post(
        MOVIMIENTOS_URL, json=_payload_movimiento("cheque"), headers=cabeceras
    )

    # Assert: 422 sin crear movimiento ni evento.
    assert respuesta.status_code == 422
    assert await _contar_movimientos() == 0
    assert await _eventos_movimiento_registrado() == []


@pytest.mark.parametrize(
    "caso",
    [
        {"monto": 0, "concepto": "Monto cero ficticio"},
        {"monto": -1500.00, "concepto": "Monto negativo ficticio"},
        {"monto": 1500.00, "concepto": ""},
    ],
    ids=["monto-cero", "monto-negativo", "concepto-vacio"],
)
async def test_movimiento_monto_no_positivo_o_concepto_vacio_422(
    cliente: AsyncClient, usuarios_caja: None, caso: dict[str, object]
) -> None:
    # Arrange: recepcion autenticada + payload invalido de negocio.
    token = await _access_recepcion(cliente)
    cabeceras = {"Authorization": f"Bearer {token}"}

    # Act: monto <= 0 o concepto vacio.
    respuesta = await cliente.post(
        MOVIMIENTOS_URL,
        json=_payload_movimiento(
            "efectivo",
            monto=float(caso["monto"]),
            concepto=str(caso["concepto"]),
        ),
        headers=cabeceras,
    )

    # Assert: 422 sin efectos.
    assert respuesta.status_code == 422
    assert await _contar_movimientos() == 0
    assert await _eventos_movimiento_registrado() == []


async def test_listar_movimientos_del_dia_200_exactos(
    cliente: AsyncClient, usuarios_caja: None
) -> None:
    # Arrange: 3 movimientos del dia (2 ingresos + 1 egreso).
    token = await _access_recepcion(cliente)
    cabeceras = {"Authorization": f"Bearer {token}"}
    for metodo, tipo, monto in [
        ("efectivo", "ingreso", 2500.00),
        ("tarjeta", "ingreso", 8000.00),
        ("efectivo", "egreso", 1200.00),
    ]:
        previo = await cliente.post(
            MOVIMIENTOS_URL,
            json=_payload_movimiento(
                metodo, tipo=tipo, monto=monto, concepto=f"Ficticio {metodo}"
            ),
            headers=cabeceras,
        )
        assert previo.status_code == 201

    # Act: arqueo del dia (Flujo 6 paso 1).
    respuesta = await cliente.get(
        MOVIMIENTOS_URL,
        params={"fecha": FECHA_FICTICIA, "sede": SEDE_FICTICIA},
        headers=cabeceras,
    )

    # Assert: 200 con exactamente esos 3 movimientos y sus montos.
    assert respuesta.status_code == 200
    movimientos = respuesta.json()
    assert len(movimientos) == 3
    assert sorted(float(m["monto"]) for m in movimientos) == [
        1200.00,
        2500.00,
        8000.00,
    ]


async def test_caja_movimientos_sin_jwt_401(
    cliente: AsyncClient, usuarios_caja: None
) -> None:
    # Arrange: sin credenciales (el movimiento seria valido).

    # Act: POST sin JWT.
    respuesta = await cliente.post(
        MOVIMIENTOS_URL, json=_payload_movimiento("efectivo")
    )

    # Assert: 401 antes de evaluar roles, sin efectos.
    assert respuesta.status_code == 401
    assert await _contar_movimientos() == 0


async def test_odontologo_en_caja_movimientos_403_sin_mutar(
    cliente: AsyncClient, usuarios_caja: None
) -> None:
    # Arrange: JWT con rol odontologo (deny-by-default en caja).
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_ODONTOLOGO, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    cabeceras = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Act: intenta registrar un movimiento.
    respuesta = await cliente.post(
        MOVIMIENTOS_URL, json=_payload_movimiento("efectivo"), headers=cabeceras
    )

    # Assert: 403 generico sin mutar nada.
    assert respuesta.status_code == 403
    assert respuesta.json()["detalle"] == "Sin permiso."
    assert await _contar_movimientos() == 0
    assert await _eventos_movimiento_registrado() == []
