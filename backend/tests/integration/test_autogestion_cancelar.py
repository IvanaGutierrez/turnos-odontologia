"""C-05 task 1.3 RED: cancelar turno con antelación mínima (freezegun, R5).

Contrato que la parte 2 (GREEN) debe cumplir (`agenda/autogestion-paciente`):
- `POST /api/v1/turnos/publicos/:token/cancelar` sin JWT: `reservado|confirmado`
  → `cancelado` (`200`) solo si `inicio - ahora >= CANCEL_MIN_HOURS`
  (default 12 h, env); persiste `motivo_cancelacion?` + `cancelado_at` y
  audita `turno_cancelado` sin PII; el slot queda liberado (el `cancelado`
  entra en `ESTADOS_INACTIVOS` del predicado GiST → el rango es reutilizable).
- Fuera de término → `422` (`problema=fuera_de_termino` + `horas_restantes`
  + texto de `CANCEL_POLICY_TEXT`) sin mutar nada.
- Duplicado sobre `cancelado` → `200` idempotente sin re-auditar.

Estado parte 1: el router público NO existe → FALLAN en rojo (404).
Reloj controlado con freezegun en `America/Argentina/Buenos_Aires`.
Todo dato sintético (R0); type hints siempre (R1).
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from freezegun import freeze_time
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.security import hashear_password
from app.models.auditoria import AuditoriaLog
from app.models.entidades import Turno, Usuario
from tests.conftest import DNI_FICTICIO, TestSession, payload_turno

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime(2026, 11, 4, 10, 0, tzinfo=BA)

AUTOGESTION_URL = "/api/v1/turnos/publicos"
TURNOS_URL = "/api/v1/turnos"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_STAFF = "autogestion.cancelar.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Autogestion-Cancelar-1234-no-real"


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


async def _crear(
    cliente: AsyncClient, access: str, inicio: datetime
) -> dict[str, object]:
    """Arrange: turno `reservado` vía núcleo C-01 (con reloj congelado)."""
    respuesta = await cliente.post(
        TURNOS_URL,
        json=payload_turno(inicio),
        headers={"Authorization": f"Bearer {access}"},
    )
    assert respuesta.status_code == 201
    return dict(respuesta.json())


async def test_cancelar_en_termino_cancela_y_libera_slot(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno a 48 h de `ahora` (> CANCEL_MIN_HOURS=12 h).
    # Login + alta con el reloj real (el JWT expira en tiempo real y la
    # primera request templa las rutas; solo el Act público se congela).
    access = await _access(cliente)
    creado = await _crear(cliente, access, AHORA + timedelta(hours=48))

    # Act: cancelar en término con motivo ficticio (reloj controlado).
    with freeze_time(AHORA):
        respuesta = await cliente.post(
            f"{AUTOGESTION_URL}/{creado['token_publico']}/cancelar",
            json={"motivo": "Viaje ficticio demo"},
        )

    # Assert: 200 `cancelado` + motivo/`cancelado_at` + auditoría sin PII.
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "cancelado"
    async with TestSession() as sesion:
        turno = await sesion.get(Turno, creado["id"])  # type: ignore[arg-type]
        assert turno is not None
        assert turno.motivo_cancelacion == "Viaje ficticio demo"
        assert turno.cancelado_at is not None
        filas = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "turno_cancelado",
                        AuditoriaLog.entidad_id == creado["id"],
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(filas) == 1
    assert DNI_FICTICIO not in str(filas[0].diff)

    # Assert: slot liberado (el mismo rango/profesional/sillón da 201).
    reuso = await cliente.post(
        TURNOS_URL,
        json=payload_turno(AHORA + timedelta(hours=48)),
        headers={"Authorization": f"Bearer {access}"},
    )
    assert reuso.status_code == 201


async def test_cancelar_fuera_de_termino_422_con_politica_sin_mutar(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno a 2 h de `ahora` (< CANCEL_MIN_HOURS=12 h).
    access = await _access(cliente)
    creado = await _crear(cliente, access, AHORA + timedelta(hours=2))

    # Act: cancelar fuera de término (reloj controlado).
    with freeze_time(AHORA):
        respuesta = await cliente.post(
            f"{AUTOGESTION_URL}/{creado['token_publico']}/cancelar",
            json={"motivo": "Imprevisto ficticio demo"},
        )

        # Assert: 422 con política del consultorio y estado intacto.
        assert respuesta.status_code == 422
        datos = respuesta.json()
        assert datos["problema"] == "fuera_de_termino"
        assert "horas_restantes" in datos
        assert datos["politica"]
        async with TestSession() as sesion:
            turno = await sesion.get(Turno, creado["id"])  # type: ignore[arg-type]
            assert turno is not None and turno.estado == "reservado"


async def test_cancelar_duplicado_idempotente(
    cliente: AsyncClient, staff: None
) -> None:
    # Arrange: turno a 48 h de `ahora`, ya cancelado una vez.
    access = await _access(cliente)
    creado = await _crear(cliente, access, AHORA + timedelta(hours=48))
    url = f"{AUTOGESTION_URL}/{creado['token_publico']}/cancelar"
    with freeze_time(AHORA):
        primera = await cliente.post(url, json={"motivo": "Duplicado demo"})
        assert primera.status_code == 200

        # Act: segunda cancelación del mismo token.
        segunda = await cliente.post(url, json={"motivo": "Duplicado demo"})

        # Assert: 200 `cancelado` sin duplicar auditoría.
        assert segunda.status_code == 200
        assert segunda.json()["estado"] == "cancelado"
        async with TestSession() as sesion:
            filas = (
                (
                    await sesion.execute(
                        select(AuditoriaLog).where(
                            AuditoriaLog.accion == "turno_cancelado",
                            AuditoriaLog.entidad_id == creado["id"],
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(filas) == 1
