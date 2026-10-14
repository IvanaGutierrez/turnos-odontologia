"""Presupuesto con firma C-07 (task 1.4, RED — RN-CL-03 + máquina de estados).

Spec `clinica/ficha-odontograma-presupuesto`: el presupuesto nace de
hallazgos con total calculado; `borrador→aprobado` exige `firma_paciente`
(`422` si falta); plan con `sena_requerida > 0` sin firma → `422`;
`borrador→pagado` directo y salidas desde `rechazado` → `422`.

Contratos asumidos para GREEN (parte 2 los implementa):
- `POST /api/v1/presupuestos` acepta `{ficha_id, desde_hallazgos:
  [{pieza_fdi, estado_codigo, cantidad, precio_unitario}]}` (el precio viaja
  en el hallazgo porque `prestacion` aún no tiene `precio_base`).
  Responde `201` `{id, estado: "borrador", total}`.
- `POST /api/v1/presupuestos/:id/firma` registra firma+fecha del paciente.
- `POST …/aprobar` y `POST …/rechazar {motivo}` transicionan; `POST …/transicion
  {estado_destino}` es la vía genérica (rechaza lo inválido con `422`).
- `GET /api/v1/presupuestos/:id` expone `{estado}` para verificar guards.
- `POST /api/v1/planes` acepta `{presupuesto_id, etapas, sena_requerida}`.
Montos ficticios en ARS (R0).
"""

import pytest
from httpx import AsyncClient

from tests.conftest import (
    DNI_HC_CON_CONSENTIMIENTO,
    EMAIL_ODONTOLOGO_HC,
    FICHAS_URL,
    PLANES_URL,
    PRESUPUESTOS_URL,
    crear_paciente_hc,
    jwt_para,
)

pytestmark = pytest.mark.integration

HALLAZGOS_FICTICIOS = [
    {"pieza_fdi": 16, "estado_codigo": "cariado", "cantidad": 1, "precio_unitario": "15000.00"},
    {"pieza_fdi": 36, "estado_codigo": "obturado", "cantidad": 2, "precio_unitario": "8000.00"},
]
TOTAL_ESPERADO = "31000.00"


async def _presupuesto_para(
    cliente: AsyncClient, headers: dict[str, str]
) -> str:
    """Arrange: ficha + presupuesto en borrador. Falla en RED."""
    paciente_id = await crear_paciente_hc(
        nombre="Paciente Presupuesto Ficticia",
        dni=DNI_HC_CON_CONSENTIMIENTO,
        consentimiento=True,
    )
    ficha = await cliente.post(
        FICHAS_URL, json={"paciente_id": str(paciente_id)}, headers=headers
    )
    assert ficha.status_code == 201
    creado = await cliente.post(
        PRESUPUESTOS_URL,
        json={"ficha_id": ficha.json()["id"], "desde_hallazgos": HALLAZGOS_FICTICIOS},
        headers=headers,
    )
    assert creado.status_code == 201
    return str(creado.json()["id"])


async def _estado_de(
    cliente: AsyncClient, headers: dict[str, str], presupuesto_id: str
) -> str:
    respuesta = await cliente.get(
        f"{PRESUPUESTOS_URL}/{presupuesto_id}", headers=headers
    )
    assert respuesta.status_code == 200
    return str(respuesta.json()["estado"])


