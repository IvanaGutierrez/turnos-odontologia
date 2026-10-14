"""C-12 task 1.4 RED: "REPROGRAMAR" en dos pasos con slots reales (R5).

Contrato que la parte 2 (GREEN) debe cumplir
(`notificaciones/confirmacion-conversacional`):
- "REPROGRAMAR" verificado del remitente sobre turno `reservado|confirmado`
  → `200` con slots reales (disponibilidad C-03) en opciones numeradas con
  fecha/hora ISO + oferta efímera `wa:conv:{remitente_hash}` en Redis con
  TTL (`WA_CONV_TTL_MIN`, `SET NX`).
- Elegir una opción vigente (número de opción) → turno nuevo con el mismo
  `token_publico`, original a `reprogramado` enlazado por
  `reprogramado_de_id` + auditoría `turno_reprogramado` (`canal=whatsapp`).
- Elección tras expirar la oferta → invita a reiniciar sin mutar nada.
- Slot ocupado entre oferta y elección → `409` conversacional con
  alternativos, original intacto.

Estado parte 1: el webhook solo acusa recibo (sin propuesta, sin oferta en
Redis, sin writeback) → FALLAN en rojo.
Todo dato sintético (R0); type hints (R1); jamás red real (R5); placeholder
de firma (R7); respuestas/auditoría sin PII (R6).
"""

import hashlib
import hmac
import json
import re
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from fastapi import FastAPI
from freezegun import freeze_time
from httpx import AsyncClient
from sqlalchemy import delete, func, select

from app.core.security import hashear_password
from app.models.auditoria import AuditoriaLog
from app.models.entidades import Paciente, Turno, Usuario
from tests.conftest import TestSession, hash_destino, payload_turno

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime(2026, 11, 4, 10, 0, tzinfo=BA)

WEBHOOK_URL = "/webhooks/whatsapp"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"
AUTOGESTION_URL = "/api/v1/turnos/publicos"

EMAIL_STAFF = "wa.conv.reprog.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Wa-Conv-Reprog-1234-no-real"

SECRETO_WEBHOOK_FICTICIO = "secreto-webhook-ficticio-no-real-32b-min"

TEL_REMITENTE = "+54 9 11 15-000-0015"
DNI_REMITENTE = "88300115"

ISO_EN_TEXTO = re.compile(r"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}")


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


async def _crear_confirmado(
    cliente: AsyncClient, access: str, inicio: datetime
) -> dict[str, object]:
    """Arrange: turno del remitente confirmado por token C-05."""
    async with TestSession() as sesion:
        await sesion.execute(delete(Paciente).where(Paciente.dni == DNI_REMITENTE))
        sesion.add(
            Paciente(
                nombre="Remitente Reprogramación Ficticia",
                dni=DNI_REMITENTE,
                telefono=TEL_REMITENTE,
                consentimiento_hc=False,
            )
        )
        await sesion.commit()
        paciente_id = (
            (
                await sesion.execute(
                    select(Paciente).where(Paciente.dni == DNI_REMITENTE)
                )
            )
            .scalar_one()
            .id
        )
    creado = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio, paciente_id=str(paciente_id)),
        headers={"Authorization": f"Bearer {access}"},
    )
    assert creado.status_code == 201
    with freeze_time(AHORA):
        confirmado = await cliente.post(
            f"{AUTOGESTION_URL}/{creado.json()['token_publico']}/confirmar"
        )
    assert confirmado.status_code == 200
    return dict(creado.json())


def _firmar(cuerpo: bytes) -> str:
    firma = hmac.new(
        SECRETO_WEBHOOK_FICTICIO.encode(), cuerpo, hashlib.sha256
    ).hexdigest()
    return f"sha256={firma}"


async def _post_wa(cliente: AsyncClient, wa_id: str, texto: str) -> Any:
    cuerpo = json.dumps(
        {
            "wa_message_id": wa_id,
            "remitente": TEL_REMITENTE,
            "remitente_hash": hash_destino(TEL_REMITENTE),
            "timestamp": AHORA.isoformat(),
            "tipo": "texto",
            "texto": texto,
        }
    ).encode("utf-8")
    return await cliente.post(
        WEBHOOK_URL,
        content=cuerpo,
        headers={
            "X-Hub-Signature-256": _firmar(cuerpo),
            "Content-Type": "application/json",
        },
    )


async def _contar_turnos() -> int:
    async with TestSession() as sesion:
        total = await sesion.execute(select(func.count()).select_from(Turno))
        return int(total.scalar_one())


async def _claves_oferta(app: FastAPI) -> list[str]:
    redis: Any = app.state.redis
    claves = await redis.keys("wa:conv:*")
    return [str(c) for c in claves]


