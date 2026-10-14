"""C-04 task 1.4 RED: CRUD de configuración con RBAC estricto.

Contrato que la parte 2 (GREEN) debe cumplir (`agenda/configuracion-agenda`):
- CRUD de `profesionales`, `sillones`, `prestaciones` y `horarios/bloqueos`
  solo `admin` (recurso `configuracion_agenda`): escritura no-admin →
  `403` + `acceso_denegado` auditado, sin mutar nada.
- `admin` crea una prestación ficticia → `201`; `GET /api/v1/prestaciones`
  como `recepcion` la incluye; el alta queda auditada sin PII.
- `odontologo` lee su propia agenda (`GET /api/v1/agenda?vista=dia&
  profesional_id=<propio>` → `200`) pero `DELETE /api/v1/sillones/<id>`
  → `403` + evento auditado.
- Catálogo válido o `422`: `duracion_min > 0`, `hora_inicio < hora_fin`
  con `dia_semana` 0–6, bloqueo con `desde < hasta`; inválidos → `422`
  sin crear registros.

Estado parte 1: los endpoints CRUD NO existen → FALLAN en rojo (404).
Todo dato sintético (R0); type hints siempre (R1).
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, func, select

from app.core.security import hashear_password
from app.models.auditoria import AuditoriaLog
from app.models.disponibilidad import Bloqueo
from app.models.entidades import Prestacion, Profesional, Usuario
from tests.conftest import (
    ID_PROFESIONAL_A,
    ID_SILLON_S1,
    TestSession,
)

pytestmark = pytest.mark.integration

LOGIN_URL = "/api/v1/auth/login"
PROFESIONALES_URL = "/api/v1/profesionales"
PRESTACIONES_URL = "/api/v1/prestaciones"
SILLONES_URL = "/api/v1/sillones"
BLOQUEOS_URL = "/api/v1/bloqueos"
AGENDA_URL = "/api/v1/agenda"

EMAIL_ADMIN = "admin.config.ficticio@consultorio.example"
EMAIL_RECEPCION = "recepcion.config.ficticia@consultorio.example"
EMAIL_ODONTOLOGO = "odontologo.config.ficticio@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Config-1234-no-real"


@pytest_asyncio.fixture()
async def usuarios_config() -> None:
    """Admin + recepción + odontólogo sintéticos; self-cleanup (R0)."""
    async with TestSession() as sesion:
        for email, rol in (
            (EMAIL_ADMIN, "admin"),
            (EMAIL_RECEPCION, "recepcion"),
            (EMAIL_ODONTOLOGO, "odontologo"),
        ):
            sesion.add(
                Usuario(
                    email=email,
                    password_hash=hashear_password(PASSWORD_FICTICIA),
                    rol=rol,
                    activo=True,
                )
            )
        await sesion.commit()
    yield
    async with TestSession() as sesion:
        await sesion.execute(
            delete(Usuario).where(
                Usuario.email.in_([EMAIL_ADMIN, EMAIL_RECEPCION, EMAIL_ODONTOLOGO])
            )
        )
        await sesion.commit()


async def _access(cliente: AsyncClient, email: str) -> str:
    login = await cliente.post(
        LOGIN_URL, json={"email": email, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


async def _accesos_denegados() -> list[AuditoriaLog]:
    async with TestSession() as sesion:
        return list(
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "acceso_denegado"
                    )
                )
            )
            .scalars()
            .all()
        )


async def test_recepcion_escribe_config_403_y_audita_sin_mutar(
    cliente: AsyncClient, usuarios_config: None
) -> None:
    # Arrange: access de recepción + conteo base de profesionales.
    access = await _access(cliente, EMAIL_RECEPCION)
    auth = {"Authorization": f"Bearer {access}"}
    async with TestSession() as sesion:
        total_antes = int(
            (
                await sesion.execute(
                    select(func.count()).select_from(Profesional)
                )
            ).scalar_one()
        )

    # Act: escritura de config con rol no-admin.
    respuesta = await cliente.post(
        PROFESIONALES_URL,
        json={"nombre": "Profesional Ficticio X", "matricula": "DEMO-MAT-X-999"},
        headers=auth,
    )

    # Assert: 403 genérico, nada creado, `acceso_denegado` auditado.
    assert respuesta.status_code == 403
    async with TestSession() as sesion:
        total_despues = int(
            (
                await sesion.execute(
                    select(func.count()).select_from(Profesional)
                )
            ).scalar_one()
        )
    assert total_despues == total_antes
    assert len(await _accesos_denegados()) == 1


async def test_admin_crea_prestacion_visible_para_recepcion(
    cliente: AsyncClient, usuarios_config: None
) -> None:
    # Arrange: access de admin y de recepción.
    access_admin = await _access(cliente, EMAIL_ADMIN)
    access_recepcion = await _access(cliente, EMAIL_RECEPCION)
    nombre = "Control sintético C-04"

    # Act: alta como admin + lectura como recepción.
    try:
        creada = await cliente.post(
            PRESTACIONES_URL,
            json={"nombre": nombre, "duracion_min": 30},
            headers={"Authorization": f"Bearer {access_admin}"},
        )
        assert creada.status_code == 201
        prestacion_id = creada.json()["id"]
        lectura = await cliente.get(
            PRESTACIONES_URL,
            headers={"Authorization": f"Bearer {access_recepcion}"},
        )

        # Assert: visible en lectura y alta auditada sin PII.
        assert lectura.status_code == 200
        assert nombre in [p["nombre"] for p in lectura.json()]
        async with TestSession() as sesion:
            filas = (
                (
                    await sesion.execute(
                        select(AuditoriaLog).where(
                            AuditoriaLog.entidad_id == prestacion_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(filas) == 1
    finally:
        async with TestSession() as sesion:
            await sesion.execute(
                delete(Prestacion).where(Prestacion.nombre == nombre)
            )
            await sesion.commit()


async def test_odontologo_lee_su_agenda_pero_no_configura(
    cliente: AsyncClient, usuarios_config: None
) -> None:
    # Arrange: access de odontólogo.
    access = await _access(cliente, EMAIL_ODONTOLOGO)
    auth = {"Authorization": f"Bearer {access}"}

    # Act: agenda propia (permitida) + DELETE de sillón (reservado a admin).
    propia = await cliente.get(
        AGENDA_URL,
        params={
            "vista": "dia",
            "profesional_id": str(ID_PROFESIONAL_A),
            "desde": "2026-11-03T00:00:00-03:00",
        },
        headers=auth,
    )
    borrado = await cliente.delete(
        f"{SILLONES_URL}/{ID_SILLON_S1}", headers=auth
    )

    # Assert: 200 en la propia, 403 + evento auditado en config.
    assert propia.status_code == 200
    assert borrado.status_code == 403
    assert len(await _accesos_denegados()) == 1


async def test_prestacion_duracion_invalida_422_sin_crear(
    cliente: AsyncClient, usuarios_config: None
) -> None:
    # Arrange: access de admin + conteo base de prestaciones.
    access = await _access(cliente, EMAIL_ADMIN)
    async with TestSession() as sesion:
        total_antes = int(
            (await sesion.execute(select(func.count()).select_from(Prestacion))).scalar_one()
        )

    # Act: prestación con `duracion_min = 0`.
    respuesta = await cliente.post(
        PRESTACIONES_URL,
        json={"nombre": "Prestación inválida ficticia", "duracion_min": 0},
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 422 y ninguna prestación nueva.
    assert respuesta.status_code == 422
    async with TestSession() as sesion:
        total_despues = int(
            (await sesion.execute(select(func.count()).select_from(Prestacion))).scalar_one()
        )
    assert total_despues == total_antes


async def test_bloqueo_ventana_invertida_422_sin_crear(
    cliente: AsyncClient, usuarios_config: None
) -> None:
    # Arrange: access de admin (la purga global limpia bloqueos, C-03).
    access = await _access(cliente, EMAIL_ADMIN)

    # Act: bloqueo con `desde >= hasta`.
    respuesta = await cliente.post(
        BLOQUEOS_URL,
        json={
            "profesional_id": str(ID_PROFESIONAL_A),
            "desde": "2026-11-04T10:00:00-03:00",
            "hasta": "2026-11-04T09:00:00-03:00",
            "motivo": "Ventana invertida ficticia",
        },
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 422 y ningún bloqueo creado (la purga global vacía la tabla).
    assert respuesta.status_code == 422
    async with TestSession() as sesion:
        total = int(
            (await sesion.execute(select(func.count()).select_from(Bloqueo))).scalar_one()
        )
    assert total == 0
