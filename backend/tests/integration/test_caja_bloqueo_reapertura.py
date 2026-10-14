"""C-09 tasks 1.3 RED: dia cerrado bloqueado + reapertura admin (R5+R6).

Contrato que la parte 2 (GREEN) debe cumplir:
- `POST /movimientos` con fecha de un cierre `cerrado` → `422
  dia_cerrado` sin crear movimiento ni evento; otros dias abiertos
  siguen en `201`.
- `POST /api/v1/caja/reapertura {fecha, sede, motivo >= 10}` revierte
  a `abierto` (`reaperturas+1`) + evento `cierre_reabierto` → `200`;
  SOLO `admin` (recepcion/odontologo → `403` generico + evento
  `reapertura_denegada` con solo `{fecha, sede, usuario_id}`, el
  cierre sigue `cerrado`); sin cierre → `404`; ya abierto → `422`.
- Jamas concepto crudo, DNI, telefonos, HCE ni tokens en logs,
  auditoria ni responses (R6, Ley 25.326): solo IDs, montos, metodos
  y estados.

Estado parte 1: el router NO existe → FALLAN en rojo (`404`).
Todo dato sintetico (R0); type hints siempre (R1).
"""

from collections.abc import AsyncGenerator
from datetime import date

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import (
    TestSession,
    crear_usuario_ficticio,
    eliminar_usuario_ficticio,
)

pytestmark = pytest.mark.integration

MOVIMIENTOS_URL = "/api/v1/caja/movimientos"
CIERRE_URL = "/api/v1/caja/cierre"
REAPERTURA_URL = "/api/v1/caja/reapertura"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_ADMIN = "reapertura.admin.ficticio@consultorio.example"
EMAIL_RECEPCION = "reapertura.recepcion.ficticia@consultorio.example"
EMAIL_ODONTOLOGO = "reapertura.odontologo.ficticio@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Reapertura-1234-no-real"
EMAILS_CAJA = (EMAIL_ADMIN, EMAIL_RECEPCION, EMAIL_ODONTOLOGO)

SEDE_FICTICIA = "Consultorio"
MOTIVO_FICTICIO = "Error de arqueo: falto registrar un cobro en efectivo"

# PII 100 % ficticia (R0+R6): solo prueba que jamas se expone.
DNI_FICTICIO = "90300401"
TEL_FICTICIO = "+54 9 11 5000-0041"
CONCEPTO_SENSIBLE = (
    f"Cobro paciente con dni {DNI_FICTICIO} tel {TEL_FICTICIO} ficticios"
)


@pytest_asyncio.fixture()
async def usuarios_reapertura() -> AsyncGenerator[None, None]:
    """Admin + recepcion + odontologo sinteticos; self-cleanup en RED."""
    await crear_usuario_ficticio(EMAIL_ADMIN, PASSWORD_FICTICIA, "admin")
    await crear_usuario_ficticio(EMAIL_RECEPCION, PASSWORD_FICTICIA, "recepcion")
    await crear_usuario_ficticio(
        EMAIL_ODONTOLOGO, PASSWORD_FICTICIA, "odontologo"
    )
    yield
    for email in EMAILS_CAJA:
        await eliminar_usuario_ficticio(email)


