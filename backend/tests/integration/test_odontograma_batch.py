"""Odontograma batch C-07 (task 1.3, RED — RN-CL-02, FDI 11–48).

Spec `clinica/ficha-odontograma-presupuesto`: `POST …/odontograma` con
batch `[{pieza_fdi, estado_codigo, cara?}]` en upsert por
`(ficha_id, pieza_fdi, cara)`; pieza fuera de FDI real → `422` atómico;
`estado_codigo` fuera del catálogo vigente → `422`; `cara` inválida →
`422`; cada entry versionada (`estado_codigo + catalogo_version`).

Contratos asumidos para GREEN (parte 2 los implementa):
- `POST /api/v1/fichas/:id/odontograma` acepta `{entries: [...]}`.
- Batch válido → `200/201` con `{entries: [{pieza_fdi, estado_codigo,
  catalogo_version, cara}]}` + auditoría `odontograma_actualizado`.
- Cualquier entry inválida aborta todo el batch (atomicidad, R5).
- El catálogo vive en `catalogo_odontograma_estado` (migración 008, seed
  v1 de ~18 estados); v2 agrega filas sin reescribir v1.
Datos 100 % sintéticos (R0).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import (
    DNI_HC_CON_CONSENTIMIENTO,
    EMAIL_ODONTOLOGO_HC,
    FICHAS_URL,
    TestSession,
    contar_filas_clinicas,
    crear_paciente_hc,
    jwt_para,
)

pytestmark = pytest.mark.integration


async def _ficha_para(
    cliente: AsyncClient, headers: dict[str, str]
) -> str:
    """Arrange: paciente con consentimiento + ficha creada. Falla en RED."""
    paciente_id = await crear_paciente_hc(
        nombre="Paciente Odontograma Ficticia",
        dni=DNI_HC_CON_CONSENTIMIENTO,
        consentimiento=True,
    )
    creada = await cliente.post(
        FICHAS_URL, json={"paciente_id": str(paciente_id)}, headers=headers
    )
    assert creada.status_code == 201
    return str(creada.json()["id"])


async def test_batch_valido_multi_pieza_upsert_y_auditoria(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: ficha del tratante.
    headers = {"Authorization": f"Bearer {await jwt_para(cliente, EMAIL_ODONTOLOGO_HC)}"}
    ficha_id = await _ficha_para(cliente, headers)

    # Act: batch válido en piezas 11/16/36 con estados del catálogo v1.
    respuesta = await cliente.post(
        f"{FICHAS_URL}/{ficha_id}/odontograma",
        json={
            "entries": [
                {"pieza_fdi": 11, "estado_codigo": "sano"},
                {"pieza_fdi": 16, "estado_codigo": "cariado"},
                {"pieza_fdi": 36, "estado_codigo": "obturado", "cara": "oclusal"},
            ]
        },
        headers=headers,
    )

    # Assert: entries creadas + upsert por pieza + auditoría con códigos.
    assert respuesta.status_code in (200, 201)
    entries = respuesta.json()["entries"]
    assert {(e["pieza_fdi"], e["estado_codigo"]) for e in entries} == {
        (11, "sano"),
        (16, "cariado"),
        (36, "obturado"),
    }
    assert all(e["catalogo_version"] == 1 for e in entries)
    assert await contar_filas_clinicas("odontograma_entry") == 3


@pytest.mark.parametrize("pieza_invalida", [19, 49, 0])
async def test_pieza_fuera_fdi_422_atomico_sin_persistir(
    cliente: AsyncClient, usuarios_hc: None, pieza_invalida: int
) -> None:
    # Arrange: ficha del tratante.
    headers = {"Authorization": f"Bearer {await jwt_para(cliente, EMAIL_ODONTOLOGO_HC)}"}
    ficha_id = await _ficha_para(cliente, headers)

    # Act: batch mixto (una pieza válida + una fuera de FDI real).
    respuesta = await cliente.post(
        f"{FICHAS_URL}/{ficha_id}/odontograma",
        json={
            "entries": [
                {"pieza_fdi": 11, "estado_codigo": "sano"},
                {"pieza_fdi": pieza_invalida, "estado_codigo": "cariado"},
            ]
        },
        headers=headers,
    )

    # Assert: 422 y atomicidad (ni siquiera la pieza válida persiste).
    assert respuesta.status_code == 422
    assert await contar_filas_clinicas("odontograma_entry") == 0


async def test_estado_fuera_de_catalogo_422_sin_persistir(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: ficha del tratante.
    headers = {"Authorization": f"Bearer {await jwt_para(cliente, EMAIL_ODONTOLOGO_HC)}"}
    ficha_id = await _ficha_para(cliente, headers)

    # Act: batch con `estado_codigo` inexistente en el catálogo vigente.
    respuesta = await cliente.post(
        f"{FICHAS_URL}/{ficha_id}/odontograma",
        json={
            "entries": [
                {"pieza_fdi": 11, "estado_codigo": "sano"},
                {"pieza_fdi": 16, "estado_codigo": "estado_inexistente_ficticio"},
            ]
        },
        headers=headers,
    )

    # Assert: 422 sin persistir nada (el error solo cita códigos, R6).
    assert respuesta.status_code == 422
    assert await contar_filas_clinicas("odontograma_entry") == 0


async def test_cara_invalida_422_y_catalogo_v2_preserva_v1(
    cliente: AsyncClient, usuarios_hc: None
) -> None:
    # Arrange: ficha del tratante + catálogo v2 simulado (agrega, no edita v1).
    headers = {"Authorization": f"Bearer {await jwt_para(cliente, EMAIL_ODONTOLOGO_HC)}"}
    ficha_id = await _ficha_para(cliente, headers)
    async with TestSession() as sesion:
        await sesion.execute(
            text(
                "INSERT INTO catalogo_odontograma_estado "
                "(version, codigo, descripcion, activo) VALUES "
                "(2, 'sano', 'Pieza sana (v2)', true), "
                "(2, 'laser_ficticio', 'Estado nuevo v2 ficticio', true)"
            )
        )
        await sesion.commit()

    # Act: cara inválida → 422; luego batch v1 válido tras la llegada de v2.
    cara_mala = await cliente.post(
        f"{FICHAS_URL}/{ficha_id}/odontograma",
        json={"entries": [{"pieza_fdi": 11, "estado_codigo": "sano", "cara": "incisal"}]},
        headers=headers,
    )
    batch_v1 = await cliente.post(
        f"{FICHAS_URL}/{ficha_id}/odontograma",
        json={"entries": [{"pieza_fdi": 11, "estado_codigo": "sano"}]},
        headers=headers,
    )

    # Assert: cara inválida 422 + entries v1 conservan su versión.
    assert cara_mala.status_code == 422
    assert batch_v1.status_code in (200, 201)
    async with TestSession() as sesion:
        versiones = (
            await sesion.execute(
                text(
                    "SELECT DISTINCT catalogo_version FROM odontograma_entry "
                    "WHERE ficha_id = :ficha"
                ),
                {"ficha": ficha_id},
            )
        ).all()
    assert [v[0] for v in versiones] == [1]
