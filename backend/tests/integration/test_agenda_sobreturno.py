"""C-04 task 1.3 RED: sobreturno explícito y auditado.

Contrato que la parte 2 (GREEN) debe cumplir (`agenda/agenda-recepcion`,
design decisión 1 — R3):
- `POST /api/v1/turnos/sobreturno` solo `recepcion`/`admin`, con
  `motivo_sobreturno` no vacío: `201` con `sobreturno=true`, fila marcada
  y `sobreturno_creado` auditado (quién/cuándo/por qué); el GiST parcial
  deja pasar SOLO esta vía (camino normal intacto).
- `odontologo` → `403` + `acceso_denegado` auditado, sin crear nada.
- Sin motivo (ausente o vacío) → `422`, sin crear nada.
- Un turno normal NUNCA pisa un sobreturno existente: `409` + alternativos
  (el pre-chequeo cuenta sobreturnos como ocupantes) y la grilla lo muestra
  con `sobreturno=true` para resolución operativa.
- `TurnoCreate` por el endpoint normal ignora el flag `sobreturno`
  (`extra="ignore"`, patrón C-01 con `fin`): el turno queda normal.

Estado parte 1: el endpoint dedicado y la grilla NO existen → rojo (404).
Todo dato sintético (R0); type hints siempre (R1).
"""

import secrets
import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text

from app.core.security import hashear_password
from app.models.auditoria import AuditoriaLog
from app.models.entidades import Turno, Usuario
from tests.conftest import (
    DNI_FICTICIO,
    ID_PACIENTE_DEMO,
    ID_PRESTACION_CONSULTA_30,
    ID_PROFESIONAL_A,
    ID_SILLON_S1,
    TestSession,
    inicio_demo,
    payload_turno,
)

pytestmark = pytest.mark.integration

TURNOS_URL = "/api/v1/turnos"
SOBRETURNO_URL = "/api/v1/turnos/sobreturno"
AGENDA_URL = "/api/v1/agenda"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_RECEPCION = "recepcion.sobreturno.ficticia@consultorio.example"
EMAIL_ODONTOLOGO = "odontologo.sobreturno.ficticio@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Sobreturno-1234-no-real"

MOTIVO_FICTICIO = "urgencia dolor agudo"


@pytest_asyncio.fixture()
async def usuarios_sobreturno() -> None:
    """Recepción + odontólogo sintéticos; self-cleanup (R0)."""
    async with TestSession() as sesion:
        sesion.add(
            Usuario(
                email=EMAIL_RECEPCION,
                password_hash=hashear_password(PASSWORD_FICTICIA),
                rol="recepcion",
                activo=True,
            )
        )
        sesion.add(
            Usuario(
                email=EMAIL_ODONTOLOGO,
                password_hash=hashear_password(PASSWORD_FICTICIA),
                rol="odontologo",
                activo=True,
            )
        )
        await sesion.commit()
    yield
    async with TestSession() as sesion:
        await sesion.execute(
            delete(Usuario).where(
                Usuario.email.in_([EMAIL_RECEPCION, EMAIL_ODONTOLOGO])
            )
        )
        await sesion.commit()


