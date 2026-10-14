"""C-03 task 1.4 RED: idempotencia, rate limit, seña y carrera GET→POST.

Contrato que la parte 2 (GREEN) debe cumplir:
- Header `Idempotency-Key` obligatorio en `POST /api/v1/turnos/publicos`:
  doble submit concurrente misma clave + mismo payload → un solo turno,
  ambas respuestas con idéntico `token_publico` (segunda `201` o `200`).
- Rate limit por IP (`RATE_PUBLIC_IP_MAX`, default 60/min) y por teléfono
  (`RATE_PUBLIC_TEL_MAX`, default 10/min; topes legibles por env en tests):
  al excederse → `429` con header `Retry-After`, SIN crear turno (el rate
  se evalúa antes de procesar la reserva y cuenta todos los intentos).
- Prestación con `requiere_sena` → `201` `reservado` + `url_pago` no vacía
  (sin crear `Pago`; el cobro es C-08) y el turno NO pasa a `confirmado`.
- Carrera GET→POST (slot ocupado entre medias, la DB manda R3) → `409`
  con el shape C-01 (`problema` + `slots_alternativos` de igual duración)
  sin PII en cuerpo ni logs.
- Hashes: SHA-256 hex del valor canónico enviado (teléfono E.164 sin
  espacios, ej. `+5491150000011`, para evitar ambigüedad de normalizado).

Estado parte 1: los endpoints NO existen → estos tests FALLAN en rojo.
Todo dato sintético (R0); jamás PII real (R6).
"""

import asyncio
import hashlib
import logging
import os
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from tests.conftest import (
    DNI_FICTICIO,
    ID_PRESTACION_LIMPIEZA_45,
    ID_PROFESIONAL_A,
    TURNOS_URL,
    TestSession,
    inicio_demo,
    payload_paciente_ficticio,
    payload_turno,
)
from tests.integration.test_disponibilidad_excluye_ocupados import (
    DISPONIBILIDAD_URL,
    _sembrar_horario,
)

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
TURNOS_PUBLICOS_URL = "/api/v1/turnos/publicos"

DNI_BASE = "90456789"
TEL_BASE = "+5491150000091"

PROBLEMAS_409 = ("profesional_ocupado", "sillon_ocupado", "slot_ocupado")


