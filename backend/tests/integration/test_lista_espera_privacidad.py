"""C-14 task 1.4 RED: privacidad 1-a-1 + blast + veto + fallback (R5/R6).

Contrato que la parte 2 (GREEN) debe cumplir:
- Blast top-N vía worker `ofertar_hueco_liberado(sesion, hueco,
  transporte)`: un mensaje `oferta_lista_espera` por ofertado con SOLO
  su slot (`nombre_pila?, fecha, hora, sede, link` de seña) — jamás
  posiciones, nombres, cantidades ni ningún dato de otros en espera,
  ni en mensajes, responses, `diff`s o logs (R6, Ley 25.326).
- `oferta_lista_espera` es el 4.º tipo utility (plantilla
  `WA_TEMPLATE_OFERTA`); cualquier otro tipo sigue vetado (`422`).
- Transporte WA caído (o paciente `sin_whatsapp`): cascada fallback +
  `aviso_a_recepcion` existentes; la oferta queda registrada igual
  (el TTL corre) y el hueco sigue libre.
- Eventos `lista_espera_creada|oferta_enviada|oferta_expirada|
  lista_espera_asignada|pago_reembolsado` consultables por admin con
  `diff`s mínimos (IDs, estados, score, horarios, montos).

Estado parte 1: sin servicio/worker/tipo nuevo → FALLAN en rojo
(`ModuleNotFoundError`, `404`, cero eventos).
Todo dato sintético (R0); type hints siempre (R1); AAA.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.core.settings import settings
from app.infrastructure.whatsapp.mensajes import TIPOS_UTILITY
from app.services.avisos import TipoAvisoNoPermitidoError, validar_tipo
from tests.conftest import (
    DNI_ESPERA_FICTICIO_1,
    DNI_ESPERA_FICTICIO_2,
    ID_PROFESIONAL_A,
    ID_SILLON_S1,
    LISTA_ESPERA_URL,
    TEL_ESPERA_FICTICIO_1,
    TEL_ESPERA_FICTICIO_2,
    FakeWhatsAppTransport,
    TestSession,
    crear_paciente_espera,
    crear_usuario_ficticio,
    eliminar_usuario_ficticio,
    hash_destino,
)
from tests.integration.test_lista_espera_concurrencia import _diffs
from tests.integration.test_lista_espera_oferta import (
    _alta_espera,
    _crear_y_cancelar_hueco,
    _limpiar_prestacion,
    _prestacion_sena,
)

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
HUECO = datetime(2026, 11, 20, 10, 0, tzinfo=BA)
SENA_MEDIA = Decimal("5000.00")

AUDITORIA_URL = "/api/v1/auditoria"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_ADMIN = "espera.priv.admin.ficticio@consultorio.example"
EMAIL_RECEPCION = "espera.priv.recepcion.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Espera-Priv-1234-no-real"

NOMBRE_P1 = "Espera Priv Uno Ficticia"
NOMBRE_P2 = "Espera Priv Dos Ficticia"

# Único vocabulario permitido en el mensaje de oferta (R6): slot propio.
VARIABLES_OFERTA = frozenset({"nombre_pila", "fecha", "hora", "sede", "link_gestion"})


@pytest_asyncio.fixture()
async def staff() -> AsyncGenerator[None, None]:
    """Admin + recepción ficticios; self-cleanup en RED."""
    await crear_usuario_ficticio(EMAIL_ADMIN, PASSWORD_FICTICIA, "admin")
    await crear_usuario_ficticio(EMAIL_RECEPCION, PASSWORD_FICTICIA, "recepcion")
    yield
    for email in (EMAIL_ADMIN, EMAIL_RECEPCION):
        await eliminar_usuario_ficticio(email)


async def _access(cliente: AsyncClient, email: str) -> str:
    login = await cliente.post(
        LOGIN_URL, json={"email": email, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


def _hueco(prestacion_id: uuid.UUID) -> dict[str, object]:
    return {
        "hueco_origen_id": uuid.uuid4(),
        "profesional_id": ID_PROFESIONAL_A,
        "sillon_id": ID_SILLON_S1,
        "prestacion_id": prestacion_id,
        "inicio": HUECO,
        "fin": HUECO + timedelta(minutes=45),
    }


async def test_blast_oferta_plantilla_y_solo_slot_propio(
    cliente: AsyncClient,
    staff: None,
    transporte_fake: FakeWhatsAppTransport,
) -> None:
    # Arrange: 2 entradas elegibles con PII marcada + hueco publicado.
    from app.services import lista_espera as svc_lista_espera

    plantilla_esperada = settings.wa_template_oferta
    pid = await _prestacion_sena("Limpieza Blast Priv Ficticia", SENA_MEDIA)
    try:
        access = await _access(cliente, EMAIL_RECEPCION)
        p1 = await crear_paciente_espera(
            nombre=NOMBRE_P1, dni=DNI_ESPERA_FICTICIO_1,
            telefono=TEL_ESPERA_FICTICIO_1,
        )
        p2 = await crear_paciente_espera(
            nombre=NOMBRE_P2, dni=DNI_ESPERA_FICTICIO_2,
            telefono=TEL_ESPERA_FICTICIO_2,
        )
        await _alta_espera(
            cliente, access, p1, pid, HUECO - timedelta(days=1), HUECO + timedelta(days=7)
        )
        await _alta_espera(
            cliente, access, p2, pid, HUECO - timedelta(days=1), HUECO + timedelta(days=7)
        )

        # Act: el worker oferta el hueco con el transporte inyectado.
        async with TestSession() as sesion:
            await svc_lista_espera.ofertar_hueco_liberado(
                sesion, _hueco(pid), transporte_fake
            )
            await sesion.commit()

        # Assert: UN mensaje por ofertado, plantilla utility, 1-a-1 estricto.
        assert len(transporte_fake.llamadas) == 2
        for llamada in transporte_fake.llamadas:
            assert llamada["plantilla"] == plantilla_esperada
            variables = dict(llamada["variables"])  # type: ignore[arg-type]
            assert set(variables) <= VARIABLES_OFERTA
            texto = " ".join(str(v) for v in variables.values())
            assert "2026-11-20" in texto and "10:00" in texto
        textos = [
            " ".join(str(v) for v in dict(ll["variables"]).values())  # type: ignore[arg-type]
            for ll in transporte_fake.llamadas
        ]
        for texto in textos:
            for sonda in (
                DNI_ESPERA_FICTICIO_1, DNI_ESPERA_FICTICIO_2,
                TEL_ESPERA_FICTICIO_1, TEL_ESPERA_FICTICIO_2,
            ):
                assert sonda not in texto
        assert NOMBRE_P2 not in textos[0] or NOMBRE_P1 not in textos[0]
        unidos = " ".join(textos)
        assert NOMBRE_P1 in unidos and NOMBRE_P2 in unidos
        # Destinos solo como hash (R6): jamás el teléfono crudo.
        hashes = {str(ll["destino_hash"]) for ll in transporte_fake.llamadas}
        assert hashes == {
            hash_destino(TEL_ESPERA_FICTICIO_1),
            hash_destino(TEL_ESPERA_FICTICIO_2),
        }
    finally:
        await _limpiar_prestacion(pid)


async def test_veto_marketing_intacto_con_tipo_nuevo() -> None:
    # Arrange: nada (puro dominio de tipos utility).

    # Act: el catálogo admite el tipo nuevo y veta el resto.
    admite_oferta = "oferta_lista_espera" in TIPOS_UTILITY
    with pytest.raises(TipoAvisoNoPermitidoError):
        validar_tipo("promocion")

    # Assert: veto intacto + tipo nuevo admitido (hoy: 3 tipos → falla).
    assert admite_oferta


async def test_fallo_wa_degrada_recepcion_sin_perder_hueco(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: transporte siempre caído + 1 entrada elegible.
    from app.services import lista_espera as svc_lista_espera

    caido = FakeWhatsAppTransport(fallos=["5xx", "5xx", "5xx", "5xx"])
    pid = await _prestacion_sena("Limpieza Fallback Ficticia", SENA_MEDIA)
    try:
        access = await _access(cliente, EMAIL_RECEPCION)
        pac = await crear_paciente_espera(
            nombre=NOMBRE_P1, dni=DNI_ESPERA_FICTICIO_1,
            telefono=TEL_ESPERA_FICTICIO_1,
        )
        await _alta_espera(
            cliente, access, pac, pid, HUECO - timedelta(days=1), HUECO + timedelta(days=7)
        )

        # Act: ofertar con WA caído.
        async with TestSession() as sesion:
            await svc_lista_espera.ofertar_hueco_liberado(
                sesion, _hueco(pid), caido
            )
            await sesion.commit()

        # Assert: oferta registrada (el TTL corre) + recepción avisada,
        # hueco libre (ningún turno creado).
        async with TestSession() as sesion:
            n_ofertas = await sesion.scalar(text("SELECT count(*) FROM oferta_espera"))
            assert int(n_ofertas or 0) == 1
            n_turnos = await sesion.scalar(
                text(
                    "SELECT count(*) FROM turno WHERE profesional_id = :prof "
                    "AND inicio = :ini AND estado <> 'cancelado'"
                ),
                {"prof": ID_PROFESIONAL_A, "ini": HUECO},
            )
            assert int(n_turnos or 0) == 0
        assert len(await _diffs("aviso_a_recepcion")) >= 1
    finally:
        await _limpiar_prestacion(pid)


async def test_endpoints_espera_sin_filtrar_otros(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: DOS entradas de distintos pacientes con PII marcada.
    pid = await _prestacion_sena("Limpieza Sin Fuga Ficticia", SENA_MEDIA)
    try:
        access = await _access(cliente, EMAIL_RECEPCION)
        p1 = await crear_paciente_espera(
            nombre=NOMBRE_P1, dni=DNI_ESPERA_FICTICIO_1,
            telefono=TEL_ESPERA_FICTICIO_1,
        )
        p2 = await crear_paciente_espera(
            nombre=NOMBRE_P2, dni=DNI_ESPERA_FICTICIO_2,
            telefono=TEL_ESPERA_FICTICIO_2,
        )
        e1 = await _alta_espera(
            cliente, access, p1, pid, HUECO - timedelta(days=1), HUECO + timedelta(days=7)
        )

        # Act: leer la entrada propia y listar la espera.
        una = await cliente.get(
            f"{LISTA_ESPERA_URL}/{e1}",
            headers={"Authorization": f"Bearer {access}"},
        )
        todas = await cliente.get(
            LISTA_ESPERA_URL,
            headers={"Authorization": f"Bearer {access}"},
        )

        # Assert: 200 y ningún rastro del OTRO en espera en ningún cuerpo.
        assert una.status_code == 200
        assert todas.status_code == 200
        cuerpos = una.text + todas.text
        for sonda in (NOMBRE_P2, DNI_ESPERA_FICTICIO_2, TEL_ESPERA_FICTICIO_2):
            assert sonda not in cuerpos
        _ = p2
    finally:
        await _limpiar_prestacion(pid)


async def test_eventos_lista_espera_auditados_sin_pii(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: alta + cancelación que dispara el flujo (PII marcada).
    pid = await _prestacion_sena("Limpieza Eventos Ficticia", SENA_MEDIA)
    try:
        access = await _access(cliente, EMAIL_RECEPCION)
        admin = await _access(cliente, EMAIL_ADMIN)
        pac = await crear_paciente_espera(
            nombre=NOMBRE_P1, dni=DNI_ESPERA_FICTICIO_1,
            telefono=TEL_ESPERA_FICTICIO_1,
        )
        await _alta_espera(
            cliente, access, pac, pid, HUECO - timedelta(days=1), HUECO + timedelta(days=7)
        )
        await _crear_y_cancelar_hueco(cliente, access, pid, HUECO + timedelta(days=5))

        # Act: admin consulta la bitácora de espera.
        eventos: dict[str, list[dict[str, object]]] = {}
        for accion in ("lista_espera_creada", "oferta_enviada"):
            r = await cliente.get(
                AUDITORIA_URL,
                params={"accion": accion},
                headers={"Authorization": f"Bearer {admin}"},
            )
            assert r.status_code == 200
            eventos[accion] = list(r.json()["items"])

        # Assert: ambos eventos existen con diffs mínimos, sin PII.
        assert len(eventos["lista_espera_creada"]) == 1
        assert len(eventos["oferta_enviada"]) == 1
        for accion, items in eventos.items():
            for item in items:
                assert item["accion"] == accion
                diff_txt = str(item["diff"])
                for sonda in (
                    NOMBRE_P1, DNI_ESPERA_FICTICIO_1, TEL_ESPERA_FICTICIO_1,
                ):
                    assert sonda not in diff_txt
    finally:
        await _limpiar_prestacion(pid)
