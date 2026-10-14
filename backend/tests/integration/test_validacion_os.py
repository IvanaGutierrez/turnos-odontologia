"""C-13 tasks 1.1 RED: validación preventiva de cobertura por turno (R5).

Contrato que la parte 2 (GREEN) debe cumplir:
- `POST /api/v1/obras-sociales/validar {turno_id, afiliacion_id}`
  (JWT `admin|recepcion|odontologo`) → `200`
  `{resultado: cubre|parcial|no_cubre, detalle, validacion_id,
  nomenclador_version}` + `deriva_particular=true` si `no_cubre`.
- Matching en 3 pasos con cortocircuito: (a) afiliación vigente del
  paciente del turno; (b) prestación en nomenclador LOCAL vigente;
  (c) topes/frecuencias contra historial local (`fuente:
  historial_local`). Motivos `sin_afiliacion_vigente|
  fuera_de_nomenclador|tope_agotado|frecuencia_excedida`.
- Validar NUNCA muta el turno (solo escribe `ValidacionCobertura` +
  evento `validacion_os_registrada`).

Estado parte 1: el router NO existe → FALLAN en rojo (`404`).
Todo dato sintético (R0: OS, afiliados y nomencladores ficticios);
type hints siempre (R1); AAA + naming `test_<unidad>_<escenario>_<esperado>`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import (
    ID_PACIENTE_DEMO,
    TURNOS_URL,
    TestSession,
    crear_afiliacion_ficticia,
    crear_obra_social_ficticia,
    crear_usuario_ficticio,
    eliminar_usuario_ficticio,
    inicio_demo,
    payload_turno,
)

pytestmark = pytest.mark.integration

VALIDAR_URL = "/api/v1/obras-sociales/validar"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_RECEPCION = "os.recepcion.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-OS-1234-no-real"


@pytest_asyncio.fixture()
async def recepcion_os() -> AsyncGenerator[None, None]:
    """Recepción sintética; self-cleanup en RED."""
    await crear_usuario_ficticio(EMAIL_RECEPCION, PASSWORD_FICTICIA, "recepcion")
    yield
    await eliminar_usuario_ficticio(EMAIL_RECEPCION)


async def _cabeceras(cliente: AsyncClient) -> dict[str, str]:
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_RECEPCION, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _turno_reservado(cliente: AsyncClient, headers: dict[str, str]) -> str:
    creado = await cliente.post(
        TURNOS_URL, json=payload_turno(inicio_demo(10, 0)), headers=headers
    )
    assert creado.status_code == 201
    return str(creado.json()["id"])


async def _estado_turno(turno_id: str) -> str:
    async with TestSession() as sesion:
        return str(
            await sesion.scalar(
                text("SELECT estado FROM turno WHERE id = :id"), {"id": turno_id}
            )
        )


async def test_validar_cubre_200_con_detalle_y_version(
    cliente: AsyncClient, recepcion_os: None
) -> None:
    # Arrange: turno reservado + OS ficticia v1 + afiliación vigente.
    headers = await _cabeceras(cliente)
    turno_id = await _turno_reservado(cliente, headers)
    os_id = await crear_obra_social_ficticia()
    afiliacion_id = await crear_afiliacion_ficticia(
        paciente_id=ID_PACIENTE_DEMO, obra_social_id=os_id
    )

    # Act: valida la cobertura.
    respuesta = await cliente.post(
        VALIDAR_URL,
        json={"turno_id": turno_id, "afiliacion_id": str(afiliacion_id)},
        headers=headers,
    )

    # Assert: 200 cubre con detalle, versión e id persistido.
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["resultado"] == "cubre"
    assert cuerpo["nomenclador_version"] == 1
    assert "validacion_id" in cuerpo
    assert "detalle" in cuerpo


async def test_validar_parcial_tope_agotado_200_con_copago(
    cliente: AsyncClient, recepcion_os: None
) -> None:
    # Arrange: turno + afiliación vigente + consumo previo que agota el
    # tope ficticio (`cantidad_limpieza_anual=2` del nomenclador andino
    # v1: 2 previas `cubre` sobre el mismo código → la 3.ª es `parcial`).
    import json
    import uuid as _uuid

    headers = await _cabeceras(cliente)
    turno_id = await _turno_reservado(cliente, headers)
    os_id = await crear_obra_social_ficticia()
    afiliacion_id = await crear_afiliacion_ficticia(
        paciente_id=ID_PACIENTE_DEMO, obra_social_id=os_id
    )
    async with TestSession() as sesion:
        for _ in range(2):
            await sesion.execute(
                text(
                    "INSERT INTO validacion_cobertura "
                    "(id, turno_id, afiliacion_id, obra_social_id, "
                    "nomenclador_version, resultado, detalle) "
                    "VALUES (:id, :turno, :afi, :os, 1, 'cubre', "
                    "CAST(:detalle AS JSONB))"
                ),
                {
                    "id": _uuid.uuid4(),
                    "turno": turno_id,
                    "afi": afiliacion_id,
                    "os": os_id,
                    "detalle": json.dumps(
                        {
                            "codigo": "limpieza",
                            "fuente": "historial_local",
                            "nomenclador_version": 1,
                        }
                    ),
                },
            )
        await sesion.commit()

    # Act: valida con consumo previo que agota el tope ficticio.
    respuesta = await cliente.post(
        VALIDAR_URL,
        json={"turno_id": turno_id, "afiliacion_id": str(afiliacion_id)},
        headers=headers,
    )

    # Assert: 200 parcial con motivo tope/frecuencia y copago a cargo.
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["resultado"] == "parcial"
    assert cuerpo["detalle"]["motivo"] in ("tope_agotado", "frecuencia_excedida")
    assert "copago" in cuerpo["detalle"] or "particular_a_cargo" in cuerpo["detalle"]


async def test_validar_no_cubre_fuera_nomenclador_deriva_particular(
    cliente: AsyncClient, recepcion_os: None
) -> None:
    # Arrange: turno sobre prestación fuera del nomenclador ficticio v1.
    from tests.conftest import ID_PRESTACION_CONSULTA_30

    headers = await _cabeceras(cliente)
    creado = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio_demo(11, 0), prestacion_id=ID_PRESTACION_CONSULTA_30),
        headers=headers,
    )
    assert creado.status_code == 201
    turno_id = str(creado.json()["id"])
    os_id = await crear_obra_social_ficticia()
    afiliacion_id = await crear_afiliacion_ficticia(
        paciente_id=ID_PACIENTE_DEMO, obra_social_id=os_id
    )

    # Act: valida una práctica no listada.
    respuesta = await cliente.post(
        VALIDAR_URL,
        json={"turno_id": turno_id, "afiliacion_id": str(afiliacion_id)},
        headers=headers,
    )

    # Assert: 200 no_cubre + deriva a particular con presupuesto C-07.
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["resultado"] == "no_cubre"
    assert cuerpo["detalle"]["motivo"] == "fuera_de_nomenclador"
    assert cuerpo["deriva_particular"] is True


async def test_validar_no_cubre_sin_afiliacion_deriva_particular(
    cliente: AsyncClient, recepcion_os: None
) -> None:
    # Arrange: turno sin afiliación vigente (afiliación vencida ficticia).
    import uuid
    from datetime import date

    from sqlalchemy import text as _text

    headers = await _cabeceras(cliente)
    turno_id = await _turno_reservado(cliente, headers)
    os_id = await crear_obra_social_ficticia()
    async with TestSession() as sesion:
        vencida = uuid.uuid4()
        await sesion.execute(
            _text(
                "INSERT INTO afiliacion_os (id, paciente_id, obra_social_id, "
                "nro_afiliado, vigencia_desde, vigencia_hasta, vigente) "
                "VALUES (:id, :pac, :os, :nro, :desde, :hasta, FALSE)"
            ),
            {
                "id": vencida,
                "pac": ID_PACIENTE_DEMO,
                "os": os_id,
                "nro": "AF-FICT-VENCIDA-XXXX-0000",
                "desde": date(2025, 1, 1),
                "hasta": date(2025, 6, 30),
            },
        )
        await sesion.commit()

    # Act: valida con la afiliación vencida.
    respuesta = await cliente.post(
        VALIDAR_URL,
        json={"turno_id": turno_id, "afiliacion_id": str(vencida)},
        headers=headers,
    )

    # Assert: 200 no_cubre por falta de vigencia + deriva.
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["resultado"] == "no_cubre"
    assert cuerpo["detalle"]["motivo"] == "sin_afiliacion_vigente"
    assert cuerpo["deriva_particular"] is True


async def test_validar_no_muta_estado_del_turno(
    cliente: AsyncClient, recepcion_os: None
) -> None:
    # Arrange: turno reservado + afiliación vigente ficticia.
    headers = await _cabeceras(cliente)
    turno_id = await _turno_reservado(cliente, headers)
    os_id = await crear_obra_social_ficticia()
    afiliacion_id = await crear_afiliacion_ficticia(
        paciente_id=ID_PACIENTE_DEMO, obra_social_id=os_id
    )
    assert await _estado_turno(turno_id) == "reservado"

    # Act: valida (cualquiera sea el resultado).
    respuesta = await cliente.post(
        VALIDAR_URL,
        json={"turno_id": turno_id, "afiliacion_id": str(afiliacion_id)},
        headers=headers,
    )

    # Assert: la validación existe y el turno sigue reservado.
    assert respuesta.status_code == 200
    assert await _estado_turno(turno_id) == "reservado"
    async with TestSession() as sesion:
        n = await sesion.scalar(
            text("SELECT count(*) FROM validacion_cobertura WHERE turno_id = :id"),
            {"id": turno_id},
        )
    assert int(n or 0) == 1
