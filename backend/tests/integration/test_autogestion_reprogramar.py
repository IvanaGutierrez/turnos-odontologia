"""C-05 task 1.4 RED: reprogramar con token sobre slots reales (R3/R5).

Contrato que la parte 2 (GREEN) debe cumplir (`agenda/autogestion-paciente`):
- `POST /api/v1/turnos/publicos/:token/reprogramar {nuevo_inicio}` sin JWT
  reutiliza el núcleo de C-04 (RN-AG-07): destino libre → original a
  `reprogramado` + turno nuevo con IDÉNTICO `token_publico` enlazado por
  `reprogramado_de_id` + `turno_reprogramado` sin PII (`200|201`).
- Destino ocupado → `409` (`problema=profesional_ocupado|sillon_ocupado` +
  `slots_alternativos` no vacío, mismo shape C-01) SIN mutar nada: el
  original conserva su estado y no se crea ningún turno nuevo.
- Solo origen `reservado|confirmado` (terminal → `422`, ver rotación).

Estado parte 1: el router público NO existe → FALLAN en rojo (404).
Todo dato sintético (R0); type hints siempre (R1).
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, func, select

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

AUTOGESTION_URL = "/api/v1/turnos/publicos"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_STAFF = "autogestion.reprogramar.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Autogestion-Reprogramar-1234-no-real"

PROBLEMAS_409 = ("profesional_ocupado", "sillon_ocupado", "slot_ocupado")


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


async def _crear(
    cliente: AsyncClient, access: str, inicio: datetime, **extras: object
) -> dict[str, object]:
    """Arrange: turno `reservado` vía núcleo C-01."""
    respuesta = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio, **extras),
        headers={"Authorization": f"Bearer {access}"},
    )
    assert respuesta.status_code == 201
    return dict(respuesta.json())


async def _poner_estado(turno_id: str, estado: str) -> None:
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, uuid.UUID(turno_id))
        assert turno is not None
        turno.estado = estado
        await sesion.commit()


async def _contar_turnos() -> int:
    async with TestSession() as sesion:
        total = await sesion.execute(select(func.count()).select_from(Turno))
        return int(total.scalar_one())


async def test_reprogramar_a_slot_libre_conserva_token_y_enlaza_original(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno `confirmado` de 45' + destino libre de igual prestación.
    access = await _access(cliente)
    creado = await _crear(cliente, access, inicio_demo(10, 0).replace(day=7))
    await _poner_estado(str(creado["id"]), "confirmado")
    token_original = str(creado["token_publico"])
    total_antes = await _contar_turnos()
    destino = inicio_demo(14, 0).replace(day=7).isoformat()

    # Act: reprogramar por token a slot libre.
    respuesta = await cliente.post(
        f"{AUTOGESTION_URL}/{token_original}/reprogramar",
        json={"nuevo_inicio": destino},
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
        reprogramado = await sesion.get(Turno, uuid.UUID(str(nuevo["id"])))
        assert (
            reprogramado is not None
            and str(reprogramado.reprogramado_de_id) == str(creado["id"])
        )
        filas = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "turno_reprogramado",
                        AuditoriaLog.entidad_id == creado["id"],
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(filas) == 1
    assert DNI_FICTICIO not in str(filas[0].diff)


async def test_reprogramar_a_ocupado_409_con_alternativos_sin_mutar(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: T1 (10:00–10:45) a reprogramar + T2 ocupando el destino (14:00).
    access = await _access(cliente)
    t1 = await _crear(cliente, access, inicio_demo(10, 0).replace(day=7))
    await _poner_estado(str(t1["id"]), "confirmado")
    await _crear(
        cliente,
        access,
        inicio_demo(14, 0).replace(day=7),
        prestacion_id=ID_PRESTACION_CONSULTA_30,
    )
    total_antes = await _contar_turnos()

    # Act: reprogramar T1 hacia el rango ocupado por T2.
    respuesta = await cliente.post(
        f"{AUTOGESTION_URL}/{t1['token_publico']}/reprogramar",
        json={"nuevo_inicio": inicio_demo(14, 15).replace(day=7).isoformat()},
    )

    # Assert: 409 + alternativos, T1 intacto, sin turnos nuevos.
    assert respuesta.status_code == 409
    datos = respuesta.json()
    assert datos["problema"] in PROBLEMAS_409
    assert len(datos["slots_alternativos"]) > 0
    assert await _contar_turnos() == total_antes
    async with TestSession() as sesion:
        original = await sesion.get(Turno, uuid.UUID(str(t1["id"])))
        assert original is not None and original.estado == "confirmado"
