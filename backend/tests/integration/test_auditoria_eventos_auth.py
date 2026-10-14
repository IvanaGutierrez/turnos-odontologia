"""Auditoría obligatoria RN-AU-03 (C-02 RED): 4 filas + diff sin PII.

Spec `auditoria/registro-acciones`: login, refresh, logout y denegación
403 generan una fila cada uno en `auditoria_log` (accion, entidad,
entidad_id, diff jsonb, usuario, ip, hora); el `diff` jamás contiene DNI,
teléfonos, historia clínica, hashes ni tokens (R6). Datos sintéticos.
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.security import hashear_password
from app.models.auditoria import AuditoriaLog
from app.models.entidades import Usuario
from tests.conftest import TestSession

pytestmark = pytest.mark.integration

LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"
USUARIOS_URL = "/api/v1/usuarios"

EMAIL_AUDITORIA = "auditoria.ficticia@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Login-1234-no-real"

CLAVES_PROHIBIDAS = (
    "password_hash",
    "dni",
    "telefono",
    "anamnesis",
    "historia_clinica",
    "token",
    "refresh_token",
    "access_token",
)


@pytest_asyncio.fixture()
async def usuario_auditoria() -> AsyncGenerator[None, None]:
    """Usuario sintético + limpieza de sus filas de auditoría (self-cleanup)."""
    async with TestSession() as sesion:
        sesion.add(
            Usuario(
                email=EMAIL_AUDITORIA,
                password_hash=hashear_password(PASSWORD_FICTICIA),
                rol="recepcion",
                activo=True,
            )
        )
        await sesion.commit()
    yield
    async with TestSession() as sesion:
        usuario = (
            await sesion.execute(
                select(Usuario).where(Usuario.email == EMAIL_AUDITORIA)
            )
        ).scalar_one_or_none()
        if usuario is not None:
            await sesion.execute(
                delete(AuditoriaLog).where(AuditoriaLog.usuario_id == usuario.id)
            )
        await sesion.execute(delete(Usuario).where(Usuario.email == EMAIL_AUDITORIA))
        await sesion.commit()


async def test_login_logout_refresh_denegacion_generan_4_filas(
    cliente: AsyncClient, usuario_auditoria: None
) -> None:
    # Arrange: usuario sintético (fixture).
    # Act: login → refresh → logout → denegación 403 (contrato RED).
    r_login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_AUDITORIA, "password": PASSWORD_FICTICIA}
    )
    access = r_login.json()["access_token"] if r_login.status_code == 200 else ""
    refresco = r_login.cookies.get("refresh_token")
    r_refresh = await cliente.post(
        REFRESH_URL, headers={"Cookie": f"refresh_token={refresco or ''}"}
    )
    r_logout = await cliente.post(
        LOGOUT_URL, headers={"Cookie": f"refresh_token={refresco or ''}"}
    )
    r_denegada = await cliente.get(
        USUARIOS_URL, headers={"Authorization": f"Bearer {access}"}
    )

    # Assert: contrato por acción + 4 filas en `auditoria_log`.
    assert [r_login.status_code, r_refresh.status_code] == [200, 200]
    assert r_logout.status_code in (200, 204)
    assert r_denegada.status_code == 403
    async with TestSession() as sesion:
        usuario = (
            await sesion.execute(
                select(Usuario).where(Usuario.email == EMAIL_AUDITORIA)
            )
        ).scalar_one()
        propias = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(AuditoriaLog.usuario_id == usuario.id)
                )
            )
            .scalars()
            .all()
        )
    # 4 eventos del usuario (login, refresh, logout, denegación) — filtro por
    # usuario para no depender del orden de ejecución (spec: "la acción, el
    # usuario y la hora correspondientes"; `_aislar` además purga entre tests).
    assert len(propias) == 4


async def test_diff_auditoria_sin_hashes_tokens_pii(
    cliente: AsyncClient, usuario_auditoria: None
) -> None:
    # Arrange: login sintético (genera evento auditado en GREEN).
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_AUDITORIA, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200

    # Act: leer las filas de auditoría del usuario.
    async with TestSession() as sesion:
        usuario = (
            await sesion.execute(
                select(Usuario).where(Usuario.email == EMAIL_AUDITORIA)
            )
        ).scalar_one()
        filas = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(AuditoriaLog.usuario_id == usuario.id)
                )
            )
            .scalars()
            .all()
        )

    # Assert: hay filas y ningún diff expone secretos ni PII (R6).
    assert len(filas) >= 1
    for fila in filas:
        plano = str(fila.diff).lower()
        for prohibida in CLAVES_PROHIBIDAS:
            assert prohibida not in plano
