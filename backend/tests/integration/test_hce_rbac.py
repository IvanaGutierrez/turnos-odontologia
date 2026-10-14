"""RBAC clínico C-07 (task 1.2, RED — RN-CL-04).

Spec `clinica/ficha-odontograma-presupuesto`: recepción jamás escribe
clínica (`403` + `acceso_clinico_denegado` sin PII); recepción edita solo
contacto (`200`); odontólogo edita clínica (`200` + `ficha_editada` con
firmante y diff sin contenido); admin sin lectura clínica directa (`403`).

Contratos asumidos para GREEN (parte 2 los implementa):
- `PATCH /api/v1/fichas/:id` (clínica, solo odontólogo).
- `POST /api/v1/fichas/:id/odontograma` y `POST …/evoluciones` (clínica).
- `PATCH /api/v1/pacientes/:id` con `{telefono}` (contacto, recepción ok).
- `GET /api/v1/fichas/:id` denegado a `admin` (solo auditoría).
Datos 100 % sintéticos (R0); el texto clínico enviado es ficticio y jamás
debe aparecer en responses de error ni auditoría (R6).
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
    EMAIL_ADMIN_HC,
    EMAIL_ODONTOLOGO_HC,
    EMAIL_RECEPCION_HC,
    FICHAS_URL,
    TEL_HC_FICTICIO,
    TEL_HC_FICTICIO_NUEVO,
    TestSession,
    contar_filas_clinicas,
    crear_paciente_hc,
    jwt_para,
)

pytestmark = pytest.mark.integration

FICHA_INEXISTENTE = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
TEXTO_CLINICO_FICTICIO = "ANAMNESIS-FICTICIA-RED-sin-valor-clinico"


async def _id_usuario(email: str) -> uuid.UUID:
    async with TestSession() as sesion:
        return (
            (
                await sesion.execute(select(Usuario).where(Usuario.email == email))
            )
            .scalar_one()
            .id
        )


async def _auditoria(accion: str, entidad: str) -> list[AuditoriaLog]:
    async with TestSession() as sesion:
        return list(
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == accion,
                        AuditoriaLog.entidad == entidad,
                    )
                )
            )
            .scalars()
            .all()
        )


async def test_recepcion_patch_ficha_403_con_auditoria_sin_pii(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: JWT de recepción (rol sin alcance clínico).
    access = await jwt_para(cliente, EMAIL_RECEPCION_HC)

    # Act: escritura clínica con rol recepción.
    respuesta = await cliente.patch(
        f"{FICHAS_URL}/{FICHA_INEXISTENTE}",
        json={"anamnesis": TEXTO_CLINICO_FICTICIO},
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 403 genérico + denegación auditada sin PII ni contenido clínico.
    assert respuesta.status_code == 403
    assert TEXTO_CLINICO_FICTICIO not in respuesta.text
    filas = await _auditoria("acceso_clinico_denegado", "ficha")
    assert len(filas) == 1
    diff_txt = json.dumps(filas[0].diff, default=str)
    assert TEXTO_CLINICO_FICTICIO not in diff_txt
    assert TEL_HC_FICTICIO not in diff_txt
    assert await contar_filas_clinicas("ficha") == 0


async def test_recepcion_post_odontograma_y_evolucion_403(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: JWT de recepción.
    access = await jwt_para(cliente, EMAIL_RECEPCION_HC)
    headers = {"Authorization": f"Bearer {access}"}

    # Act: batch de odontograma + evolución con rol recepción.
    odonto = await cliente.post(
        f"{FICHAS_URL}/{FICHA_INEXISTENTE}/odontograma",
        json={"entries": [{"pieza_fdi": 11, "estado_codigo": "sano"}]},
        headers=headers,
    )
    evolucion = await cliente.post(
        f"{FICHAS_URL}/{FICHA_INEXISTENTE}/evoluciones",
        json={"texto": TEXTO_CLINICO_FICTICIO},
        headers=headers,
    )

    # Assert: ambas 403 y nada clínico persistido.
    assert [odonto.status_code, evolucion.status_code] == [403, 403]
    assert await contar_filas_clinicas("odontograma_entry") == 0
    assert await contar_filas_clinicas("evolucion") == 0


async def test_recepcion_patch_contacto_200_hce_intacta(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: paciente ficticio con consentimiento + JWT de recepción.
    paciente_id = await crear_paciente_hc(
        nombre="Paciente Contacto Ficticia",
        dni=DNI_HC_CON_CONSENTIMIENTO,
        consentimiento=True,
    )
    access = await jwt_para(cliente, EMAIL_RECEPCION_HC)

    # Act: edición de contacto por el canal de pacientes.
    respuesta = await cliente.patch(
        f"/api/v1/pacientes/{paciente_id}",
        json={"telefono": TEL_HC_FICTICIO_NUEVO},
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 200 con contacto actualizado y HCE/consentimiento intactos.
    assert respuesta.status_code == 200
    async with TestSession() as sesion:
        paciente = (
            await sesion.execute(
                select(Paciente).where(Paciente.id == paciente_id)
            )
        ).scalar_one()
    assert paciente.telefono == TEL_HC_FICTICIO_NUEVO
    assert paciente.consentimiento_hc is True
    assert await contar_filas_clinicas("ficha") == 0


async def test_odontologo_edita_ficha_200_con_firmante_y_auditoria(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: paciente con consentimiento + ficha creada por el odontólogo.
    paciente_id = await crear_paciente_hc(
        nombre="Paciente Edicion Ficticia",
        dni=DNI_HC_CON_CONSENTIMIENTO,
        consentimiento=True,
    )
    access = await jwt_para(cliente, EMAIL_ODONTOLOGO_HC)
    headers = {"Authorization": f"Bearer {access}"}
    creada = await cliente.post(
        FICHAS_URL, json={"paciente_id": str(paciente_id)}, headers=headers
    )
    assert creada.status_code == 201
    ficha_id = creada.json()["id"]
    odontologo_id = await _id_usuario(EMAIL_ODONTOLOGO_HC)

    # Act: el tratante edita la anamnesis (re-firma).
    respuesta = await cliente.patch(
        f"{FICHAS_URL}/{ficha_id}",
        json={"anamnesis": TEXTO_CLINICO_FICTICIO},
        headers=headers,
    )

    # Assert: 200 + firmante renovado + auditoría sin contenido clínico.
    assert respuesta.status_code == 200
    assert respuesta.json()["firmante_usuario_id"] == str(odontologo_id)
    filas = await _auditoria("ficha_editada", "ficha")
    assert len(filas) == 1
    diff_txt = json.dumps(filas[0].diff, default=str)
    assert TEXTO_CLINICO_FICTICIO not in diff_txt
    assert "anamnesis" not in diff_txt.lower()


async def test_admin_lectura_clinica_directa_403(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: JWT de admin (solo auditoría, jamás clínica directa).
    access = await jwt_para(cliente, EMAIL_ADMIN_HC)

    # Act: lectura directa de ficha con rol admin.
    respuesta = await cliente.get(
        f"{FICHAS_URL}/{FICHA_INEXISTENTE}",
        headers={"Authorization": f"Bearer {access}"},
    )

    # Assert: 403 (el admin clínico no existe; la auditoría la ve en C-11).
    assert respuesta.status_code == 403
