"""C-08 tasks 1.1+1.5 RED: preferencia MP + `GET /pagar/:token` (R5).

Contrato que la parte 2 (GREEN) debe cumplir:
- `GET /pagar/:token?firma=...` (token opaco C-03, sin JWT, rate limit
  público RN-PU-03): token válido + seña configurada → `200` con
  `init_point` no vacío, `moneda='ARS'`, `estado_pago='pendiente'`; crea
  (o reutiliza) UN `Pago pendiente` por turno y la preferencia MP con
  `currency_id='ARS'` + `metadata={turno_id, presupuesto_id?}` (visible
  en el `FakeMercadoPagoClient` inyectado).
- Monto: `sena_monto_fijo` gana a `sena_porcentaje`; sin fijo es
  `precio_base * sena_porcentaje/100`.
- `requiere_sena` sin monto ni % → `422` de configuración, sin
  preferencia, turno intacto (nunca cero silencioso).
- Token/firma inválidos → `404` idéntico (mismo cuerpo siempre).
- Segundo GET → mismo `init_point`, sin segundo `Pago` (idempotente).

Estado parte 1: el router NO existe → FALLAN en rojo (`404`).
Todo dato sintético (R0); Fake MP inyectado, jamás red real (R5); type
hints siempre (R1); sin PII en asserts (R6); secretos solo env (R7).
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from app.core.security import hashear_password
from app.models.entidades import Prestacion, Turno, Usuario
from httpx import AsyncClient
from sqlalchemy import delete, text

from tests.conftest import (
    MONTO_PRECIO_BASE_FICTICIO,
    MONTO_SENA_FIJO_FICTICIO,
    PORCENTAJE_SENA_FICTICIO,
    FakeMercadoPagoClient,
    TestSession,
    extraer_token_pago,
    inicio_demo,
    inyectar_mp_fake,
    payload_turno,
)

pytestmark = pytest.mark.integration

PAGAR_URL = "/pagar"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_STAFF = "mp.preferencia.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Mp-Preferencia-1234-no-real"


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


async def _prestacion_con_sena(
    nombre: str,
    *,
    precio_base: Decimal | None = None,
    fijo: Decimal | None = None,
    porcentaje: Decimal | None = None,
) -> uuid.UUID:
    """Prestación ficticia con seña (columnas 009 vía SQL — R2, modelo en GREEN)."""
    pid = uuid.uuid4()
    async with TestSession() as sesion:
        sesion.add(
            Prestacion(
                id=pid,
                nombre=nombre,
                duracion_min=45,
                requiere_sena=True,
            )
        )
        await sesion.commit()
        await sesion.execute(
            text(
                "UPDATE prestacion SET precio_base = :pb, sena_monto_fijo = :f, "
                "sena_porcentaje = :p WHERE id = :pid"
            ),
            {"pb": precio_base, "f": fijo, "p": porcentaje, "pid": pid},
        )
        await sesion.commit()
    return pid


async def _limpiar_prestacion(pid: uuid.UUID) -> None:
    async with TestSession() as sesion:
        await sesion.execute(
            text("DELETE FROM pago WHERE turno_id IN (SELECT id FROM turno WHERE prestacion_id = :pid)"),
            {"pid": pid},
        )
        await sesion.execute(
            Turno.__table__.delete().where(Turno.prestacion_id == pid)  # type: ignore[arg-type]
        )
        await sesion.execute(
            Prestacion.__table__.delete().where(Prestacion.id == pid)  # type: ignore[arg-type]
        )
        await sesion.commit()


async def _crear_turno(
    cliente: AsyncClient, access: str, inicio: datetime, prestacion_id: uuid.UUID
) -> dict[str, object]:
    """Arrange: turno `reservado` vía núcleo C-01."""
    respuesta = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio, prestacion_id=prestacion_id),
        headers={"Authorization": f"Bearer {access}"},
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["estado"] == "reservado"
    return dict(respuesta.json())


async def _contar_pagos(turno_id: str) -> int:
    async with TestSession() as sesion:
        return int(
            await sesion.scalar(
                text("SELECT count(*) FROM pago WHERE turno_id = :tid"),
                {"tid": uuid.UUID(turno_id)},
            )
            or 0
        )


async def test_preferencia_valida_devuelve_link_ars_con_metadata(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: turno `reservado` con seña fija + Fake inyectado.
    pid = await _prestacion_con_sena(
        "Endodoncia Seña Fija Ficticia",
        precio_base=MONTO_PRECIO_BASE_FICTICIO,
        fijo=MONTO_SENA_FIJO_FICTICIO,
    )
    inyectar_mp_fake(app, mp_fake)
    try:
        access = await _access(cliente)
        creado = await _crear_turno(cliente, access, inicio_demo(10, 0).replace(day=6), pid)
        token, firma = extraer_token_pago(
            uuid.UUID(str(creado["id"])), str(creado["token_publico"])
        )

        # Act: abrir el link de pago.
        respuesta = await cliente.get(f"{PAGAR_URL}/{token}?firma={firma}")

        # Assert: 200 con link, ARS y pendiente + metadata round-trip en el Fake.
        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["init_point"]
        assert datos["moneda"] == "ARS"
        assert datos["estado_pago"] == "pendiente"
        assert float(datos["monto"]) == float(MONTO_SENA_FIJO_FICTICIO)
        prefs = [l for l in mp_fake.llamadas if l["operacion"] == "crear_preferencia"]
        assert len(prefs) == 1
        assert prefs[0]["metadata"]["turno_id"] == str(creado["id"])
        assert prefs[0]["moneda"] == "ARS"
    finally:
        await _limpiar_prestacion(pid)


async def test_monto_fijo_gana_a_porcentaje(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: prestación con fijo 5000 + 10 % sobre base 20000 (= 2000).
    pid = await _prestacion_con_sena(
        "Endodoncia Fijo Gana Ficticia",
        precio_base=MONTO_PRECIO_BASE_FICTICIO,
        fijo=MONTO_SENA_FIJO_FICTICIO,
        porcentaje=PORCENTAJE_SENA_FICTICIO,
    )
    inyectar_mp_fake(app, mp_fake)
    try:
        access = await _access(cliente)
        creado = await _crear_turno(cliente, access, inicio_demo(11, 0).replace(day=6), pid)
        token, firma = extraer_token_pago(
            uuid.UUID(str(creado["id"])), str(creado["token_publico"])
        )

        # Act: abrir el link de pago.
        respuesta = await cliente.get(f"{PAGAR_URL}/{token}?firma={firma}")

        # Assert: el monto es el fijo (5000), no el 10 % (2000).
        assert respuesta.status_code == 200
        assert float(respuesta.json()["monto"]) == float(MONTO_SENA_FIJO_FICTICIO)
    finally:
        await _limpiar_prestacion(pid)


async def test_porcentaje_sobre_precio_base_sin_fijo(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: prestación solo con 10 % sobre base 20000 → seña 2000.
    pid = await _prestacion_con_sena(
        "Endodoncia Solo Porcentaje Ficticia",
        precio_base=MONTO_PRECIO_BASE_FICTICIO,
        porcentaje=PORCENTAJE_SENA_FICTICIO,
    )
    inyectar_mp_fake(app, mp_fake)
    try:
        access = await _access(cliente)
        creado = await _crear_turno(cliente, access, inicio_demo(12, 0).replace(day=6), pid)
        token, firma = extraer_token_pago(
            uuid.UUID(str(creado["id"])), str(creado["token_publico"])
        )

        # Act: abrir el link de pago.
        respuesta = await cliente.get(f"{PAGAR_URL}/{token}?firma={firma}")

        # Assert: 10 % de 20000 = 2000 en ARS.
        assert respuesta.status_code == 200
        assert float(respuesta.json()["monto"]) == 2000.0
        assert respuesta.json()["moneda"] == "ARS"
    finally:
        await _limpiar_prestacion(pid)


async def test_sena_sin_monto_configurado_422_sin_preferencia(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: `requiere_sena` sin fijo ni (base + %) → error visible.
    pid = await _prestacion_con_sena("Endodoncia Sin Monto Ficticia")
    inyectar_mp_fake(app, mp_fake)
    try:
        access = await _access(cliente)
        creado = await _crear_turno(cliente, access, inicio_demo(13, 0).replace(day=6), pid)
        token, firma = extraer_token_pago(
            uuid.UUID(str(creado["id"])), str(creado["token_publico"])
        )

        # Act: abrir el link de pago sin configuración de monto.
        respuesta = await cliente.get(f"{PAGAR_URL}/{token}?firma={firma}")

        # Assert: 422 sin link ni preferencia, turno intacto.
        assert respuesta.status_code == 422
        assert "init_point" not in respuesta.json()
        prefs = [l for l in mp_fake.llamadas if l["operacion"] == "crear_preferencia"]
        assert prefs == []
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
            assert turno is not None and turno.estado == "reservado"
    finally:
        await _limpiar_prestacion(pid)


async def test_token_invalido_404_identico(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: turno válido con seña (control positivo) + Fake inyectado.
    pid = await _prestacion_con_sena(
        "Endodoncia Token Inválido Ficticia",
        precio_base=MONTO_PRECIO_BASE_FICTICIO,
        fijo=MONTO_SENA_FIJO_FICTICIO,
    )
    inyectar_mp_fake(app, mp_fake)
    try:
        access = await _access(cliente)
        creado = await _crear_turno(cliente, access, inicio_demo(15, 0).replace(day=6), pid)
        token, firma = extraer_token_pago(
            uuid.UUID(str(creado["id"])), str(creado["token_publico"])
        )

        # Act: un GET válido + dos GET inválidos (firma ajena, token al azar).
        valido = await cliente.get(f"{PAGAR_URL}/{token}?firma={firma}")
        primera = await cliente.get(f"{PAGAR_URL}/{token}?firma={'00' * 16}")
        segunda = await cliente.get(f"{PAGAR_URL}/otro-token-ficticio?firma=ff")

        # Assert: el válido resuelve (control positivo) y los inválidos son
        # 404 idénticos — mismo cuerpo, sin distinguir causas ni PII.
        assert valido.status_code == 200
        assert primera.status_code == 404
        assert segunda.status_code == 404
        assert primera.json() == segunda.json()
    finally:
        await _limpiar_prestacion(pid)


async def test_segundo_get_reutiliza_pendiente_sin_duplicar(
    cliente: AsyncClient, app: object, staff: None, mp_fake: FakeMercadoPagoClient
) -> None:
    # Arrange: turno con seña + primer GET que crea el pendiente.
    pid = await _prestacion_con_sena(
        "Endodoncia Reuso Ficticia",
        precio_base=MONTO_PRECIO_BASE_FICTICIO,
        fijo=MONTO_SENA_FIJO_FICTICIO,
    )
    inyectar_mp_fake(app, mp_fake)
    try:
        access = await _access(cliente)
        creado = await _crear_turno(cliente, access, inicio_demo(14, 0).replace(day=6), pid)
        token, firma = extraer_token_pago(
            uuid.UUID(str(creado["id"])), str(creado["token_publico"])
        )
        primera = await cliente.get(f"{PAGAR_URL}/{token}?firma={firma}")
        assert primera.status_code == 200

        # Act: segundo GET del mismo link.
        segunda = await cliente.get(f"{PAGAR_URL}/{token}?firma={firma}")

        # Assert: mismo link, UN solo `Pago` y UNA sola preferencia creada.
        assert segunda.status_code == 200
        assert segunda.json()["init_point"] == primera.json()["init_point"]
        assert await _contar_pagos(str(creado["id"])) == 1
        prefs = [l for l in mp_fake.llamadas if l["operacion"] == "crear_preferencia"]
        assert len(prefs) == 1
    finally:
        await _limpiar_prestacion(pid)
