"""C-03 task 1.3 RED: primera reserva exige verificación sin enumerar.

Contrato que la parte 2 (GREEN) debe cumplir:
- `POST /api/v1/turnos/publicos` (sin JWT) con
  `{prestacion_id, profesional_id, inicio, paciente: {nombre, dni,
  telefono}, codigo_verificacion?}` + header `Idempotency-Key`.
- Par DNI + teléfono sin verificación previa y sin/código inválido o
  expirado → `422` genérico SIN crear turno.
- Intentos agotados / bloqueo temporal → `429` genérico SIN crear turno.
- Par ya verificado → `201` sin código (`reservado`, `canal=online`,
  `token_publico` único, `fin = inicio + duracion_min`).
- Mensajes idénticos exista o no el par (anti-enumeración, R6).
- Hashes: SHA-256 hex del valor en claro (contrato con `models/`).

Estado parte 1: el endpoint NO existe → estos tests FALLAN en rojo.
Todo dato sintético (R0); jamás PII real (R6).
"""

import hashlib
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from tests.conftest import (
    ID_PRESTACION_LIMPIEZA_45,
    ID_PROFESIONAL_A,
    TestSession,
    inicio_demo,
)
from tests.integration.test_disponibilidad_excluye_ocupados import (
    _sembrar_horario,
)

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
TURNOS_PUBLICOS_URL = "/api/v1/turnos/publicos"

# Pares 100 % ficticios (rango ejemplo 90xxxxxx / 5000-00xx, R0).
DNI_NUEVO = "90345678"
TEL_NUEVO = "+5491150000011"
DNI_OTRO = "90345679"
TEL_OTRO = "+5491150000012"
CODIGO_BUENO = "123456"
CODIGO_MALO = "000000"