def _sha(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def _payload_publico(
    dni: str,
    telefono: str,
    inicio: datetime,
    prestacion_id: uuid.UUID = ID_PRESTACION_LIMPIEZA_45,
) -> dict[str, object]:
    return {
        "prestacion_id": str(prestacion_id),
        "profesional_id": str(ID_PROFESIONAL_A),
        "inicio": inicio.isoformat(),
        "paciente": {
            "nombre": "Reservante Ficticia Demo",
            "dni": dni,
            "telefono": telefono,
        },
    }


async def _sembrar_verificada(dni: str, telefono: str) -> None:
    from app.models.disponibilidad import VerificacionPublica

    async with TestSession() as sesion:
        sesion.add(
            VerificacionPublica(
                dni_hash=_sha(dni),
                telefono_hash=_sha(telefono),
                codigo_hash=_sha("123456"),
                intentos=0,
                expira_en=datetime.now(BA) + timedelta(minutes=10),
                verificada_en=datetime.now(BA),
                bloqueada_hasta=None,
            )
        )
        await sesion.commit()


async def _sembrar_horario_total() -> None:
    """Arrange: cobertura 00–24 los 7 días (los slots los elige el test)."""
    from datetime import time

    for dia in range(7):
        await _sembrar_horario(dia, hora_inicio=time(0, 0), hora_fin=time(23, 59))


async def _contar_turnos_publicos() -> int:
    from app.models.entidades import Turno

    async with TestSession() as sesion:
        return int(
            (
                await sesion.execute(
                    select(func.count())
                    .select_from(Turno)
                    .where(Turno.profesional_id == ID_PROFESIONAL_A)
                )
            ).scalar_one()
        )


async def test_doble_submit_misma_clave_crea_un_solo_turno(
    cliente: AsyncClient,
) -> None:
    # Arrange: par verificado + slot libre + una sola clave de idempotencia.
    await _sembrar_horario(inicio_demo(11, 0).weekday())
    await _sembrar_verificada(DNI_BASE, TEL_BASE)
    cuerpo = _payload_publico(DNI_BASE, TEL_BASE, inicio_demo(11, 0))
    cabecera = {"Idempotency-Key": f"clave-ficticia-{uuid.uuid4()}"}

    # Act: doble submit simultáneo (carrera real, patrón C-01).
    primera, segunda = await asyncio.gather(
        cliente.post(TURNOS_PUBLICOS_URL, json=cuerpo, headers=cabecera),
        cliente.post(TURNOS_PUBLICOS_URL, json=cuerpo, headers=cabecera),
    )

    # Assert: un solo turno y mismo token público en ambas respuestas.
    assert primera.status_code in (200, 201)
    assert segunda.status_code in (200, 201)
    assert primera.json()["token_publico"]
    assert primera.json()["token_publico"] == segunda.json()["token_publico"]
    assert await _contar_turnos_publicos() == 1


@pytest.mark.slow
async def test_rate_limit_por_ip_devuelve_429_con_retry_after(
    cliente: AsyncClient,
) -> None:
    # Arrange: N pares verificados distintos (misma IP, teléfonos frescos).
    tope = int(os.environ.get("RATE_PUBLIC_IP_MAX", "60"))
    await _sembrar_horario_total()
    for i in range(tope + 5):
        await _sembrar_verificada(f"90{i:06d}", f"+5491150{i:04d}")
    antes = await _contar_turnos_publicos()
    base = inicio_demo(8, 0)

    # Act: ráfaga desde la misma IP con teléfonos siempre nuevos.
    ultima = None
    for i in range(tope + 5):
        inicio = base + timedelta(minutes=45 * i)
        ultima = await cliente.post(
            TURNOS_PUBLICOS_URL,
            json=_payload_publico(
                f"90{i:06d}", f"+5491150{i:04d}", inicio
            ),
            headers={"Idempotency-Key": f"clave-ficticia-{uuid.uuid4()}"},
        )

    # Assert: la ráfaga se corta con 429 + Retry-After, sin crear de más.
    assert ultima is not None
    assert ultima.status_code == 429
    assert "retry-after" in ultima.headers
    assert await _contar_turnos_publicos() - antes < tope + 5


@pytest.mark.slow
async def test_rate_limit_por_telefono_devuelve_429_sin_crear(
    cliente: AsyncClient,
) -> None:
    # Arrange: un solo par verificado (misma IP por debajo del tope IP).
    tope_tel = int(os.environ.get("RATE_PUBLIC_TEL_MAX", "10"))
    await _sembrar_horario_total()
    await _sembrar_verificada(DNI_BASE, TEL_BASE)
    antes = await _contar_turnos_publicos()
    base = inicio_demo(8, 0)
    vistos = set()

    # Act: ráfaga con el mismo teléfono en slots siempre libres.
    for i in range(tope_tel + 5):
        inicio = base + timedelta(minutes=45 * i)
        respuesta = await cliente.post(
            TURNOS_PUBLICOS_URL,
            json=_payload_publico(DNI_BASE, TEL_BASE, inicio),
            headers={"Idempotency-Key": f"clave-ficticia-{uuid.uuid4()}"},
        )
        vistos.add(respuesta.status_code)

    # Assert: el teléfono se corta con 429 y no todo intento creó turno.
    assert 429 in vistos
    assert await _contar_turnos_publicos() - antes < tope_tel + 5


async def test_prestacion_con_sena_devuelve_url_pago_y_queda_reservado(
    cliente: AsyncClient,
) -> None:
    # Arrange: prestación ficticia con seña + par verificado.
    import uuid as _uuid

    from app.models.entidades import Prestacion

    id_sena = _uuid.uuid4()
    async with TestSession() as sesion:
        sesion.add(
            Prestacion(
                id=id_sena,
                nombre="Endodoncia Demo Sena Ficticia",
                duracion_min=45,
                requiere_sena=True,
            )
        )
        await sesion.commit()
    await _sembrar_horario(inicio_demo(11, 0).weekday())
    await _sembrar_verificada(DNI_BASE, TEL_BASE)

    try:
        # Act: reserva sobre prestación con seña.
        respuesta = await cliente.post(
            TURNOS_PUBLICOS_URL,
            json=_payload_publico(
                DNI_BASE, TEL_BASE, inicio_demo(11, 0), prestacion_id=id_sena
            ),
            headers={"Idempotency-Key": f"clave-ficticia-{_uuid.uuid4()}"},
        )

        # Assert: reservado (no confirmado aquí) con link de pago opaco.
        assert respuesta.status_code == 201
        datos = respuesta.json()
        assert datos["estado"] == "reservado"
        assert datos["url_pago"]
    finally:
        # Self-cleanup: la prestación ficticia no debe contaminar el seed
        # (el conteo exacto de 6 prestaciones lo verifica C-01, R0).
        # El turno creado la referencia (FK restrictiva): se purga primero.
        from app.models.entidades import Turno

        async with TestSession() as sesion:
            await sesion.execute(
                Turno.__table__.delete().where(
                    Turno.prestacion_id == id_sena  # type: ignore[arg-type]
                )
            )
            await sesion.execute(
                Prestacion.__table__.delete().where(
                    Prestacion.id == id_sena  # type: ignore[arg-type]
                )
            )
            await sesion.commit()


async def test_carrera_get_post_devuelve_409_con_alternativos_sin_pii(
    cliente: AsyncClient,
    cliente_autenticado: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: el slot figura libre; otro lo ocupa antes del POST público.
    await _sembrar_horario(inicio_demo(10, 0).weekday())
    await _sembrar_verificada(DNI_BASE, TEL_BASE)
    base = inicio_demo(10, 0).replace(hour=0, minute=0, second=0, microsecond=0)
    listado = await cliente.get(
        DISPONIBILIDAD_URL,
        params={
            "prestacion_id": str(ID_PRESTACION_LIMPIEZA_45),
            "profesional_id": str(ID_PROFESIONAL_A),
            "desde": base.isoformat(),
            "hasta": (base + timedelta(days=1)).isoformat(),
        },
    )
    assert listado.status_code == 200
    assert any(
        datetime.fromisoformat(s["inicio"]) == inicio_demo(10, 0)
        for s in listado.json()
    )
    ocupante = payload_turno(
        inicio_demo(10, 0),
        paciente_id=None,  # type: ignore[arg-type]
        paciente=payload_paciente_ficticio(),
    )
    ocupante.pop("paciente_id", None)
    respuesta_ok = await cliente_autenticado.post(TURNOS_URL, json=ocupante)
    assert respuesta_ok.status_code == 201

    # Act: la reserva pública llega tarde al mismo slot.
    with caplog.at_level(logging.WARNING):
        respuesta = await cliente.post(
            TURNOS_PUBLICOS_URL,
            json=_payload_publico(DNI_BASE, TEL_BASE, inicio_demo(10, 0)),
            headers={"Idempotency-Key": f"clave-ficticia-{uuid.uuid4()}"},
        )

    # Assert: 409 shape C-01 con alternativos de igual duración, sin PII.
    assert respuesta.status_code == 409
    datos = respuesta.json()
    assert datos["problema"] in PROBLEMAS_409
    assert len(datos["slots_alternativos"]) > 0
    for alt in datos["slots_alternativos"]:
        duracion = datetime.fromisoformat(alt["fin"]) - datetime.fromisoformat(
            alt["inicio"]
        )
        assert duracion == timedelta(minutes=45)
    assert DNI_FICTICIO not in respuesta.text
    assert "5000-0001" not in respuesta.text
    assert DNI_FICTICIO not in caplog.text
    logging.getLogger(__name__).debug("carrera 409 verificada sin PII")