async def _access(cliente: AsyncClient, email: str) -> str:
    login = await cliente.post(
        LOGIN_URL, json={"email": email, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


async def _contar_turnos() -> int:
    async with TestSession() as sesion:
        total = await sesion.execute(select(func.count()).select_from(Turno))
        return int(total.scalar_one())


async def _insertar_sobreturno_sql(
    inicio: datetime, minutos: int = 30
) -> uuid.UUID:
    """Arrange: sobreturno preexistente por SQL (el endpoint llega en GREEN).

    Requiere la migración 004 aplicada (columnas `sobreturno`,
    `motivo_sobreturno`); es solo arrange, no código de producción.
    """
    nuevo_id = uuid.uuid4()
    async with TestSession() as sesion:
        await sesion.execute(
            text(
                "INSERT INTO turno (id, paciente_id, profesional_id, sillon_id,"
                " prestacion_id, inicio, fin, estado, canal, token_publico,"
                " motivo_override, sobreturno, motivo_sobreturno)"
                " VALUES (:id, :pac, :prof, :sillon, :prest, :ini, :fin,"
                " 'reservado', 'recepcion', :token, NULL, TRUE, :motivo)"
            ),
            {
                "id": nuevo_id,
                "pac": ID_PACIENTE_DEMO,
                "prof": ID_PROFESIONAL_A,
                "sillon": ID_SILLON_S1,
                "prest": ID_PRESTACION_CONSULTA_30,
                "ini": inicio,
                "fin": inicio + timedelta(minutes=minutos),
                "token": secrets.token_urlsafe(32),
                "motivo": MOTIVO_FICTICIO,
            },
        )
        await sesion.commit()
    return nuevo_id


async def test_sobreturno_con_permiso_crea_y_audita_con_motivo(
    cliente: AsyncClient, usuarios_sobreturno: None
) -> None:
    # Arrange: slot ya ocupado por un turno normal + recepción autenticada.
    access = await _access(cliente, EMAIL_RECEPCION)
    ocupado = payload_turno(inicio_demo(10, 0))
    respuesta_ok = await cliente.post(
        TURNOS_URL, json=ocupado, headers={"Authorization": f"Bearer {access}"}
    )
    assert respuesta_ok.status_code == 201

    # Act: sobreturno sobre el slot ocupado, con motivo (datos sintéticos).
    respuesta = await cliente.post(
        SOBRETURNO_URL,
        json={
            **payload_turno(
                inicio_demo(10, 15),
                prestacion_id=ID_PRESTACION_CONSULTA_30,
            ),
            "sobreturno": True,
            "motivo_sobreturno": MOTIVO_FICTICIO,
        },
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 201 `sobreturno=true` + `sobreturno_creado` con motivo, sin PII.
    assert respuesta.status_code == 201
    datos = respuesta.json()
    assert datos["sobreturno"] is True
    async with TestSession() as sesion:
        filas = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "sobreturno_creado",
                        AuditoriaLog.entidad_id == datos["id"],
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(filas) == 1
    assert filas[0].diff["motivo_sobreturno"] == MOTIVO_FICTICIO
    assert DNI_FICTICIO not in str(filas[0].diff)


async def test_sobreturno_sin_permiso_403_y_audita_sin_crear(
    cliente: AsyncClient, usuarios_sobreturno: None
) -> None:
    # Arrange: odontólogo autenticado + conteo base.
    access = await _access(cliente, EMAIL_ODONTOLOGO)
    total_antes = await _contar_turnos()

    # Act: sobreturno con rol sin permiso fino (matriz de este change).
    respuesta = await cliente.post(
        SOBRETURNO_URL,
        json={
            **payload_turno(
                inicio_demo(10, 0),
                prestacion_id=ID_PRESTACION_CONSULTA_30,
            ),
            "sobreturno": True,
            "motivo_sobreturno": MOTIVO_FICTICIO,
        },
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 403 genérico, nada creado, `acceso_denegado` auditado.
    assert respuesta.status_code == 403
    assert await _contar_turnos() == total_antes
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
    assert len(filas) == 1


async def test_sobreturno_sin_motivo_422_sin_crear(
    cliente: AsyncClient, usuarios_sobreturno: None
) -> None:
    # Arrange: recepción autenticada + conteo base.
    access = await _access(cliente, EMAIL_RECEPCION)
    auth = {"Authorization": f"Bearer {access}"}
    total_antes = await _contar_turnos()
    base = payload_turno(
        inicio_demo(10, 0), prestacion_id=ID_PRESTACION_CONSULTA_30
    )

    # Act: sin motivo y con motivo vacío.
    sin_motivo = await cliente.post(
        SOBRETURNO_URL,
        json={**base, "sobreturno": True},
        headers=auth,
    )
    motivo_vacio = await cliente.post(
        SOBRETURNO_URL,
        json={**base, "sobreturno": True, "motivo_sobreturno": "  "},
        headers=auth,
    )

    # Assert: 422 en ambos, sin turnos nuevos.
    assert sin_motivo.status_code == 422
    assert motivo_vacio.status_code == 422
    assert await _contar_turnos() == total_antes


async def test_normal_contra_sobreturno_409_y_grilla_lo_muestra(
    cliente: AsyncClient, usuarios_sobreturno: None
) -> None:
    # Arrange: sobreturno preexistente 10:00–10:30 (vía SQL, arrange puro).
    access = await _access(cliente, EMAIL_RECEPCION)
    await _insertar_sobreturno_sql(inicio_demo(10, 0))
    total_antes = await _contar_turnos()

    # Act: turno normal superpuesto + grilla del día.
    respuesta = await cliente.post(
        TURNOS_URL,
        json=payload_turno(
            inicio_demo(10, 15), prestacion_id=ID_PRESTACION_CONSULTA_30
        ),
        headers={"Authorization": f"Bearer {access}"},
    )
    grilla = await cliente.get(
        AGENDA_URL,
        params={"vista": "dia", "desde": "2026-11-03T00:00:00-03:00"},
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: el normal recibe 409 + alternativos (no pisa el sobreturno) y
    # la grilla expone el sobreturno con su flag para resolución operativa.
    assert respuesta.status_code == 409
    assert len(respuesta.json()["slots_alternativos"]) > 0
    assert await _contar_turnos() == total_antes
    assert grilla.status_code == 200
    items = grilla.json()
    marcados = [i for i in items if i.get("sobreturno") is True]
    assert len(marcados) == 1


async def test_create_normal_ignora_flag_sobreturno(
    cliente: AsyncClient, usuarios_sobreturno: None
) -> None:
    # Arrange: recepción autenticada.
    access = await _access(cliente, EMAIL_RECEPCION)
    auth = {"Authorization": f"Bearer {access}"}

    # Act: endpoint normal con `sobreturno=true` en el body + grilla.
    respuesta = await cliente.post(
        TURNOS_URL,
        json={
            **payload_turno(inicio_demo(10, 0)),
            "sobreturno": True,
            "motivo_sobreturno": MOTIVO_FICTICIO,
        },
        headers=auth,
    )
    grilla = await cliente.get(
        AGENDA_URL,
        params={"vista": "dia", "desde": "2026-11-03T00:00:00-03:00"},
        headers=auth,
    )

    # Assert: 201 normal y la grilla lo lista con `sobreturno=false`
    # (el flag solo lo atiende el endpoint dedicado).
    assert respuesta.status_code == 201
    creado_id = respuesta.json()["id"]
    async with TestSession() as sesion:
        filas = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "sobreturno_creado"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert filas == []
    assert grilla.status_code == 200
    items = {t["id"]: t for t in grilla.json()}
    assert items[creado_id]["sobreturno"] is False
