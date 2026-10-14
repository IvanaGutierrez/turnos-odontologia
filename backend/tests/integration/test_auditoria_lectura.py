"""C-11 tasks 1.2 RED: lectura de bitacora solo admin (R5).

Contrato que la parte 2 (GREEN) debe cumplir:
- `GET /api/v1/auditoria?entidad&entidad_id&accion&desde&hasta&page&page_size`
  solo admin -> 200 paginado ordenado por hora desc, con `diff` sanitizados.
- Recepcion/odontologo -> 403 generico + `acceso_denegado`.
- Los 5 eventos (turno_creado, turno_cancelado, pago_acreditado,
  cierre_creado, evolucion_registrada) aparecen filtrando por entidad/id.
- Ningun `diff` contiene DNI, telefonos, HCE, hashes ni tokens (R6).

Estado parte 1: el router NO existe -> todo falla 404 (rojo genuino).
Todo dato sintetico (R0); type hints siempre (R1).
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.auditoria import AuditoriaLog
from app.models.entidades import Usuario
from app.repositories import auditoria as repo_auditoria
from tests.conftest import TestSession, crear_usuario_ficticio, eliminar_usuario_ficticio

pytestmark = pytest.mark.integration

AUDITORIA_URL = "/api/v1/auditoria"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_ADMIN = "auditoria.c11.admin@consultorio.example"
EMAIL_RECEPCION = "auditoria.c11.recepcion@consultorio.example"
EMAIL_ODONTOLOGO = "auditoria.c11.odontologo@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-Aud-C11-0001-no-real"

CLAVES_PROHIBIDAS = (
    "password_hash",
    "dni",
    "telefono",
    "anamnesis",
    "historia_clinica",
    "hc",
    "token",
    "refresh_token",
    "access_token",
    "hash",
)

# 5 eventos C-11 (entidad, entidad_id ficticio, accion).
EVENTOS_CINCO: tuple[tuple[str, str, str], ...] = (
    ("turno", "turno-ficticio-c11-0001", "turno_creado"),
    ("turno", "turno-ficticio-c11-0002", "turno_cancelado"),
    ("pago", "pago-ficticio-c11-0003", "pago_acreditado"),
    ("cierre", "cierre-ficticio-c11-0004", "cierre_creado"),
    ("evolucion", "evolucion-ficticia-c11-0005", "evolucion_registrada"),
)


@pytest_asyncio.fixture()
async def bitacora_c11() -> AsyncGenerator[None, None]:
    """Admin + recepcion + odontologo + 5 eventos sinteticos; self-cleanup."""
    await crear_usuario_ficticio(EMAIL_ADMIN, PASSWORD_FICTICIA, "admin")
    await crear_usuario_ficticio(EMAIL_RECEPCION, PASSWORD_FICTICIA, "recepcion")
    await crear_usuario_ficticio(EMAIL_ODONTOLOGO, PASSWORD_FICTICIA, "odontologo")
    async with TestSession() as sesion:
        admin = (
            await sesion.execute(select(Usuario).where(Usuario.email == EMAIL_ADMIN))
        ).scalar_one()
        for entidad, entidad_id, accion in EVENTOS_CINCO:
            await repo_auditoria.registrar_auditoria(
                sesion,
                accion=accion,
                entidad=entidad,
                entidad_id=entidad_id,
                diff={"entidad_id": entidad_id, "origen": "ficticio-c11"},
                usuario_id=admin.id,
                ip="127.0.0.1",
            )
        await sesion.commit()
    yield
    async with TestSession() as sesion:
        await sesion.execute(
            delete(AuditoriaLog).where(
                AuditoriaLog.entidad.in_(["turno", "pago", "cierre", "evolucion"])
            )
        )
        admin = (
            await sesion.execute(select(Usuario).where(Usuario.email == EMAIL_ADMIN))
        ).scalar_one_or_none()
        if admin is not None:
            await sesion.execute(
                delete(AuditoriaLog).where(AuditoriaLog.usuario_id == admin.id)
            )
        await sesion.commit()
    for email in (EMAIL_ADMIN, EMAIL_RECEPCION, EMAIL_ODONTOLOGO):
        await eliminar_usuario_ficticio(email)


async def _access_para(cliente: AsyncClient, email: str) -> str:
    # Arrange: login del rol pedido.
    login = await cliente.post(
        LOGIN_URL, json={"email": email, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


def _sin_pii(plano: str) -> bool:
    bajo = plano.lower()
    return all(clave not in bajo for clave in CLAVES_PROHIBIDAS)


async def test_admin_filtra_por_entidad_e_id_200_solo_esas(
    cliente: AsyncClient, bitacora_c11: None
) -> None:
    # Arrange: JWT admin.
    access = await _access_para(cliente, EMAIL_ADMIN)
    cabeceras = {"Authorization": f"Bearer {access}"}
    # Act: filtra pago por entidad + id.
    respuesta = await cliente.get(
        AUDITORIA_URL,
        params={"entidad": "pago", "entidad_id": "pago-ficticio-c11-0003"},
        headers=cabeceras,
    )
    # Assert: 200 solo con las filas de ese pago, sin PII.
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    items = cuerpo["items"] if isinstance(cuerpo, dict) else cuerpo
    assert len(items) >= 1
    for fila in items:
        assert fila["entidad"] == "pago"
        assert fila["entidad_id"] == "pago-ficticio-c11-0003"
    assert _sin_pii(respuesta.text)


async def test_cinco_eventos_quedan_registrados_y_consultables(
    cliente: AsyncClient, bitacora_c11: None
) -> None:
    # Arrange: JWT admin.
    access = await _access_para(cliente, EMAIL_ADMIN)
    cabeceras = {"Authorization": f"Bearer {access}"}
    # Act + Assert: cada filtro devuelve su evento con usuario y hora, sin PII/HC.
    for entidad, entidad_id, accion in EVENTOS_CINCO:
        respuesta = await cliente.get(
            AUDITORIA_URL,
            params={"entidad": entidad, "entidad_id": entidad_id},
            headers=cabeceras,
        )
        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        items = cuerpo["items"] if isinstance(cuerpo, dict) else cuerpo
        acciones = [fila["accion"] for fila in items]
        assert accion in acciones
        fila = next(f for f in items if f["accion"] == accion)
        assert fila["usuario_id"] is not None or "usuario" in fila
        assert "hora" in fila or "creado_en" in fila
        assert _sin_pii(respuesta.text)


async def test_recepcion_consulta_auditoria_403_mas_log(
    cliente: AsyncClient, bitacora_c11: None
) -> None:
    # Arrange: JWT recepcion.
    access = await _access_para(cliente, EMAIL_RECEPCION)
    # Act: misma consulta que el admin.
    respuesta = await cliente.get(
        AUDITORIA_URL,
        params={"entidad": "pago", "entidad_id": "pago-ficticio-c11-0003"},
        headers={"Authorization": f"Bearer {access}"},
    )
    # Assert: 403 generico + acceso_denegado.
    assert respuesta.status_code == 403
    async with TestSession() as sesion:
        filas = (
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
    assert len(filas) >= 1


async def test_odontologo_consulta_auditoria_403(
    cliente: AsyncClient, bitacora_c11: None
) -> None:
    # Arrange: JWT odontologo.
    access = await _access_para(cliente, EMAIL_ODONTOLOGO)
    # Act: intenta leer bitacora.
    respuesta = await cliente.get(
        AUDITORIA_URL,
        params={"entidad": "turno", "entidad_id": "turno-ficticio-c11-0001"},
        headers={"Authorization": f"Bearer {access}"},
    )
    # Assert: 403 sin datos.
    assert respuesta.status_code == 403


async def test_filtros_y_paginacion_acotan_con_orden_desc(
    cliente: AsyncClient, bitacora_c11: None
) -> None:
    # Arrange: JWT admin + 25 eventos extra de cierre para paginar.
    access = await _access_para(cliente, EMAIL_ADMIN)
    cabeceras = {"Authorization": f"Bearer {access}"}
    async with TestSession() as sesion:
        admin = (
            await sesion.execute(select(Usuario).where(Usuario.email == EMAIL_ADMIN))
        ).scalar_one()
        for i in range(25):
            await repo_auditoria.registrar_auditoria(
                sesion,
                accion="cierre_creado",
                entidad="cierre",
                entidad_id=f"cierre-paginado-c11-{i:04d}",
                diff={"indice": i},
                usuario_id=admin.id,
                ip="127.0.0.1",
            )
        await sesion.commit()
    # Act: pagina 2 de 20 con filtro de accion.
    respuesta = await cliente.get(
        AUDITORIA_URL,
        params={"accion": "cierre_creado", "page": "2", "page_size": "20"},
        headers=cabeceras,
    )
    # Assert: 200 con pagina pedida, total y orden desc por hora, sin PII.
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["page"] == 2
    assert cuerpo["page_size"] == 20
    assert cuerpo["total"] >= 21
    horas = [fila.get("hora") or fila.get("creado_en") for fila in cuerpo["items"]]
    assert horas == sorted(horas, reverse=True)
    assert _sin_pii(respuesta.text)
