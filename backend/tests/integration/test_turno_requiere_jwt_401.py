"""Delta `agenda/crear-turno` (C-02 RED): `POST /turnos` exige JWT + audita.

Spec delta: salda el hook `get_current_user` (deuda C-01) — sin access
válido → 401 sin crear el turno; con access válido el shape 201/409/422
de C-01 no cambia; la creación queda auditada sin PII en el diff (R6).
Hoy el endpoint nace abierto: estos tests fallan en ROJO genuino.
Datos 100 % sintéticos (R0, vía `tests/conftest.py`).
"""

import pytest
from freezegun import freeze_time
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.security import hashear_password
from app.models.auditoria import AuditoriaLog
from app.models.entidades import Usuario
from tests.conftest import (
    DNI_FICTICIO,
    TEL_FICTICIO,
    TURNOS_URL,
    TestSession,
    inicio_demo,
    obtener_access,
    payload_turno,
)

pytestmark = pytest.mark.integration

# Access expirado sintético (firma/exp resueltos en GREEN, parte 2).
ACCESS_EXPIRADO_FICTICIO = "access-expirado-ficticio-no-real"

# GREEN (ajuste mínimo reportado): crear turno exige JWT, así que este test
# crea un usuario sintético y loguea antes de crear el turno.
EMAIL_TURNO_AUDITADO = "turno.auditado.ficticio@consultorio.example"
PASSWORD_FICTICIA_TURNO = "Ficticia-Turno-1234-no-real"


async def test_crear_turno_sin_token_401(cliente: AsyncClient) -> None:
    # Arrange: payload válido de turno (conftest sintético).
    payload = payload_turno(inicio_demo(14, 0))

    # Act: POST sin access token (el turno NO debe crearse).
    respuesta = await cliente.post(TURNOS_URL, json=payload)

    # Assert: 401 (hoy 201 porque el endpoint está abierto → ROJO).
    assert respuesta.status_code == 401


@freeze_time("2026-11-03 15:00:00")
async def test_crear_turno_access_expirado_401(cliente: AsyncClient) -> None:
    # Arrange: payload válido + access vencido (hora congelada).
    payload = payload_turno(inicio_demo(16, 0))

    # Act: POST con access expirado.
    respuesta = await cliente.post(
        TURNOS_URL,
        json=payload,
        headers={"Authorization": f"Bearer {ACCESS_EXPIRADO_FICTICIO}"},
    )

    # Assert: 401 sin crear el turno (hoy 201 → ROJO).
    assert respuesta.status_code == 401


async def test_crear_turno_auditado_sin_pii(cliente: AsyncClient) -> None:
    # Arrange: usuario sintético + login (GREEN exige JWT) y turno válido.
    async with TestSession() as sesion:
        sesion.add(
            Usuario(
                email=EMAIL_TURNO_AUDITADO,
                password_hash=hashear_password(PASSWORD_FICTICIA_TURNO),
                rol="recepcion",
                activo=True,
            )
        )
        await sesion.commit()
    try:
        access = await obtener_access(
            cliente, EMAIL_TURNO_AUDITADO, PASSWORD_FICTICIA_TURNO
        )
        payload = payload_turno(inicio_demo(17, 0))

        # Act: crear el turno autenticado.
        respuesta = await cliente.post(
            TURNOS_URL,
            json=payload,
            headers={"Authorization": f"Bearer {access}"},
        )

        # Assert: 201 + fila de auditoría cuyo diff no expone DNI/teléfono (R6).
        assert respuesta.status_code == 201
        turno_id = respuesta.json()["id"]
        async with TestSession() as sesion:
            filas = (
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
        assert len(filas) == 1
        plano = str(filas[0].diff)
        assert DNI_FICTICIO not in plano
        assert TEL_FICTICIO not in plano
    finally:
        async with TestSession() as sesion:
            await sesion.execute(
                delete(Usuario).where(Usuario.email == EMAIL_TURNO_AUDITADO)
            )
            await sesion.commit()