def _sha(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def _payload_reserva(
    dni: str = DNI_NUEVO,
    telefono: str = TEL_NUEVO,
    codigo: str | None = None,
    inicio: datetime | None = None,
) -> dict[str, object]:
    cuerpo: dict[str, object] = {
        "prestacion_id": str(ID_PRESTACION_LIMPIEZA_45),
        "profesional_id": str(ID_PROFESIONAL_A),
        "inicio": (inicio or inicio_demo(11, 0)).isoformat(),
        "paciente": {
            "nombre": "Reservante Ficticia Demo",
            "dni": dni,
            "telefono": telefono,
        },
    }
    if codigo is not None:
        cuerpo["codigo_verificacion"] = codigo
    return cuerpo


def _cabecera_clave() -> dict[str, str]:
    return {"Idempotency-Key": f"clave-ficticia-{uuid.uuid4()}"}


async def _sembrar_verificacion(
    dni: str,
    telefono: str,
    codigo: str = CODIGO_BUENO,
    expirada: bool = False,
    intentos: int = 0,
    verificada: bool = False,
    bloqueada: bool = False,
) -> None:
    """Arrange: fila de verificación vía ORM (solo hashes, R6)."""
    from app.models.disponibilidad import VerificacionPublica

    ahora = datetime.now(BA)
    async with TestSession() as sesion:
        sesion.add(
            VerificacionPublica(
                dni_hash=_sha(dni),
                telefono_hash=_sha(telefono),
                codigo_hash=_sha(codigo),
                intentos=intentos,
                expira_en=ahora - timedelta(minutes=1)
                if expirada
                else ahora + timedelta(minutes=10),
                verificada_en=ahora if verificada else None,
                bloqueada_hasta=ahora + timedelta(minutes=15) if bloqueada else None,
            )
        )
        await sesion.commit()


async def _contar_turnos() -> int:
    from app.models.entidades import Turno

    async with TestSession() as sesion:
        return int(
            (await sesion.execute(select(func.count()).select_from(Turno))).scalar_one()
        )


async def test_primera_reserva_sin_codigo_devuelve_422_sin_crear(
    cliente: AsyncClient,
) -> None:
    # Arrange: horario vigente; par sin verificación previa.
    await _sembrar_horario(inicio_demo(11, 0).weekday())
    antes = await _contar_turnos()

    # Act: reserva sin código de verificación.
    respuesta = await cliente.post(
        TURNOS_PUBLICOS_URL, json=_payload_reserva(), headers=_cabecera_clave()
    )

    # Assert: 422 genérico y ningún turno creado.
    assert respuesta.status_code == 422
    assert "problema" in respuesta.json()
    assert DNI_NUEVO not in respuesta.text
    assert await _contar_turnos() == antes


async def test_codigo_incorrecto_devuelve_422_sin_crear(
    cliente: AsyncClient,
) -> None:
    # Arrange: código emitido pero el cliente envía otro.
    await _sembrar_horario(inicio_demo(11, 0).weekday())
    await _sembrar_verificacion(DNI_NUEVO, TEL_NUEVO)
    antes = await _contar_turnos()

    # Act: reserva con código incorrecto.
    respuesta = await cliente.post(
        TURNOS_PUBLICOS_URL,
        json=_payload_reserva(codigo=CODIGO_MALO),
        headers=_cabecera_clave(),
    )

    # Assert: 422 genérico y ningún turno creado.
    assert respuesta.status_code == 422
    assert await _contar_turnos() == antes


async def test_codigo_expirado_devuelve_422_sin_crear(
    cliente: AsyncClient,
) -> None:
    # Arrange: código emitido pero vencido.
    await _sembrar_horario(inicio_demo(11, 0).weekday())
    await _sembrar_verificacion(DNI_NUEVO, TEL_NUEVO, expirada=True)
    antes = await _contar_turnos()

    # Act: reserva con código expirado (aunque sea el correcto).
    respuesta = await cliente.post(
        TURNOS_PUBLICOS_URL,
        json=_payload_reserva(codigo=CODIGO_BUENO),
        headers=_cabecera_clave(),
    )

    # Assert: 422 genérico y ningún turno creado.
    assert respuesta.status_code == 422
    assert await _contar_turnos() == antes


async def test_bloqueo_por_intentos_devuelve_429_sin_crear(
    cliente: AsyncClient,
) -> None:
    # Arrange: par bloqueado tras fallos reiterados.
    await _sembrar_horario(inicio_demo(11, 0).weekday())
    await _sembrar_verificacion(DNI_NUEVO, TEL_NUEVO, intentos=5, bloqueada=True)
    antes = await _contar_turnos()

    # Act: reserva durante el bloqueo temporal.
    respuesta = await cliente.post(
        TURNOS_PUBLICOS_URL,
        json=_payload_reserva(codigo=CODIGO_BUENO),
        headers=_cabecera_clave(),
    )

    # Assert: 429 genérico y ningún turno creado.
    assert respuesta.status_code == 429
    assert "detalle" in respuesta.json()
    assert await _contar_turnos() == antes


async def test_par_verificado_reserva_sin_codigo_devuelve_201(
    cliente: AsyncClient,
) -> None:
    # Arrange: par con verificación previa exitosa vigente.
    await _sembrar_horario(inicio_demo(11, 0).weekday())
    await _sembrar_verificacion(DNI_NUEVO, TEL_NUEVO, verificada=True)

    # Act: reserva posterior sin código nuevo.
    respuesta = await cliente.post(
        TURNOS_PUBLICOS_URL, json=_payload_reserva(), headers=_cabecera_clave()
    )

    # Assert: turno reservado con token público y fin calculado.
    assert respuesta.status_code == 201
    datos = respuesta.json()
    assert datos["estado"] == "reservado"
    assert datos["canal"] == "online"
    assert datos["token_publico"]
    assert datetime.fromisoformat(datos["fin"]) - datetime.fromisoformat(
        datos["inicio"]
    ) == timedelta(minutes=45)


async def test_mensajes_identicos_exista_o_no_el_par(
    cliente: AsyncClient,
) -> None:
    # Arrange: un par con verificación emitida; otro totalmente desconocido.
    await _sembrar_horario(inicio_demo(11, 0).weekday())
    await _sembrar_verificacion(DNI_NUEVO, TEL_NUEVO)

    # Act: ambas reservas sin código (misma forma, distinto conocimiento).
    primera = await cliente.post(
        TURNOS_PUBLICOS_URL, json=_payload_reserva(), headers=_cabecera_clave()
    )
    segunda = await cliente.post(
        TURNOS_PUBLICOS_URL,
        json=_payload_reserva(dni=DNI_OTRO, telefono=TEL_OTRO),
        headers=_cabecera_clave(),
    )

    # Assert: anti-enumeración → mismo estado y cuerpo idéntico, con el
    # shape genérico del dominio (un 404 de Starlette por ruta inexistente
    # trae `detail`, no `problema`: eso falla aquí, nada de falsos verdes).
    assert primera.status_code == segunda.status_code == 422
    assert primera.json() == segunda.json()
    assert "problema" in primera.json()
    assert DNI_NUEVO not in primera.text
    assert DNI_OTRO not in segunda.text
