"""C-04 task 1.2 RED: operación de recepción (crear/confirmar/check-in/reprogramar).

Contrato que la parte 2 (GREEN) debe cumplir (`agenda/agenda-recepcion`):
- Crear con `canal=recepcion` reusa el núcleo C-01 (`201` + `turno_creado`)
  y el turno queda visible en la grilla del día.
- `POST /api/v1/turnos/<id>/confirmar`: `reservado→confirmado` (`200` +
  `turno_confirmado`); estado terminal → `422` sin mutar.
- `POST /api/v1/turnos/<id>/check-in`: `confirmado|reservado→presente`
  (`200` + `turno_presente`); otro origen → `422` sin mutar.
- `POST /api/v1/turnos/<id>/reprogramar {nuevo_inicio}`: destino libre →
  original a `reprogramado` + nuevo turno con idéntico `token_publico`
  enlazado por `reprogramado_de_id` + `turno_reprogramado` (`200|201`);
  destino ocupado → `409` + alternativos sin mutar nada (la cancelación
  es C-05 y NO se implementa aquí).

Estado parte 1: los endpoints dedicados NO existen → FALLAN en rojo (404).
Todo dato sintético (R0); type hints siempre (R1).
"""

import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text

from app.core.security import hashear_password
from app.models.auditoria import AuditoriaLog
from app.models.entidades import Turno, Usuario
from tests.conftest import (
    DNI_FICTICIO,
    ID_PRESTACION_CONSULTA_30,
    TestSession,
    inicio_demo,
    payload_turno,
)

pytestmark = pytest.mark.integration

TURNOS_URL = "/api/v1/turnos"
AGENDA_URL = "/api/v1/agenda"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_RECEPCION = "recepcion.operacion.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Operacion-1234-no-real"


@pytest_asyncio.fixture()
async def recepcion() -> str:
    """Usuario recepción sintético; retorna su access (self-cleanup, R0)."""
    async with TestSession() as sesion:
        sesion.add(
            Usuario(
                email=EMAIL_RECEPCION,
                password_hash=hashear_password(PASSWORD_FICTICIA),
                rol="recepcion",
                activo=True,
            )
        )
        await sesion.commit()
    yield "pendiente"
    async with TestSession() as sesion:
        await sesion.execute(
            delete(Usuario).where(Usuario.email == EMAIL_RECEPCION)
        )
        await sesion.commit()


async def _access(cliente: AsyncClient) -> str:
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_RECEPCION, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


async def _crear(
    cliente: AsyncClient,
    access: str,
    inicio: datetime | None = None,
    **extras: object,
) -> dict[str, object]:
    """Arrange: turno `reservado` vía núcleo C-01 (+ `canal=recepcion`)."""
    payload = payload_turno(inicio if inicio is not None else inicio_demo(10, 0), **extras)
    payload["canal"] = "recepcion"
    respuesta = await cliente.post(
        TURNOS_URL, json=payload, headers={"Authorization": f"Bearer {access}"}
    )
    assert respuesta.status_code == 201
    datos = respuesta.json()
    assert datos["estado"] == "reservado"
    return datos


async def _contar_turnos() -> int:
    async with TestSession() as sesion:
        total = await sesion.execute(select(func.count()).select_from(Turno))
        return int(total.scalar_one())


async def _poner_estado(turno_id: str, estado: str) -> None:
    """Arrange: lleva el turno al estado pedido por ORM directo."""
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, uuid.UUID(turno_id))
        assert turno is not None
        turno.estado = estado
        await sesion.commit()


