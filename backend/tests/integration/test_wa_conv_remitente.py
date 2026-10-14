"""C-12 task 1.2 RED: remitente desconocido / ambiguo jamás muta (R6).

Contrato que la parte 2 (GREEN) debe cumplir
(`notificaciones/confirmacion-conversacional`):
- "SÍ" verificado de un número sin turnos vigentes asociados → `200` con el
  link de gestión genérico (el mismo para todos, sin confirmar ni negar
  existencia), cero mutaciones en turnos/avisos y cero PII (DNI, teléfonos,
  HC, tokens) en respuesta, diffs y logs.
- Dos turnos futuros el mismo día para el mismo remitente → pide elegir
  (nombra fecha/hora/sede de cada candidato) sin mutar nada.

Estado parte 1: el webhook solo acusa recibo (`{"estado": "recibido"}`,
sin link ni desambiguación) → FALLAN en rojo.
Todo dato sintético (R0); type hints (R1); jamás red real (R5); firma con
placeholder de la suite (R7); desconocido jamás muta ni filtra (R6).
"""

import hashlib
import hmac
import json
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from freezegun import freeze_time
from httpx import AsyncClient
from sqlalchemy import delete, func, select

from app.core.security import hashear_password
from app.models.auditoria import AuditoriaLog
from app.models.aviso_envio import AvisoEnvio
from app.models.entidades import Paciente, Turno, Usuario
from tests.conftest import (
    ID_PRESTACION_CONSULTA_30,
    TestSession,
    hash_destino,
    payload_turno,
)

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime(2026, 11, 4, 10, 0, tzinfo=BA)

WEBHOOK_URL = "/webhooks/whatsapp"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_STAFF = "wa.conv.remitente.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Wa-Conv-Remitente-1234-no-real"

SECRETO_WEBHOOK_FICTICIO = "secreto-webhook-ficticio-no-real-32b-min"

TEL_DESCONOCIDO = "+54 9 11 15-000-0012"
TEL_CONOCIDO = "+54 9 11 15-000-0013"
DNI_CONOCIDO = "88300113"


@pytest_asyncio.fixture()
async def staff() -> AsyncGenerator[None, None]:
    """Usuario recepción sintético (turno testigo para no-mutación)."""
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


def _firmar(cuerpo: bytes) -> str:
    firma = hmac.new(
        SECRETO_WEBHOOK_FICTICIO.encode(), cuerpo, hashlib.sha256
    ).hexdigest()
    return f"sha256={firma}"


def _cuerpo_wa(wa_id: str, remitente: str, texto: str) -> bytes:
    return json.dumps(
        {
            "wa_message_id": wa_id,
            "remitente": remitente,
            "remitente_hash": hash_destino(remitente),
            "timestamp": AHORA.isoformat(),
            "tipo": "texto",
            "texto": texto,
        }
    ).encode("utf-8")


async def _post_wa(cliente: AsyncClient, cuerpo: bytes) -> object:
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


async def _contar_avisos() -> int:
    async with TestSession() as sesion:
        total = await sesion.execute(select(func.count()).select_from(AvisoEnvio))
        return int(total.scalar_one())


async def _auditorias_turno(turno_id: str) -> list[AuditoriaLog]:
    async with TestSession() as sesion:
        return list(
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.entidad == "turno",
                        AuditoriaLog.entidad_id == turno_id,
                    )
                )
            )
            .scalars()
            .all()
        )


async def _crear_paciente_conocido() -> uuid.UUID:
    async with TestSession() as sesion:
        await sesion.execute(delete(Paciente).where(Paciente.dni == DNI_CONOCIDO))
        sesion.add(
            Paciente(
                nombre="Paciente Doble Turno Ficticia",
                dni=DNI_CONOCIDO,
                telefono=TEL_CONOCIDO,
                consentimiento_hc=False,
            )
        )
        await sesion.commit()
        fila = (
            await sesion.execute(select(Paciente).where(Paciente.dni == DNI_CONOCIDO))
        ).scalar_one()
        return fila.id