async def test_presupuesto_desde_hallazgos_201_borrador_con_total(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: ficha del tratante.
    headers = {"Authorization": f"Bearer {await jwt_para(cliente, EMAIL_ODONTOLOGO_HC)}"}
    paciente_id = await crear_paciente_hc(
        nombre="Paciente Hallazgos Ficticia",
        dni=DNI_HC_CON_CONSENTIMIENTO,
        consentimiento=True,
    )
    ficha = await cliente.post(
        FICHAS_URL, json={"paciente_id": str(paciente_id)}, headers=headers
    )
    assert ficha.status_code == 201

    # Act: presupuesto nacido de hallazgos del odontograma.
    respuesta = await cliente.post(
        PRESUPUESTOS_URL,
        json={"ficha_id": ficha.json()["id"], "desde_hallazgos": HALLAZGOS_FICTICIOS},
        headers=headers,
    )

    # Assert: 201 en borrador con items por pieza y total calculado en servicio.
    assert respuesta.status_code == 201
    datos = respuesta.json()
    assert datos["estado"] == "borrador"
    assert str(datos["total"]) == TOTAL_ESPERADO
    assert len(datos["items"]) == 2


async def test_aprobar_sin_firma_422_sigue_borrador(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: presupuesto en borrador sin firma.
    headers = {"Authorization": f"Bearer {await jwt_para(cliente, EMAIL_ODONTOLOGO_HC)}"}
    presupuesto_id = await _presupuesto_para(cliente, headers)

    # Act: intento de aprobar sin `firma_paciente`.
    respuesta = await cliente.post(
        f"{PRESUPUESTOS_URL}/{presupuesto_id}/aprobar", headers=headers
    )

    # Assert: 422 con la política RN-CL-03 y el estado no se mueve.
    assert respuesta.status_code == 422
    assert await _estado_de(cliente, headers, presupuesto_id) == "borrador"


async def test_firma_y_aprobacion_200_aprobado(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: presupuesto en borrador.
    headers = {"Authorization": f"Bearer {await jwt_para(cliente, EMAIL_ODONTOLOGO_HC)}"}
    presupuesto_id = await _presupuesto_para(cliente, headers)

    # Act: firma del paciente (registro firma+fecha) y luego aprobación.
    firma = await cliente.post(
        f"{PRESUPUESTOS_URL}/{presupuesto_id}/firma",
        json={"firma": "firma-ficticia-paciente-hc", "fecha": "2026-11-03"},
        headers=headers,
    )
    aprobacion = await cliente.post(
        f"{PRESUPUESTOS_URL}/{presupuesto_id}/aprobar", headers=headers
    )

    # Assert: firma 200 + estado aprobado.
    assert firma.status_code == 200
    assert aprobacion.status_code == 200
    assert await _estado_de(cliente, headers, presupuesto_id) == "aprobado"


async def test_plan_con_sena_sin_firma_422(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: presupuesto en borrador sin firma.
    headers = {"Authorization": f"Bearer {await jwt_para(cliente, EMAIL_ODONTOLOGO_HC)}"}
    presupuesto_id = await _presupuesto_para(cliente, headers)
    plan = {"presupuesto_id": presupuesto_id, "etapas": [{"nombre": "Etapa ficticia 1"}], "sena_requerida": "5000.00"}

    # Act: plan con seña sin firma → 422; con firma → 201.
    sin_firma = await cliente.post(PLANES_URL, json=plan, headers=headers)
    await cliente.post(
        f"{PRESUPUESTOS_URL}/{presupuesto_id}/firma",
        json={"firma": "firma-ficticia-paciente-hc", "fecha": "2026-11-03"},
        headers=headers,
    )
    con_firma = await cliente.post(PLANES_URL, json=plan, headers=headers)

    # Assert: la seña exige firma previa (RN-CL-03 + RN-PA-01).
    assert sin_firma.status_code == 422
    assert con_firma.status_code == 201


async def test_transiciones_invalidas_422(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: presupuesto en borrador.
    headers = {"Authorization": f"Bearer {await jwt_para(cliente, EMAIL_ODONTOLOGO_HC)}"}
    presupuesto_id = await _presupuesto_para(cliente, headers)

    # Act: `borrador→pagado` directo (solo vía C-08) y salidas desde `rechazado`.
    directa = await cliente.post(
        f"{PRESUPUESTOS_URL}/{presupuesto_id}/transicion",
        json={"estado_destino": "pagado"},
        headers=headers,
    )
    rechazo = await cliente.post(
        f"{PRESUPUESTOS_URL}/{presupuesto_id}/rechazar",
        json={"motivo": "Motivo ficticio de rechazo"},
        headers=headers,
    )
    desde_rechazado = await cliente.post(
        f"{PRESUPUESTOS_URL}/{presupuesto_id}/aprobar", headers=headers
    )

    # Assert: 422 en ambas inválidas; el rechazo terminal no se mueve.
    assert directa.status_code == 422
    assert rechazo.status_code == 200
    assert desde_rechazado.status_code == 422
    assert await _estado_de(cliente, headers, presupuesto_id) == "rechazado"
