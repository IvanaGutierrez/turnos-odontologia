"""C-04 TRIANGULATE: ramas no cubiertas por los 23 tests de contrato.

Casos propios del apply (no modifican los tests RED 1.1–1.4):
- Reprogramar hacia slot con sillón ocupado (otro profesional) → 409
  `sillon_ocupado` sin mutar (rama `existe_solape_sillon` del destino).
- Sobreturno con paciente inline (sin `paciente_id`) → 201 + auditado.
- Confirmar/check-in/reprogramar sobre id inexistente → 404 sin mutar.

Todo dato sintético (R0); type hints siempre (R1).
"""

import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, func, select

from app.core.security import hashear_password
from app.models.auditoria import AuditoriaLog
from app.models.entidades import Turno, Usuario
from tests.conftest import (
    ID_PRESTACION_CONSULTA_30,
    ID_PROFESIONAL_B,
    ID_SILLON_S1,
    ID_SILLON_S2,
    TestSession,
    inicio_demo,
    payload_paciente_ficticio,
    payload_turno,
)

pytestmark = pytest.mark.integration

TURNOS_URL = "/api/v1/turnos"
SOBRETURNO_URL = "/api/v1/turnos/sobreturno"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_RECEPCION = "recepcion.triangulacion.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Triangulacion-1234-no-real"
MOTIVO_FICTICIO = "urgencia dolor agudo"


@pytest_asyncio.fixture()
async def recepcion() -> None:
    """Usuario recepción sintético; self-cleanup (R0)."""
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
    yield
    async with TestSession() as sesion:
        await sesion.execute(delete(Usuario).where(Usuario.email == EMAIL_RECEPCION))
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
    payload = payload_turno(
        inicio if inicio is not None else inicio_demo(10, 0), **extras
    )
    payload["canal"] = "recepcion"
    respuesta = await cliente.post(
        TURNOS_URL, json=payload, headers={"Authorization": f"Bearer {access}"}
    )
    assert respuesta.status_code == 201
    return dict(respuesta.json())


async def _contar_turnos() -> int:
    async with TestSession() as sesion:
        total = await sesion.execute(select(func.count()).select_from(Turno))
        return int(total.scalar_one())


async def test_reprogramar_destino_sillon_ocupado_409_sin_mutar(
    cliente: AsyncClient, recepcion: None
) -> None:
    # Arrange: T1 (prof A/S1 10:00) + T2 (prof B/S1 14:00–14:30).
    access = await _access(cliente)
    auth = {"Authorization": f"Bearer {access}"}
    t1 = await _crear(cliente, access)
    await _crear(
        cliente,
        access,
        inicio=inicio_demo(14, 0),
        profesional_id=ID_PROFESIONAL_B,
        sillon_id=ID_SILLON_S1,
        prestacion_id=ID_PRESTACION_CONSULTA_30,
    )
    total_antes = await _contar_turnos()

    # Act: T1 → 14:15 (prof A libre, pero S1 ocupado por T2).
    respuesta = await cliente.post(
        f"{TURNOS_URL}/{t1['id']}/reprogramar",
        json={"nuevo_inicio": inicio_demo(14, 15).isoformat()},
        headers=auth,
    )

    # Assert: 409 `sillon_ocupado` + alternativos, T1 intacto, sin altas.
    assert respuesta.status_code == 409
    assert respuesta.json()["problema"] == "sillon_ocupado"
    assert len(respuesta.json()["slots_alternativos"]) > 0
    assert await _contar_turnos() == total_antes
    async with TestSession() as sesion:
        original = await sesion.get(Turno, uuid.UUID(str(t1["id"])))
        assert original is not None and original.estado == "reservado"


async def test_sobreturno_paciente_inline_crea_y_audita(
    cliente: AsyncClient, recepcion: None
) -> None:
    # Arrange: recepción autenticada + paciente inline ficticio (R0).
    access = await _access(cliente)
    cuerpo = payload_turno(inicio_demo(10, 0))
    cuerpo.pop("paciente_id", None)
    cuerpo["paciente"] = payload_paciente_ficticio()

    # Act: sobreturno con paciente inline y motivo.
    respuesta = await cliente.post(
        SOBRETURNO_URL,
        json={
            **cuerpo,
            "sobreturno": True,
            "motivo_sobreturno": MOTIVO_FICTICIO,
        },
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 201 `sobreturno=true` + `sobreturno_creado` con motivo.
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


async def test_operacion_sobre_id_inexistente_404(
    cliente: AsyncClient, recepcion: None
) -> None:
    # Arrange: id al azar (nunca existe) + conteo base.
    access = await _access(cliente)
    auth = {"Authorization": f"Bearer {access}"}
    inexistente = str(uuid.uuid4())
    total_antes = await _contar_turnos()

    # Act: las tres operaciones sobre el id inexistente.
    respuestas = [
        await cliente.post(f"{TURNOS_URL}/{inexistente}/confirmar", headers=auth),
        await cliente.post(f"{TURNOS_URL}/{inexistente}/check-in", headers=auth),
        await cliente.post(
            f"{TURNOS_URL}/{inexistente}/reprogramar",
            json={"nuevo_inicio": inicio_demo(14, 0).isoformat()},
            headers=auth,
        ),
    ]

    # Assert: 404 en las tres, sin turnos nuevos.
    assert [r.status_code for r in respuestas] == [404, 404, 404]
    assert await _contar_turnos() == total_antes


async def test_sobreturno_sillon_distinto_no_colisiona_grilla(
    cliente: AsyncClient, recepcion: None
) -> None:
    # Arrange: turno normal en S1 10:00 (prof A).
    access = await _access(cliente)
    auth = {"Authorization": f"Bearer {access}"}
    await _crear(cliente, access)

    # Act: sobreturno superpuesto pero en S2 con otro profesional.
    respuesta = await cliente.post(
        SOBRETURNO_URL,
        json={
            **payload_turno(
                inicio_demo(10, 15),
                profesional_id=ID_PROFESIONAL_B,
                sillon_id=ID_SILLON_S2,
                prestacion_id=ID_PRESTACION_CONSULTA_30,
            ),
            "sobreturno": True,
            "motivo_sobreturno": MOTIVO_FICTICIO,
        },
        headers=auth,
    )
    grilla = await cliente.get(
        "/api/v1/agenda",
        params={"vista": "dia", "desde": "2026-11-03T00:00:00-03:00"},
        headers=auth,
    )

    # Assert: 201 (el GiST parcial deja pasar al sobreturno) y la grilla
    # del día muestra ambos: el normal y el sobreturno marcado.
    assert respuesta.status_code == 201
    assert grilla.status_code == 200
    items = grilla.json()
    assert len(items) == 2
    assert sum(1 for i in items if i.get("sobreturno") is True) == 1
