"""C-11 tasks 1.1 RED: CRUD usuarios solo admin con baja logica (R5).

Contrato que la parte 2 (GREEN) debe cumplir:
- `GET /api/v1/usuarios?page&page_size` solo admin -> 200
  `{items: [{id, email, rol, activo}], total, page, page_size}` sin `password_hash`.
- `POST /api/v1/usuarios {email, rol, password}` solo admin -> 201
  `{id, email, rol, activo}` sin hash + evento `usuario_creado`.
- `GET /api/v1/usuarios/:id` solo admin -> 200 sin hash.
- `PATCH /api/v1/usuarios/:id {rol, activo}` solo admin -> 200 + `rol_cambiado`;
  autodegradacion del propio admin -> 422.
- `DELETE /api/v1/usuarios/:id` solo admin -> 200 `{activo: false}` (baja logica,
  nunca borrado fisico); login posterior -> 401 + `usuario_desactivado`.
- No-admin en cualquier verbo -> 403 generico + `acceso_denegado`, sin crear nada.
- Email duplicado -> 409; rol invalido -> 422; sin efectos.

Estado parte 1: solo existe el probe `GET /usuarios` (lista plana C-02);
todo lo demas responde 404/405 -> ROJO genuino.
Todo dato sintetico (R0); type hints siempre (R1).
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.auditoria import AuditoriaLog
from app.models.entidades import Usuario
from tests.conftest import TestSession, crear_usuario_ficticio, eliminar_usuario_ficticio

pytestmark = pytest.mark.integration

USUARIOS_URL = "/api/v1/usuarios"
LOGIN_URL = "/api/v1/auth/login"

EMAIL_ADMIN = "admin.c11.ficticio@consultorio.example"
EMAIL_RECEPCION = "recepcion.c11.ficticia@consultorio.example"
EMAIL_ODONTOLOGO = "odontologo.c11.ficticio@consultorio.example"
PASSWORD_FICTICIA = "Ficticia-C11-1234-no-real"

EMAIL_NUEVO = "nuevo.c11.ficticio@consultorio.example"
PASSWORD_NUEVA = "Ficticia-Nueva-C11-0001-no-real"


@pytest_asyncio.fixture()
async def roles_c11() -> AsyncGenerator[None, None]:
    """Admin + recepcion + odontologo sinteticos; self-cleanup en RED."""
    await crear_usuario_ficticio(EMAIL_ADMIN, PASSWORD_FICTICIA, "admin")
    await crear_usuario_ficticio(EMAIL_RECEPCION, PASSWORD_FICTICIA, "recepcion")
    await crear_usuario_ficticio(EMAIL_ODONTOLOGO, PASSWORD_FICTICIA, "odontologo")
    yield
    for email in (EMAIL_ADMIN, EMAIL_RECEPCION, EMAIL_ODONTOLOGO, EMAIL_NUEVO):
        await eliminar_usuario_ficticio(email)
    async with TestSession() as sesion:
        await sesion.execute(
            delete(AuditoriaLog).where(AuditoriaLog.entidad == "usuario")
        )
        await sesion.commit()


async def _access_para(cliente: AsyncClient, email: str) -> str:
    # Arrange: login del rol pedido.
    login = await cliente.post(
        LOGIN_URL, json={"email": email, "password": PASSWORD_FICTICIA}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


async def _cabeceras(cliente: AsyncClient, email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {await _access_para(cliente, email)}"}


async def _eventos(accion: str) -> list[AuditoriaLog]:
    async with TestSession() as sesion:
        return list(
            (
                await sesion.execute(
                    select(AuditoriaLog).where(AuditoriaLog.accion == accion)
                )
            )
            .scalars()
            .all()
        )


async def test_admin_crea_usuario_odontologo_201_sin_hash(
    cliente: AsyncClient, roles_c11: None
) -> None:
    # Arrange: JWT admin.
    cabeceras = await _cabeceras(cliente, EMAIL_ADMIN)
    # Act: alta con email/rol/password validos.
    respuesta = await cliente.post(
        USUARIOS_URL,
        json={"email": EMAIL_NUEVO, "rol": "odontologo", "password": PASSWORD_NUEVA},
        headers=cabeceras,
    )
    # Assert: 201 con {id, email, rol, activo} sin password_hash + evento.
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["email"] == EMAIL_NUEVO
    assert cuerpo["rol"] == "odontologo"
    assert cuerpo["activo"] is True
    assert "id" in cuerpo
    plano = respuesta.text.lower()
    assert "password_hash" not in plano
    assert "hash" not in plano or "password_hash" not in plano
    eventos = await _eventos("usuario_creado")
    assert len(eventos) == 1


async def test_recepcion_crear_usuario_403_mas_log(
    cliente: AsyncClient, roles_c11: None
) -> None:
    # Arrange: JWT recepcion (no admin).
    cabeceras = await _cabeceras(cliente, EMAIL_RECEPCION)
    # Act: intenta alta reservada a admin.
    respuesta = await cliente.post(
        USUARIOS_URL,
        json={"email": EMAIL_NUEVO, "rol": "recepcion", "password": PASSWORD_NUEVA},
        headers=cabeceras,
    )
    # Assert: 403 generico sin crear nada + acceso_denegado.
    assert respuesta.status_code == 403
    assert "admin" not in respuesta.text.lower()
    async with TestSession() as sesion:
        creado = (
            await sesion.execute(select(Usuario).where(Usuario.email == EMAIL_NUEVO))
        ).scalar_one_or_none()
    assert creado is None
    denegados = await _eventos("acceso_denegado")
    assert len(denegados) >= 1


async def test_email_duplicado_409_sin_efectos(
    cliente: AsyncClient, roles_c11: None
) -> None:
    # Arrange: admin crea un usuario valido.
    cabeceras = await _cabeceras(cliente, EMAIL_ADMIN)
    primera = await cliente.post(
        USUARIOS_URL,
        json={"email": EMAIL_NUEVO, "rol": "recepcion", "password": PASSWORD_NUEVA},
        headers=cabeceras,
    )
    assert primera.status_code == 201
    # Act: reintento con el mismo email.
    duplicada = await cliente.post(
        USUARIOS_URL,
        json={"email": EMAIL_NUEVO, "rol": "odontologo", "password": PASSWORD_NUEVA},
        headers=cabeceras,
    )
    # Assert: 409 sin segundo usuario ni segundo evento de alta.
    assert duplicada.status_code == 409
    async with TestSession() as sesion:
        filas = (
            (await sesion.execute(select(Usuario).where(Usuario.email == EMAIL_NUEVO)))
            .scalars()
            .all()
        )
    assert len(filas) == 1
    assert len(await _eventos("usuario_creado")) == 1


async def test_rol_invalido_422_sin_efectos(
    cliente: AsyncClient, roles_c11: None
) -> None:
    # Arrange: JWT admin.
    cabeceras = await _cabeceras(cliente, EMAIL_ADMIN)
    # Act: alta con rol fuera del enum.
    respuesta = await cliente.post(
        USUARIOS_URL,
        json={"email": EMAIL_NUEVO, "rol": "superadmin", "password": PASSWORD_NUEVA},
        headers=cabeceras,
    )
    # Assert: 422 sin crear usuario ni evento.
    assert respuesta.status_code == 422
    async with TestSession() as sesion:
        creado = (
            await sesion.execute(select(Usuario).where(Usuario.email == EMAIL_NUEVO))
        ).scalar_one_or_none()
    assert creado is None
    assert await _eventos("usuario_creado") == []


async def test_baja_logica_desactiva_y_login_posterior_401(
    cliente: AsyncClient, roles_c11: None
) -> None:
    # Arrange: admin crea un usuario activo.
    cabeceras = await _cabeceras(cliente, EMAIL_ADMIN)
    alta = await cliente.post(
        USUARIOS_URL,
        json={"email": EMAIL_NUEVO, "rol": "recepcion", "password": PASSWORD_NUEVA},
        headers=cabeceras,
    )
    assert alta.status_code == 201
    usuario_id = str(alta.json()["id"])
    # Act: baja logica + login posterior del desactivado.
    baja = await cliente.delete(f"{USUARIOS_URL}/{usuario_id}", headers=cabeceras)
    assert baja.status_code == 200
    assert baja.json()["activo"] is False
    login = await cliente.post(
        LOGIN_URL, json={"email": EMAIL_NUEVO, "password": PASSWORD_NUEVA}
    )
    # Assert: login 401 (usuario inactivo) + evento auditado, sin borrado fisico.
    assert login.status_code == 401
    async with TestSession() as sesion:
        fila = (
            await sesion.execute(select(Usuario).where(Usuario.email == EMAIL_NUEVO))
        ).scalar_one_or_none()
    assert fila is not None
    assert fila.activo is False
    assert len(await _eventos("usuario_desactivado")) == 1


async def test_admin_cambia_rol_recepcion_a_odontologo_auditado(
    cliente: AsyncClient, roles_c11: None
) -> None:
    # Arrange: admin crea un recepcionista.
    cabeceras = await _cabeceras(cliente, EMAIL_ADMIN)
    alta = await cliente.post(
        USUARIOS_URL,
        json={"email": EMAIL_NUEVO, "rol": "recepcion", "password": PASSWORD_NUEVA},
        headers=cabeceras,
    )
    assert alta.status_code == 201
    usuario_id = str(alta.json()["id"])
    # Act: cambia rol a odontologo.
    cambio = await cliente.patch(
        f"{USUARIOS_URL}/{usuario_id}", json={"rol": "odontologo"}, headers=cabeceras
    )
    # Assert: 200 con rol nuevo + rol_cambiado sin hash/tokens.
    assert cambio.status_code == 200
    assert cambio.json()["rol"] == "odontologo"
    assert "password_hash" not in cambio.text.lower()
    assert "token" not in cambio.text.lower()
    eventos = await _eventos("rol_cambiado")
    assert len(eventos) == 1
    plano = str(eventos[0].diff).lower()
    assert "recepcion" in plano
    assert "odontologo" in plano
    assert "password_hash" not in plano
    assert "token" not in plano


async def test_odontologo_lista_usuarios_403_mas_log(
    cliente: AsyncClient, roles_c11: None
) -> None:
    # Arrange: JWT odontologo.
    cabeceras = await _cabeceras(cliente, EMAIL_ODONTOLOGO)
    # Act: lista reservada a admin.
    respuesta = await cliente.get(USUARIOS_URL, headers=cabeceras)
    # Assert: 403 generico + acceso_denegado.
    assert respuesta.status_code == 403
    assert "admin" not in respuesta.text.lower()
    assert len(await _eventos("acceso_denegado")) >= 1


async def test_admin_no_puede_autodegradarse_422(
    cliente: AsyncClient, roles_c11: None
) -> None:
    # Arrange: id propio del admin.
    cabeceras = await _cabeceras(cliente, EMAIL_ADMIN)
    async with TestSession() as sesion:
        propio = (
            await sesion.execute(select(Usuario).where(Usuario.email == EMAIL_ADMIN))
        ).scalar_one()
        propio_id = str(propio.id)
    # Act: intenta quitarse su propio rol admin.
    respuesta = await cliente.patch(
        f"{USUARIOS_URL}/{propio_id}", json={"rol": "recepcion"}, headers=cabeceras
    )
    # Assert: 422 y conserva admin.
    assert respuesta.status_code == 422
    async with TestSession() as sesion:
        tras = (
            await sesion.execute(select(Usuario).where(Usuario.email == EMAIL_ADMIN))
        ).scalar_one()
    assert tras.rol == "admin"
