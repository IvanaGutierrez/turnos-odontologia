"""C-12 task 1.6 RED: robustez conversacional (ambiguo, firma, dedupe, tasa).

Contrato que la parte 2 (GREEN) debe cumplir:
- Mensaje ambiguo ("hola", "gracias", texto vacío) verificado → ayuda con
  las opciones válidas, sin mutar turnos/avisos ni auditar altas.
- Firma ausente/inválida/cuerpo alterado → `401` ciego sin procesar, sin
  mutar, sin auditar contenido y sin PII en logs (regresión C-06 intacta:
  estos tres casos YA pasan en verde; el resto del archivo está en rojo).
- `wa_message_id` duplicado → `200` sin doble mutación ni doble respuesta
  observable (UNA sola auditoría de la mutación).
- Ráfaga del mismo remitente-hash → rate-limit (alguna respuesta `429` o
  con espera), sin caer la agenda.

Todo dato sintético (R0); type hints (R1); jamás red real (R5); placeholder
de firma (R7); desconocido/ambiguo jamás muta ni filtra (R6).
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
from app.models.entidades import Paciente, Turno, Usuario
from tests.conftest import TestSession, hash_destino, payload_turno

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime(2026, 11, 4, 10, 0, tzinfo=BA)

WEBHOOK_URL = "/webhooks/whatsapp"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_STAFF = "wa.conv.robustos.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Wa-Conv-Robustos-1234-no-real"

SECRETO_WEBHOOK_FICTICIO = "secreto-webhook-ficticio-no-real-32b-min"

TEL_REMITENTE = "+54 9 11 15-000-0017"
DNI_REMITENTE = "88300117"
TEL_RAFAGA = "+54 9 11 15-000-0018"


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


async def _crear_reservado(cliente: AsyncClient, access: str) -> dict[str, object]:
    """Arrange: turno testigo `reservado` del remitente vía núcleo C-01."""
    async with TestSession() as sesion:
        await sesion.execute(delete(Paciente).where(Paciente.dni == DNI_REMITENTE))
        sesion.add(
            Paciente(
                nombre="Remitente Robusto Ficticia",
                dni=DNI_REMITENTE,
                telefono=TEL_REMITENTE,
                consentimiento_hc=False,
            )
        )
        await sesion.commit()
        paciente_id = (
            await sesion.execute(select(Paciente).where(Paciente.dni == DNI_REMITENTE))
        ).scalar_one().id
    creado = await cliente.post(
        TURNOS_URL,
        json=payload_turno(
            AHORA + timedelta(hours=49), paciente_id=str(paciente_id)
        ),
        headers={"Authorization": f"Bearer {access}"},
    )
    assert creado.status_code == 201
    return dict(creado.json())


def _firmar(cuerpo: bytes, secreto: str = SECRETO_WEBHOOK_FICTICIO) -> str:
    firma = hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
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


async def _post_wa(cliente: AsyncClient, cuerpo: bytes, firma: str | None) -> object:
    cabeceras: dict[str, str] = {"Content-Type": "application/json"}
    if firma is not None:
        cabeceras["X-Hub-Signature-256"] = firma
    return await cliente.post(WEBHOOK_URL, content=cuerpo, headers=cabeceras)


async def _alatas_turno(turno_id: str) -> list[AuditoriaLog]:
    async with TestSession() as sesion:
        return list(
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion.in_(
                            [
                                "turno_confirmado",
                                "turno_cancelado",
                                "turno_reprogramado",
                            ]
                        ),
                        AuditoriaLog.entidad_id == turno_id,
                    )
                )
            )
            .scalars()
            .all()
        )


@pytest.mark.parametrize("texto", ["hola", "gracias", ""])
async def test_mensaje_ambiguo_responde_ayuda_sin_mutar(
    cliente: AsyncClient, staff: None, texto: str
) -> None:
    # Arrange: turno testigo `reservado` del remitente.
    access = await _access(cliente)
    creado = await _crear_reservado(cliente, access)

    # Act: texto no clasificable verificado (reloj controlado BA).
    cuerpo = _cuerpo_wa(f"wamid.conv-amb-{abs(hash(texto)) % 10000:04d}", TEL_REMITENTE, texto)
    with freeze_time(AHORA):
        respuesta = await _post_wa(cliente, cuerpo, _firmar(cuerpo))

    # Assert: ayuda con las opciones, turno intacto, sin altas auditadas.
    assert respuesta.status_code == 200  # type: ignore[attr-defined]
    minusculas = respuesta.text.lower()  # type: ignore[attr-defined]
    assert "confirmar" in minusculas or "cancelar" in minusculas
    assert "reprogramar" in minusculas or "ayuda" in minusculas
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
        assert turno is not None and turno.estado == "reservado"
    assert await _alatas_turno(str(creado["id"])) == []
    assert TEL_REMITENTE not in respuesta.text  # type: ignore[attr-defined]
    assert DNI_REMITENTE not in respuesta.text  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "caso", ["sin_firma", "firma_invalida", "cuerpo_alterado"]
)
async def test_firma_ausente_invalida_o_alterada_401_sin_procesar(
    cliente: AsyncClient, staff: None, caso: str
) -> None:
    # Arrange: turno testigo + cuerpo base firmado (mutado según caso).
    # NOTA: regresión C-06 — estos tres casos ya están en verde.
    access = await _access(cliente)
    creado = await _crear_reservado(cliente, access)
    async with TestSession() as sesion:
        total = await sesion.execute(select(func.count()).select_from(Turno))
        turnos_antes = int(total.scalar_one())
    cuerpo = _cuerpo_wa("wamid.conv-firma-0001", TEL_REMITENTE, "SÍ")
    if caso == "sin_firma":
        firma: str | None = None
    elif caso == "firma_invalida":
        firma = _firmar(cuerpo, "otro-secreto-ficticio-no-real")
    else:
        # Cuerpo alterado tras firmar: un byte extra invalida el HMAC
        # (la firma se verifica antes de parsear, así que el 401 es ciego).
        cuerpo = _cuerpo_wa("wamid.conv-firma-0001", TEL_REMITENTE, "SÍ") + b" "
        firma = _firmar(_cuerpo_wa("wamid.conv-firma-0001", TEL_REMITENTE, "SÍ"))

    # Act: POST sin firma válida (reloj controlado BA).
    with freeze_time(AHORA):
        respuesta = await _post_wa(cliente, cuerpo, firma)

    # Assert: 401 ciego — sin mutar, sin auditar altas, sin PII.
    assert respuesta.status_code == 401  # type: ignore[attr-defined]
    assert TEL_REMITENTE not in respuesta.text  # type: ignore[attr-defined]
    assert SECRETO_WEBHOOK_FICTICIO not in respuesta.text  # type: ignore[attr-defined]
    async with TestSession() as sesion:
        total = await sesion.execute(select(func.count()).select_from(Turno))
        assert int(total.scalar_one()) == turnos_antes
        turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
        assert turno is not None and turno.estado == "reservado"
    assert await _alatas_turno(str(creado["id"])) == []


async def test_wa_message_id_duplicado_sin_doble_mutacion_ni_respuesta(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno testigo `reservado` del remitente.
    access = await _access(cliente)
    creado = await _crear_reservado(cliente, access)

    # Act: mismo "SÍ" dos veces con idéntico `wa_message_id` (reintento Meta).
    cuerpo = _cuerpo_wa("wamid.conv-dupe-0001", TEL_REMITENTE, "SÍ")
    with freeze_time(AHORA):
        primera = await _post_wa(cliente, cuerpo, _firmar(cuerpo))
        segunda = await _post_wa(cliente, cuerpo, _firmar(cuerpo))

    # Assert: ambas 200, UNA sola mutación y UNA sola auditoría de alta.
    assert primera.status_code == 200  # type: ignore[attr-defined]
    assert segunda.status_code == 200  # type: ignore[attr-defined]
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, uuid.UUID(str(creado["id"])))
        assert turno is not None and turno.estado == "confirmado"
    assert len(await _alatas_turno(str(creado["id"]))) == 1


async def test_rafaga_del_mismo_remitente_activa_rate_limit(
    cliente: AsyncClient, staff: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: tope conversacional bajo por env (patrón C-03/C-05 legible).
    monkeypatch.setenv("WA_CONV_RATE_MAX", "5")
    monkeypatch.setenv("WA_CONV_RATE_WINDOW_S", "60")
    monkeypatch.setenv("WA_CONV_RATE_WINDOW", "60")
    access = await _access(cliente)
    await _crear_reservado(cliente, access)

    # Act: ráfaga de 12 "SÍ" del mismo remitente-hash (reloj controlado).
    with freeze_time(AHORA):
        respuestas = []
        for i in range(12):
            cuerpo = _cuerpo_wa(f"wamid.conv-rl-{i:04d}", TEL_RAFAGA, "SÍ")
            respuestas.append(await _post_wa(cliente, cuerpo, _firmar(cuerpo)))

    # Assert: al menos una frena con 429 o mensaje de espera, sin PII.
    frenadas = [
        r
        for r in respuestas
        if r.status_code == 429  # type: ignore[attr-defined]
        or "esper" in r.text.lower()  # type: ignore[attr-defined]
        or "tard" in r.text.lower()  # type: ignore[attr-defined]
        or "demasiado" in r.text.lower()  # type: ignore[attr-defined]
    ]
    assert frenadas, "la ráfaga debe activar el rate-limit por remitente-hash"
    for r in respuestas:
        assert TEL_RAFAGA not in r.text  # type: ignore[attr-defined]