async def test_recepcion_crea_turno_canal_recepcion_y_visible_en_grilla(
    cliente: AsyncClient, recepcion: str
) -> None:
    # Arrange: recepción autenticada.
    access = await _access(cliente)

    # Act: crear con `canal=recepcion` + grilla del día.
    creado = await _crear(cliente, access)
    grilla = await cliente.get(
        AGENDA_URL,
        params={"vista": "dia", "desde": "2026-11-03T00:00:00-03:00"},
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 201 + `turno_creado` auditado + visible en la grilla.
    assert creado["token_publico"]
    async with TestSession() as sesion:
        filas = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "turno_creado",
                        AuditoriaLog.entidad_id == creado["id"],
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(filas) == 1
    assert DNI_FICTICIO not in str(filas[0].diff)
    assert grilla.status_code == 200
    assert {t["id"] for t in grilla.json()} >= {creado["id"]}


async def test_recepcion_confirma_turno_reservado(
    cliente: AsyncClient, recepcion: str
) -> None:
    # Arrange: turno `reservado` de recepción.
    access = await _access(cliente)
    creado = await _crear(cliente, access)

    # Act: confirmar.
    respuesta = await cliente.post(
        f"{TURNOS_URL}/{creado['id']}/confirmar",
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 200 `confirmado` + `turno_confirmado` auditado.
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "confirmado"
    async with TestSession() as sesion:
        filas = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "turno_confirmado",
                        AuditoriaLog.entidad_id == creado["id"],
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(filas) == 1


async def test_confirmar_estado_terminal_422_sin_mutar(
    cliente: AsyncClient, recepcion: str
) -> None:
    # Arrange: turnos en `atendido` y `cancelado` (terminales, vía ORM).
    access = await _access(cliente)
    auth = {"Authorization": f"Bearer {access}"}
    ids = []
    for estado in ("atendido", "cancelado"):
        creado = await _crear(
            cliente,
            access,
            inicio=inicio_demo(10, 0).replace(hour=10 + len(ids)),
        )
        await _poner_estado(str(creado["id"]), estado)
        ids.append(str(creado["id"]))

    # Act: intentar confirmar ambos.
    respuestas = [
        await cliente.post(f"{TURNOS_URL}/{tid}/confirmar", headers=auth)
        for tid in ids
    ]

    # Assert: 422 en ambos y estados intactos.
    assert [r.status_code for r in respuestas] == [422, 422]
    async with TestSession() as sesion:
        estados = [
            (await sesion.get(Turno, uuid.UUID(tid))).estado  # type: ignore[union-attr]
            for tid in ids
        ]
    assert estados == ["atendido", "cancelado"]


async def test_checkin_marca_presente_y_audita(
    cliente: AsyncClient, recepcion: str
) -> None:
    # Arrange: turno `confirmado` (vía ORM; el endpoint confirmar llega en GREEN).
    access = await _access(cliente)
    creado = await _crear(cliente, access)
    await _poner_estado(str(creado["id"]), "confirmado")

    # Act: check-in.
    respuesta = await cliente.post(
        f"{TURNOS_URL}/{creado['id']}/check-in",
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 200 `presente` + `turno_presente` auditado sin PII.
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "presente"
    async with TestSession() as sesion:
        filas = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "turno_presente",
                        AuditoriaLog.entidad_id == creado["id"],
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(filas) == 1
    assert DNI_FICTICIO not in str(filas[0].diff)


async def test_checkin_estado_invalido_422_sin_mutar(
    cliente: AsyncClient, recepcion: str
) -> None:
    # Arrange: turno `atendido` (fuera de `reservado|confirmado`).
    access = await _access(cliente)
    creado = await _crear(cliente, access)
    await _poner_estado(str(creado["id"]), "atendido")

    # Act: check-in sobre estado inválido.
    respuesta = await cliente.post(
        f"{TURNOS_URL}/{creado['id']}/check-in",
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 422 y estado intacto.
    assert respuesta.status_code == 422
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
        assert turno is not None and turno.estado == "atendido"


async def test_reprogramar_conserva_token_y_enlaza_original(
    cliente: AsyncClient, recepcion: str
) -> None:
    # Arrange: turno `confirmado` de 45' (vía ORM) + conteo base.
    access = await _access(cliente)
    creado = await _crear(cliente, access)
    await _poner_estado(str(creado["id"]), "confirmado")
    token_original = creado["token_publico"]
    total_antes = await _contar_turnos()
    destino = (inicio_demo(14, 0)).isoformat()

    # Act: reprogramar a slot libre de igual prestación.
    respuesta = await cliente.post(
        f"{TURNOS_URL}/{creado['id']}/reprogramar",
        json={"nuevo_inicio": destino},
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: nuevo turno con idéntico token + original `reprogramado` enlazado.
    assert respuesta.status_code in (200, 201)
    nuevo = respuesta.json()
    assert nuevo["token_publico"] == token_original
    assert nuevo["id"] != creado["id"]
    assert await _contar_turnos() == total_antes + 1
    async with TestSession() as sesion:
        original = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
        assert original is not None and original.estado == "reprogramado"
        enlace = (
            await sesion.execute(
                text("SELECT reprogramado_de_id FROM turno WHERE id = :id"),
                {"id": uuid.UUID(nuevo["id"])},
            )
        ).scalar_one()
        assert str(enlace) == str(creado["id"])
        filas = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "turno_reprogramado"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(filas) == 1
    assert DNI_FICTICIO not in str(filas[0].diff)


async def test_reprogramar_destino_ocupado_409_sin_mutar(
    cliente: AsyncClient, recepcion: str
) -> None:
    # Arrange: T1 (10:00–10:45) a reprogramar + T2 ocupando el destino (14:00).
    access = await _access(cliente)
    t1 = await _crear(cliente, access)
    await _poner_estado(str(t1["id"]), "confirmado")
    await _crear(
        cliente,
        access,
        inicio=inicio_demo(14, 0),
        prestacion_id=ID_PRESTACION_CONSULTA_30,
    )
    total_antes = await _contar_turnos()

    # Act: reprogramar T1 hacia el rango ocupado por T2.
    respuesta = await cliente.post(
        f"{TURNOS_URL}/{t1['id']}/reprogramar",
        json={"nuevo_inicio": inicio_demo(14, 15).isoformat()},
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 409 + alternativos, T1 intacto, sin turnos nuevos.
    assert respuesta.status_code == 409
    datos = respuesta.json()
    assert datos["problema"] in (
        "profesional_ocupado",
        "sillon_ocupado",
        "slot_ocupado",
    )
    assert len(datos["slots_alternativos"]) > 0
    assert await _contar_turnos() == total_antes
    async with TestSession() as sesion:
        original = await sesion.get(Turno, uuid.UUID(str(t1["id"])))
        assert original is not None and original.estado == "confirmado"