async def test_reprogramar_propone_slots_y_guarda_oferta_con_ttl(
    cliente: AsyncClient, app: FastAPI, staff: None
) -> None:
    # Arrange: `confirmado` del remitente, inicio a +49 h.
    access = await _access(cliente)
    await _crear_confirmado(cliente, access, AHORA + timedelta(hours=49))

    # Act: "REPROGRAMAR" verificado (reloj controlado BA).
    with freeze_time(AHORA):
        respuesta = await _post_wa(cliente, "wamid.conv-rep-0001", "REPROGRAMAR")

    # Assert: opciones numeradas con fecha/hora + oferta `wa:conv:*` con TTL.
    assert respuesta.status_code == 200
    cuerpo = respuesta.text.lower()
    assert "1" in cuerpo and ("2" in cuerpo or "opcion" in cuerpo or "slot" in cuerpo)
    assert ISO_EN_TEXTO.search(respuesta.text) is not None
    claves = await _claves_oferta(app)
    assert len(claves) == 1
    ttl = await app.state.redis.ttl(claves[0])
    assert isinstance(ttl, int) and ttl > 0
    assert TEL_REMITENTE not in respuesta.text
    assert DNI_REMITENTE not in respuesta.text


async def test_elegir_opcion_vigente_reprograma_con_token_conservado(
    cliente: AsyncClient, app: FastAPI, staff: None
) -> None:
    # Arrange: `confirmado` del remitente + oferta pedida por chat.
    access = await _access(cliente)
    creado = await _crear_confirmado(cliente, access, AHORA + timedelta(hours=49))
    token_original = str(creado["token_publico"])
    total_antes = await _contar_turnos()
    with freeze_time(AHORA):
        propuesta = await _post_wa(cliente, "wamid.conv-rep-0002", "REPROGRAMAR")
        assert propuesta.status_code == 200
        # Act: elegir la primera opción ofertada (reloj controlado BA).
        eleccion = await _post_wa(cliente, "wamid.conv-rep-0003", "1")

    # Assert: turno nuevo con idéntico token + original `reprogramado` + audit.
    assert eleccion.status_code == 200
    assert await _contar_turnos() == total_antes + 1
    async with TestSession() as sesion:
        original = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
        assert original is not None and original.estado == "reprogramado"
        nuevo = (
            await sesion.execute(
                select(Turno).where(
                    Turno.reprogramado_de_id == uuid.UUID(str(creado["id"]))
                )
            )
        ).scalar_one()
        assert str(nuevo.token_publico) == token_original
        filas = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "turno_reprogramado",
                        AuditoriaLog.entidad_id == str(creado["id"]),
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(list(filas)) == 1


async def test_oferta_expirada_invita_a_reiniciar_sin_mutar(
    cliente: AsyncClient, app: FastAPI, staff: None
) -> None:
    # Arrange: oferta pedida y luego expirada (simula TTL `WA_CONV_TTL_MIN`).
    access = await _access(cliente)
    creado = await _crear_confirmado(cliente, access, AHORA + timedelta(hours=49))
    total_antes = await _contar_turnos()
    with freeze_time(AHORA):
        propuesta = await _post_wa(cliente, "wamid.conv-rep-0004", "REPROGRAMAR")
        assert propuesta.status_code == 200
        for clave in await _claves_oferta(app):
            await app.state.redis.delete(clave)
        # Act: elegir cuando ya no hay oferta vigente.
        respuesta = await _post_wa(cliente, "wamid.conv-rep-0005", "1")

    # Assert: invita a reiniciar (nombra reprogramar/expirado) sin mutar nada.
    assert respuesta.status_code == 200
    cuerpo = respuesta.text.lower()
    assert "reprogramar" in cuerpo or "expir" in cuerpo or "venc" in cuerpo
    assert await _contar_turnos() == total_antes
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
        assert turno is not None and turno.estado == "confirmado"


async def test_slot_ocupado_entre_oferta_y_eleccion_409_con_alternativos(
    cliente: AsyncClient, app: FastAPI, staff: None
) -> None:
    # Arrange: oferta pedida + el primer slot ofertado lo ocupa un tercero.
    access = await _access(cliente)
    creado = await _crear_confirmado(cliente, access, AHORA + timedelta(hours=49))
    total_antes = await _contar_turnos()
    with freeze_time(AHORA):
        propuesta = await _post_wa(cliente, "wamid.conv-rep-0006", "REPROGRAMAR")
        assert propuesta.status_code == 200
        opciones = ISO_EN_TEXTO.findall(propuesta.text)
        assert opciones, "la propuesta debe ofertar slots con fecha/hora ISO"
        # El regex del contrato captura hasta minutos (sin zona); el schema
        # exige `AwareDatetime`: se asume zona AR (los slots ofertados viajan
        # con offset y tienen segundo 00, así coincide exacto).
        inicio_bloqueo = datetime.fromisoformat(opciones[0])
        if inicio_bloqueo.tzinfo is None:
            inicio_bloqueo = inicio_bloqueo.replace(tzinfo=BA)
        access_congelado = await _access(cliente)
        bloqueo = await cliente.post(
            TURNOS_URL,
            json=payload_turno(inicio_bloqueo),
            headers={"Authorization": f"Bearer {access_congelado}"},
        )
        assert bloqueo.status_code == 201
        # Act: elegir el slot que acaba de ocuparse.
        respuesta = await _post_wa(cliente, "wamid.conv-rep-0007", "1")

    # Assert: 409 conversacional con alternativos, original intacto.
    assert respuesta.status_code == 409
    cuerpo = respuesta.text.lower()
    assert "ocup" in cuerpo or "alternativ" in cuerpo
    assert await _contar_turnos() == total_antes + 1
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
        assert turno is not None and turno.estado == "confirmado"