async def test_si_remitente_desconocido_responde_link_sin_mutar_ni_pii(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno testigo `reservado` + conteos base (turnos/avisos).
    access = await _access(cliente)
    testigo = await cliente.post(
        TURNOS_URL,
        json=payload_turno(AHORA + timedelta(hours=49)),
        headers={"Authorization": f"Bearer {access}"},
    )
    assert testigo.status_code == 201
    turnos_antes = await _contar_turnos()
    avisos_antes = await _contar_avisos()

    # Act: "SÍ" verificado desde un número sin turnos vigentes.
    with freeze_time(AHORA):
        respuesta = await _post_wa(
            cliente, _cuerpo_wa("wamid.conv-desc-0001", TEL_DESCONOCIDO, "SÍ")
        )

    # Assert: 200 con link de gestión genérico, cero mutaciones, cero PII.
    assert respuesta.status_code == 200  # type: ignore[attr-defined]
    cuerpo = respuesta.text.lower()  # type: ignore[attr-defined]
    assert "gestion" in cuerpo
    assert TEL_DESCONOCIDO not in respuesta.text  # type: ignore[attr-defined]
    assert "88300113" not in respuesta.text  # type: ignore[attr-defined]
    assert await _contar_turnos() == turnos_antes
    assert await _contar_avisos() == avisos_antes
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, uuid.UUID(str(testigo.json()["id"])))
        assert turno is not None and turno.estado == "reservado"


async def test_dos_turnos_mismo_dia_pide_elegir_sin_mutar(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: dos `reservado` el mismo día para el mismo remitente.
    access = await _access(cliente)
    paciente_id = await _crear_paciente_conocido()
    dia = (AHORA + timedelta(days=2)).replace(hour=0, minute=0)
    cabeceras = {"Authorization": f"Bearer {access}"}
    primero = await cliente.post(
        TURNOS_URL,
        json=payload_turno(dia.replace(hour=10), paciente_id=str(paciente_id)),
        headers=cabeceras,
    )
    segundo = await cliente.post(
        TURNOS_URL,
        json=payload_turno(
            dia.replace(hour=12),
            paciente_id=str(paciente_id),
            prestacion_id=ID_PRESTACION_CONSULTA_30,
        ),
        headers=cabeceras,
    )
    assert primero.status_code == 201
    assert segundo.status_code == 201

    # Act: "SÍ" verificado del remitente con dos candidatos el mismo día.
    with freeze_time(AHORA):
        respuesta = await _post_wa(
            cliente, _cuerpo_wa("wamid.conv-amb-0001", TEL_CONOCIDO, "SÍ")
        )

    # Assert: 200 que pide elegir (nombra opciones) sin mutar ni auditar alta.
    assert respuesta.status_code == 200  # type: ignore[attr-defined]
    cuerpo = respuesta.text.lower()  # type: ignore[attr-defined]
    assert "eleg" in cuerpo or ("1" in cuerpo and "2" in cuerpo)
    async with TestSession() as sesion:
        for creado in (primero, segundo):
            turno = await sesion.get(Turno, uuid.UUID(str(creado.json()["id"])))
            assert turno is not None and turno.estado == "reservado"
    # Sin altas conversacionales: el Arrange (`POST /turnos`) deja su
    # `turno_creado` propio, así que se filtra por acción de mutación
    # (mismo criterio que `_alatas_turno` en `test_wa_conv_robustos.py`).
    for creado in (primero, segundo):
        altas = [
            a
            for a in await _auditorias_turno(str(creado.json()["id"]))
            if a.accion in ("turno_confirmado", "turno_cancelado", "turno_reprogramado")
        ]
        assert altas == []
    assert TEL_CONOCIDO not in respuesta.text  # type: ignore[attr-defined]
    assert DNI_CONOCIDO not in respuesta.text  # type: ignore[attr-defined]
