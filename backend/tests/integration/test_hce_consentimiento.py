"""Gate de consentimiento HCE C-07 (task 1.1, RED — Ley 26.529, RN-CL-01).

Spec `clinica/ficha-odontograma-presupuesto`: crear HCE exige
`paciente.consentimiento_hc`; sin él → `422` sin crear nada; con él →
`201` + `firmante_usuario_id` (= odontólogo JWT) + `ficha_creada` sin
contenido clínico.

Contratos asumidos para GREEN (parte 2 los implementa):
- `POST /api/v1/fichas` acepta `{paciente_id, anamnesis?}`.
- `201` responde `{id, paciente_id, firmante_usuario_id, ...}`.
- `422` responde error de política genérico (sin PII, R6).
- Auditoría `ficha_creada` en `auditoria_log` (entidad `ficha`) con diff
  mínimo (solo IDs/rol/fecha, jamás anamnesis — R6).
Datos 100 % sintéticos (R0); jamás HC real.
"""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.auditoria import AuditoriaLog
from app.models.entidades import Paciente, Usuario
from tests.conftest import (
    DNI_HC_CON_CONSENTIMIENTO,
    DNI_HC_SIN_CONSENTIMIENTO,
    EMAIL_ODONTOLOGO_HC,
    FICHAS_URL,
    TEL_HC_FICTICIO,
    TestSession,
    contar_filas_clinicas,
    crear_paciente_hc,
    jwt_para,
)

pytestmark = pytest.mark.integration


async def _id_usuario(email: str) -> uuid.UUID:
    async with TestSession() as sesion:
        usuario = (
            await sesion.execute(select(Usuario).where(Usuario.email == email))
        ).scalar_one()
        return usuario.id


async def test_crear_ficha_sin_consentimiento_422_sin_filas_clinicas(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: paciente ficticio SIN consentimiento + JWT de odontólogo.
    paciente_id = await crear_paciente_hc(
        nombre="Paciente Sin Consentimiento Ficticia",
        dni=DNI_HC_SIN_CONSENTIMIENTO,
        consentimiento=False,
    )
    access = await jwt_para(cliente, EMAIL_ODONTOLOGO_HC)

    # Act: intento de crear HCE.
    respuesta = await cliente.post(
        FICHAS_URL,
        json={"paciente_id": str(paciente_id)},
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 422 de política, error genérico sin PII y cero filas clínicas.
    assert respuesta.status_code == 422
    cuerpo = respuesta.text
    assert DNI_HC_SIN_CONSENTIMIENTO not in cuerpo
    assert TEL_HC_FICTICIO not in cuerpo
    assert await contar_filas_clinicas("ficha") == 0
    assert await contar_filas_clinicas("odontograma_entry") == 0
    assert await contar_filas_clinicas("evolucion") == 0


async def test_crear_ficha_con_consentimiento_201_con_firmante_y_auditoria(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: paciente ficticio CON consentimiento + JWT de odontólogo.
    paciente_id = await crear_paciente_hc(
        nombre="Paciente Con Consentimiento Ficticia",
        dni=DNI_HC_CON_CONSENTIMIENTO,
        consentimiento=True,
    )
    access = await jwt_para(cliente, EMAIL_ODONTOLOGO_HC)
    odontologo_id = await _id_usuario(EMAIL_ODONTOLOGO_HC)

    # Act: creación de HCE.
    respuesta = await cliente.post(
        FICHAS_URL,
        json={"paciente_id": str(paciente_id)},
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 201 + firmante = odontólogo JWT + auditoría sin contenido clínico.
    assert respuesta.status_code == 201
    datos = respuesta.json()
    assert datos["firmante_usuario_id"] == str(odontologo_id)
    async with TestSession() as sesion:
        filas = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "ficha_creada",
                        AuditoriaLog.entidad == "ficha",
                    )
                )
            )
            .scalars()
            .all()
        )
        paciente = (
            await sesion.execute(
                select(Paciente).where(Paciente.id == paciente_id)
            )
        ).scalar_one()
    assert len(filas) == 1
    diff_txt = json.dumps(filas[0].diff, default=str)
    assert "anamnesis" not in diff_txt.lower()
    assert DNI_HC_CON_CONSENTIMIENTO not in diff_txt
    assert TEL_HC_FICTICIO not in diff_txt
    assert paciente.consentimiento_hc is True
