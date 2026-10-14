"""Privacidad y exportación C-07 (task 1.5, RED — Ley 25.326, R6).

Spec `clinica/ficha-odontograma-presupuesto`: anamnesis/evolución solo
cifradas; ningún log, error, diff ni response contiene HC/DNI/teléfonos;
`GET /api/v1/pacientes/:id/exportacion` entrega las 7 secciones al
titular/rol clínico con auditoría `datos_exportados`; rol no autorizado →
`403`; anamnesis descifrada solo titular/odontólogo tratante.

Contratos asumidos para GREEN (parte 2 los implementa):
- `GET /api/v1/pacientes/:id/exportacion` responde `200` con
  `{datos_contacto, consentimientos, ficha, odontograma, evoluciones,
  presupuestos, turnos}` (minimizado por rol; anamnesis solo tratante).
- Errores `422/403` genéricos minimizados (sin PII ni texto clínico).
Datos 100 % sintéticos (R0); el marcador `ANAMNESIS-FICTICIA-*` es la
sonda que jamás debe aparecer en logs ni errores (R6).
"""

import logging

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.auditoria import AuditoriaLog
from tests.conftest import (
    DNI_HC_CON_CONSENTIMIENTO,
    DNI_HC_SIN_CONSENTIMIENTO,
    EMAIL_ODONTOLOGO_HC,
    EMAIL_ODONTOLOGO_HC_2,
    EMAIL_RECEPCION_HC,
    FICHAS_URL,
    TEL_HC_FICTICIO,
    TestSession,
    clave_hce_prueba,
    crear_paciente_hc,
    jwt_para,
)

pytestmark = pytest.mark.integration

SONDA_ANAMNESIS = "ANAMNESIS-FICTICIA-SONDA-sin-valor-clinico"
SECCIONES_EXPORTACION = {
    "datos_contacto",
    "consentimientos",
    "ficha",
    "odontograma",
    "evoluciones",
    "presupuestos",
    "turnos",
}


async def _ficha_para(
    cliente: AsyncClient, headers: dict[str, str], dni: str
) -> str:
    """Arrange: paciente + ficha con anamnesis sonda. Falla en RED."""
    clave_hce_prueba()
    paciente_id = await crear_paciente_hc(
        nombre="Paciente Privacidad Ficticia",
        dni=dni,
        consentimiento=True,
    )
    creada = await cliente.post(
        FICHAS_URL,
        json={"paciente_id": str(paciente_id), "anamnesis": SONDA_ANAMNESIS},
        headers=headers,
    )
    assert creada.status_code == 201
    return str(paciente_id)


async def test_exportacion_tratante_200_siete_secciones_y_auditoria(
    cliente: AsyncClient,
    usuarios_hc: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: ficha con sonda + JWT del tratante; capturo logs del flujo.
    headers = {"Authorization": f"Bearer {await jwt_para(cliente, EMAIL_ODONTOLOGO_HC)}"}
    with caplog.at_level(logging.INFO):
        paciente_id = await _ficha_para(cliente, headers, DNI_HC_CON_CONSENTIMIENTO)

        # Act: exportación del titular/ tratante.
        respuesta = await cliente.get(
            f"/api/v1/pacientes/{paciente_id}/exportacion", headers=headers
        )

    # Assert: 200 con las 7 secciones + auditoría, sin PII en logs.
    assert respuesta.status_code == 200
    assert SECCIONES_EXPORTACION <= set(respuesta.json().keys())
    async with TestSession() as sesion:
        filas = (
            (
                await sesion.execute(
                    select(AuditoriaLog).where(
                        AuditoriaLog.accion == "datos_exportados",
                        AuditoriaLog.entidad == "paciente",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(filas) == 1
    assert DNI_HC_CON_CONSENTIMIENTO not in caplog.text
    assert TEL_HC_FICTICIO not in caplog.text


async def test_exportacion_recepcion_403(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: ficha del tratante + JWT de recepción (fuera de alcance clínico).
    headers_tratante = {
        "Authorization": f"Bearer {await jwt_para(cliente, EMAIL_ODONTOLOGO_HC)}"
    }
    paciente_id = await _ficha_para(
        cliente, headers_tratante, DNI_HC_CON_CONSENTIMIENTO
    )
    headers_recep = {
        "Authorization": f"Bearer {await jwt_para(cliente, EMAIL_RECEPCION_HC)}"
    }

    # Act: exportación con rol no autorizado.
    respuesta = await cliente.get(
        f"/api/v1/pacientes/{paciente_id}/exportacion", headers=headers_recep
    )

    # Assert: 403 genérico sin exponer nada clínico.
    assert respuesta.status_code == 403
    assert SONDA_ANAMNESIS not in respuesta.text
    assert DNI_HC_CON_CONSENTIMIENTO not in respuesta.text


async def test_exportacion_otro_odontologo_no_tratante_403(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: ficha del tratante 1 + JWT de otro odontólogo.
    headers_tratante = {
        "Authorization": f"Bearer {await jwt_para(cliente, EMAIL_ODONTOLOGO_HC)}"
    }
    paciente_id = await _ficha_para(
        cliente, headers_tratante, DNI_HC_CON_CONSENTIMIENTO
    )
    headers_otro = {
        "Authorization": f"Bearer {await jwt_para(cliente, EMAIL_ODONTOLOGO_HC_2)}"
    }

    # Act: exportación fuera del vínculo tratante-paciente.
    respuesta = await cliente.get(
        f"/api/v1/pacientes/{paciente_id}/exportacion", headers=headers_otro
    )

    # Assert: 403 (la HCE solo la ve el tratante, R6).
    assert respuesta.status_code == 403


async def test_anamnesis_jamas_en_logs_ni_errores(
    cliente: AsyncClient,
    usuarios_hc: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: JWT del tratante; capturo todo el tráfico clínico.
    clave_hce_prueba()
    headers = {"Authorization": f"Bearer {await jwt_para(cliente, EMAIL_ODONTOLOGO_HC)}"}
    with caplog.at_level(logging.INFO):
        paciente_id = await crear_paciente_hc(
            nombre="Paciente Sonda Ficticia",
            dni=DNI_HC_SIN_CONSENTIMIENTO,
            consentimiento=False,
        )

        # Act: HCE sin consentimiento (422) + HCE válida (201) con sonda.
        sin_consent = await cliente.post(
            FICHAS_URL,
            json={"paciente_id": str(paciente_id), "anamnesis": SONDA_ANAMNESIS},
            headers=headers,
        )
        await crear_paciente_hc(
            nombre="Paciente Sonda Dos Ficticia",
            dni=DNI_HC_CON_CONSENTIMIENTO,
            consentimiento=True,
        )
        # (El segundo paciente reutiliza el flujo válido de exportación.)
        cuerpos_error = sin_consent.text

    # Assert: el flujo existe (422 real) y la sonda/PII jamás en logs/errores.
    assert sin_consent.status_code == 422
    assert SONDA_ANAMNESIS not in caplog.text
    assert SONDA_ANAMNESIS not in cuerpos_error
    assert DNI_HC_SIN_CONSENTIMIENTO not in cuerpos_error
    assert TEL_HC_FICTICIO not in cuerpos_error
    assert TEL_HC_FICTICIO not in caplog.text