async def _access_para(cliente: AsyncClient, email: str) -> str:
    login = await cliente.post(
        LOGIN_URL, json={"email": email, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


async def _cerrar_dia(
    cliente: AsyncClient, token: str, dia: int
) -> None:
    cierre = await cliente.post(
        CIERRE_URL,
        json={"fecha": f"2026-12-{dia:02d}", "sede": SEDE_FICTICIA},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cierre.status_code == 201


async def _contar_movimientos_dia(dia: int) -> int:
    async with TestSession() as sesion:
        return int(
            await sesion.scalar(
                text(
                    "SELECT count(*) FROM movimiento_caja "
                    "WHERE fecha = :fecha AND sede = :sede"
                ),
                {"fecha": date(2026, 12, dia), "sede": SEDE_FICTICIA},
            )
            or 0
        )


async def _estado_cierre(dia: int) -> str | None:
    async with TestSession() as sesion:
        return await sesion.scalar(
            text(
                "SELECT estado FROM cierre_diario "
                "WHERE fecha = :fecha AND sede = :sede"
            ),
            {"fecha": date(2026, 12, dia), "sede": SEDE_FICTICIA},
        )


async def _eventos_por_accion(accion: str) -> list[str]:
    async with TestSession() as sesion:
        filas = (
            await sesion.execute(
                text(
                    "SELECT diff::text FROM auditoria_log WHERE accion = :accion"
                ),
                {"accion": accion},
            )
        ).scalars().all()
        return [str(f) for f in filas]


async def test_movimiento_en_dia_cerrado_422_y_abierto_201(
    cliente: AsyncClient, usuarios_reapertura: None
) -> None:
    # Arrange: dia 16 cerrado + dia 17 abierto.
    token = await _access_para(cliente, EMAIL_RECEPCION)
    cabeceras = {"Authorization": f"Bearer {token}"}
    await _cerrar_dia(cliente, token, 16)

    # Act: movimiento en cada dia.
    en_cerrado = await cliente.post(
        MOVIMIENTOS_URL,
        json={
            "fecha": "2026-12-16",
            "sede": SEDE_FICTICIA,
            "tipo": "ingreso",
            "concepto": "Cobro tardio ficticio",
            "monto": 2500.00,
            "metodo": "efectivo",
        },
        headers=cabeceras,
    )
    en_abierto = await cliente.post(
        MOVIMIENTOS_URL,
        json={
            "fecha": "2026-12-17",
            "sede": SEDE_FICTICIA,
            "tipo": "ingreso",
            "concepto": "Cobro normal ficticio",
            "monto": 2500.00,
            "metodo": "efectivo",
        },
        headers=cabeceras,
    )

    # Assert: cerrado 422 sin efectos; abierto 201.
    assert en_cerrado.status_code == 422
    assert en_cerrado.json()["detalle"] == "dia_cerrado"
    assert await _contar_movimientos_dia(16) == 0
    assert en_abierto.status_code == 201
    assert await _contar_movimientos_dia(17) == 1


async def test_reapertura_admin_200_auditada_y_movimiento_posterior_201(
    cliente: AsyncClient, usuarios_reapertura: None
) -> None:
    # Arrange: dia 18 cerrado por recepcion.
    token_recep = await _access_para(cliente, EMAIL_RECEPCION)
    await _cerrar_dia(cliente, token_recep, 18)
    token_admin = await _access_para(cliente, EMAIL_ADMIN)

    # Act: admin reabre con motivo valido.
    reapertura = await cliente.post(
        REAPERTURA_URL,
        json={
            "fecha": "2026-12-18",
            "sede": SEDE_FICTICIA,
            "motivo": MOTIVO_FICTICIO,
        },
        headers={"Authorization": f"Bearer {token_admin}"},
    )

    # Assert: 200 abierto + evento + movimiento posterior 201.
    assert reapertura.status_code == 200
    assert reapertura.json()["estado"] == "abierto"
    eventos = await _eventos_por_accion("cierre_reabierto")
    assert len(eventos) == 1
    assert "2026-12-18" in eventos[0]
    posterior = await cliente.post(
        MOVIMIENTOS_URL,
        json={
            "fecha": "2026-12-18",
            "sede": SEDE_FICTICIA,
            "tipo": "ingreso",
            "concepto": "Cobro tras reapertura ficticia",
            "monto": 2500.00,
            "metodo": "efectivo",
        },
        headers={"Authorization": f"Bearer {token_recep}"},
    )
    assert posterior.status_code == 201


@pytest.mark.parametrize(
    "email", [EMAIL_RECEPCION, EMAIL_ODONTOLOGO], ids=["recepcion", "odontologo"]
)
async def test_reapertura_no_admin_403_con_log_y_sigue_cerrado(
    cliente: AsyncClient, usuarios_reapertura: None, email: str
) -> None:
    # Arrange: dia 19 cerrado.
    token_recep = await _access_para(cliente, EMAIL_RECEPCION)
    await _cerrar_dia(cliente, token_recep, 19)
    token_no_admin = await _access_para(cliente, email)

    # Act: no-admin intenta reabrir.
    reapertura = await cliente.post(
        REAPERTURA_URL,
        json={
            "fecha": "2026-12-19",
            "sede": SEDE_FICTICIA,
            "motivo": MOTIVO_FICTICIO,
        },
        headers={"Authorization": f"Bearer {token_no_admin}"},
    )

    # Assert: 403 generico, sigue cerrado, evento denegada.
    assert reapertura.status_code == 403
    assert reapertura.json()["detalle"] == "Sin permiso."
    assert await _estado_cierre(19) == "cerrado"
    eventos = await _eventos_por_accion("reapertura_denegada")
    assert len(eventos) == 1
    assert "2026-12-19" in eventos[0]


async def test_reapertura_dia_abierto_422(
    cliente: AsyncClient, usuarios_reapertura: None
) -> None:
    # Arrange: dia 20 con cierre ya `abierto` (reabierto antes).
    token_admin = await _access_para(cliente, EMAIL_ADMIN)
    async with TestSession() as sesion:
        await sesion.execute(
            text(
                "INSERT INTO cierre_diario "
                "(id, fecha, sede, estado, reaperturas) "
                "VALUES (gen_random_uuid(), :fecha, :sede, 'abierto', 1)"
            ),
            {"fecha": date(2026, 12, 20), "sede": SEDE_FICTICIA},
        )
        await sesion.commit()

    # Act: admin intenta reabrir un dia ya abierto.
    reapertura = await cliente.post(
        REAPERTURA_URL,
        json={
            "fecha": "2026-12-20",
            "sede": SEDE_FICTICIA,
            "motivo": MOTIVO_FICTICIO,
        },
        headers={"Authorization": f"Bearer {token_admin}"},
    )

    # Assert: 422 (nada que reabrir).
    assert reapertura.status_code == 422


async def test_reapertura_cierre_inexistente_404(
    cliente: AsyncClient, usuarios_reapertura: None
) -> None:
    # Arrange: admin autenticado, dia 21 sin cierre.

    # Act: reabre un dia que nunca se cerro.
    reapertura = await cliente.post(
        REAPERTURA_URL,
        json={
            "fecha": "2026-12-21",
            "sede": SEDE_FICTICIA,
            "motivo": MOTIVO_FICTICIO,
        },
        headers={
            "Authorization": f"Bearer {await _access_para(cliente, EMAIL_ADMIN)}"
        },
    )

    # Assert: 404 de dominio (no el 404 de ruteo sin `problema`).
    assert reapertura.status_code == 404
    assert reapertura.json()["problema"] == "no_encontrado"


async def test_caja_sin_pii_ni_concepto_crudo(
    cliente: AsyncClient,
    usuarios_reapertura: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: concepto libre con PII ficticia (dia 22).
    token_recep = await _access_para(cliente, EMAIL_RECEPCION)
    cabeceras = {"Authorization": f"Bearer {token_recep}"}
    token_admin = await _access_para(cliente, EMAIL_ADMIN)
    cabeceras_admin = {"Authorization": f"Bearer {token_admin}"}

    # Act: movimiento + cierre + reapertura con el concepto sensible.
    with caplog.at_level("INFO"):
        movimiento = await cliente.post(
            MOVIMIENTOS_URL,
            json={
                "fecha": "2026-12-22",
                "sede": SEDE_FICTICIA,
                "tipo": "ingreso",
                "concepto": CONCEPTO_SENSIBLE,
                "monto": 2500.00,
                "metodo": "efectivo",
            },
            headers=cabeceras,
        )
        assert movimiento.status_code == 201
        cierre = await cliente.post(
            CIERRE_URL,
            json={"fecha": "2026-12-22", "sede": SEDE_FICTICIA},
            headers=cabeceras,
        )
        assert cierre.status_code == 201
        reapertura = await cliente.post(
            REAPERTURA_URL,
            json={
                "fecha": "2026-12-22",
                "sede": SEDE_FICTICIA,
                "motivo": MOTIVO_FICTICIO,
            },
            headers=cabeceras_admin,
        )
        assert reapertura.status_code == 200

    # Assert: ninguna superficie expone concepto crudo, DNI ni telefono.
    superficies = [movimiento.text, cierre.text, reapertura.text, caplog.text]
    superficies += await _eventos_por_accion("movimiento_registrado")
    superficies += await _eventos_por_accion("cierre_creado")
    superficies += await _eventos_por_accion("cierre_reabierto")
    assert superficies, "sin superficies que auditar"
    for superficie in superficies:
        assert CONCEPTO_SENSIBLE not in superficie
        assert DNI_FICTICIO not in superficie
        assert TEL_FICTICIO not in superficie
