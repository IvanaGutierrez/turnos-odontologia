"""C-05 task 1.5 RED: rotación staff + transiciones inválidas + rate limit (R6).

Contrato que la parte 2 (GREEN) debe cumplir (`agenda/autogestion-paciente`):
- `POST /api/v1/turnos/<id>/rotar-token` solo con permiso `turnos` (JWT):
  genera `token_publico` nuevo, invalida el anterior (el viejo responde
  `404` idéntico al de un token nunca emitido) y audita `token_rotado`
  sin PII; sin permiso → `403` + `acceso_denegado`; los endpoints públicos
  jamás rotan por sí solos.
- Máquina consolidada: terminal (`cancelado|ausente|atendido|reprogramado`)
  no admite más transiciones; confirmar un `atendido` o cancelar un
  `presente` por token → `422` sin mutar (el valor `en_sala` deja de existir
  en la migración 005: la consolidación se verifica a nivel DB, no HTTP).
- Rate limit por IP en los cuatro endpoints públicos (mismo esquema Redis
  que C-03): al excederse → `429` con `Retry-After`, sin mutar ni revelar
  si el token existe.

Estado parte 1: NADA de esto existe → FALLAN en rojo (404/ausencia).
Todo dato sintético (R0); type hints siempre (R1).
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.security import hashear_password
from app.models.auditoria import AuditoriaLog
from app.models.entidades import Turno, Usuario
from tests.conftest import (
    DNI_FICTICIO,
    TestSession,
    inicio_demo,
    payload_turno,
)

pytestmark = pytest.mark.integration

AUTOGESTION_URL = "/api/v1/turnos/publicos"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_STAFF = "autogestion.rotacion.ficticia@consultorio.example"
EMAIL_SIN_PERMISO = "autogestion.sinpermiso.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Autogestion-Rotacion-1234-no-real"


@pytest_asyncio.fixture()
async def staff() -> AsyncGenerator[None, None]:
    """Recepción (con permiso `turnos`) + rol ficticio sin permiso (R0)."""
    async with TestSession() as sesion:
        sesion.add(
            Usuario(
                email=EMAIL_STAFF,
                password_hash=hashear_password(PASSWORD_FICTICIA),
                rol="recepcion",
                activo=True,
            )
        )
        sesion.add(
            Usuario(
                email=EMAIL_SIN_PERMISO,
                password_hash=hashear_password(PASSWORD_FICTICIA),
                rol="pasante-ficticio",
                activo=True,
            )
        )
        await sesion.commit()
    yield
    async with TestSession() as sesion:
        await sesion.execute(
            delete(Usuario).where(
                Usuario.email.in_([EMAIL_STAFF, EMAIL_SIN_PERMISO])
            )
        )
        await sesion.commit()


async def _access(cliente: AsyncClient, email: str) -> str:
    login = await cliente.post(
        LOGIN_URL, json={"email": email, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


async def _crear(cliente: AsyncClient, access: str, hora: int) -> dict[str, object]:
    """Arrange: turno `reservado` vía núcleo C-01 (día 8, hora variable)."""
    respuesta = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio_demo(hora, 0).replace(day=8)),
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


async def test_rotacion_invalida_token_anterior_y_activa_nuevo(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno `reservado` con token conocido.
    access = await _access(cliente, EMAIL_STAFF)
    creado = await _crear(cliente, access, 10)
    token_viejo = str(creado["token_publico"])
    nunca_emitido = "token-ficticio-nunca-emitido-0000-no-real"

    # Act: rotación por staff con permiso.
    rotada = await cliente.post(
        f"{TURNOS_URL}/{creado['id']}/rotar-token",
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 200 con token nuevo distinto + viejo 404 idéntico + auditoría.
    assert rotada.status_code == 200
    token_nuevo = str(rotada.json()["token_publico"])
    assert token_nuevo and token_nuevo != token_viejo
    r_viejo = await cliente.get(f"{AUTOGESTION_URL}/{token_viejo}")
    r_nunca = await cliente.get(f"{AUTOGESTION_URL}/{nunca_emitido}")
    r_nuevo = await cliente.get(f"{AUTOGESTION_URL}/{token_nuevo}")
    assert r_viejo.status_code == 404
    assert r_viejo.content == r_nunca.content
    assert r_viejo.json()["problema"]
    assert r_nuevo.status_code == 200
    async with TestSession() as sesion:
        filas = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "token_rotado",
                        AuditoriaLog.entidad_id == creado["id"],
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(filas) == 1
    assert DNI_FICTICIO not in str(filas[0].diff)
    assert token_viejo not in str(filas[0].diff)
    assert token_nuevo not in str(filas[0].diff)


async def test_rotar_sin_permiso_403_con_acceso_denegado(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno existente + access de rol ficticio sin permiso `turnos`.
    access_staff = await _access(cliente, EMAIL_STAFF)
    access_sin_permiso = await _access(cliente, EMAIL_SIN_PERMISO)
    creado = await _crear(cliente, access_staff, 11)

    # Act: rotación sin permiso.
    respuesta = await cliente.post(
        f"{TURNOS_URL}/{creado['id']}/rotar-token",
        headers={"Authorization": f"Bearer {access_sin_permiso}"},
    )

    # Assert: 403 genérico + `acceso_denegado` auditado, token intacto.
    assert respuesta.status_code == 403
    async with TestSession() as sesion:
        filas = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "acceso_denegado"
                    )
                )
            )
            .scalars()
            .all()
        )
        turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
    assert len(filas) == 1
    assert turno is not None and turno.token_publico == creado["token_publico"]


async def test_transicion_invalida_por_token_422_sin_mutar(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: T1 `atendido` + T2 `presente` (vía ORM directo).
    access = await _access(cliente, EMAIL_STAFF)
    t1 = await _crear(cliente, access, 12)
    t2 = await _crear(cliente, access, 14)
    await _poner_estado(str(t1["id"]), "atendido")
    await _poner_estado(str(t2["id"]), "presente")

    # Act: confirmar `atendido` + cancelar `presente` por token.
    r_confirmar = await cliente.post(
        f"{AUTOGESTION_URL}/{t1['token_publico']}/confirmar"
    )
    r_cancelar = await cliente.post(
        f"{AUTOGESTION_URL}/{t2['token_publico']}/cancelar", json={}
    )

    # Assert: 422 en ambas y estados intactos.
    assert [r_confirmar.status_code, r_cancelar.status_code] == [422, 422]
    async with TestSession() as sesion:
        e1 = await sesion.get(Turno, uuid.UUID(str(t1["id"])))
        e2 = await sesion.get(Turno, uuid.UUID(str(t2["id"])))
        assert e1 is not None and e1.estado == "atendido"
        assert e2 is not None and e2.estado == "presente"


async def test_rate_limit_publico_429_con_retry_after_sin_procesar(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: token inexistente (el 429 no debe revelar si existe).
    url = f"{AUTOGESTION_URL}/token-ficticio-nunca-emitido-0000-no-real"

    # Act: ráfaga por encima del tope por IP (default 60/60 s, env C-03).
    vistos: set[int] = set()
    espera: str | None = None
    for _ in range(70):
        respuesta = await cliente.get(url)
        vistos.add(respuesta.status_code)
        if respuesta.status_code == 429:
            espera = respuesta.headers.get("Retry-After")

    # Assert: corte con 429 + `Retry-After`, sin procesar (sigue 404/429).
    assert 429 in vistos
    assert espera
    assert vistos <= {404, 429}
