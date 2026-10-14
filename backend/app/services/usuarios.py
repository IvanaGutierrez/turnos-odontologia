"""Servicio de gestión de usuarios C-11 (R0–R8).

- `crear_usuario`: alta con email único (duplicado → `EmailDuplicadoError`
  → `409`), rol válido (pydantic → `422`), password con hash Argon2id;
  audita `usuario_creado` con `{usuario_id, email, rol}` (sin credenciales).
- `listar_usuarios` / `obtener_usuario`: solo IDs/roles/estados (R6).
- `actualizar_usuario`: cambia `rol` y/o `activo`; autodegradación del
  propio admin (quitarse `admin` o desactivarse) → `AutobloqueoError`
  → `422`; cambio de rol audita `rol_cambiado` con
  `{usuario_id, rol_anterior, rol_nuevo}`.
- `desactivar_usuario`: baja lógica (`activo=false`, nunca borrado
  físico) + `usuario_desactivado`; idempotente (ya inactivo → `200`
  sin evento duplicado).

Todo dato sintético (R0); type hints siempre (R1).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.core.security import hashear_password
from app.models.entidades import Usuario
from app.repositories import auditoria as repo_auditoria
from app.schemas.usuarios import UsuarioOut

logger = get_logger(__name__)


class EmailDuplicadoError(Exception):
    """Email ya registrado (→ `409`, sin crear nada)."""


class UsuarioNoEncontradoError(Exception):
    """Sin usuario para el id (→ `404` `problema: no_encontrado`)."""


class AutobloqueoError(Exception):
    """El admin no puede quitarse su propio rol ni desactivarse (→ `422`)."""


class ActualizacionVaciaError(Exception):
    """PATCH sin campos (→ `422`, sin efectos)."""


def cuerpo_usuario(usuario: Usuario) -> dict[str, object]:
    """Serialización allowlist (R6: jamás `password_hash`)."""
    return {
        "id": str(usuario.id),
        "email": usuario.email,
        "rol": usuario.rol,
        "activo": usuario.activo,
    }


def _email_norm(email: str) -> str:
    return email.strip().lower()


async def crear_usuario(
    session: AsyncSession,
    *,
    email: str,
    rol: str,
    password: str,
    actor_id: uuid.UUID,
    ip: str | None = None,
) -> Usuario:
    """Crea UN usuario interno (el router ya exigió `admin`)."""
    email_norm = _email_norm(email)
    previo = (
        await session.execute(select(Usuario.id).where(Usuario.email == email_norm))
    ).first()
    if previo is not None:
        raise EmailDuplicadoError(email_norm)
    usuario = Usuario(
        email=email_norm,
        password_hash=hashear_password(password),
        rol=rol,
        activo=True,
    )
    session.add(usuario)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        logger.info("alta de usuario rechazada por email duplicado")
        raise EmailDuplicadoError(email_norm) from exc
    await repo_auditoria.registrar_auditoria(
        session,
        accion="usuario_creado",
        entidad="usuario",
        entidad_id=str(usuario.id),
        diff={
            "usuario_id": str(usuario.id),
            "email": email_norm,
            "rol": rol,
        },
        usuario_id=actor_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(usuario)
    logger.info("usuario creado", extra={"usuario_id": str(usuario.id), "rol": rol})
    return usuario


async def listar_usuarios(
    session: AsyncSession, *, page: int, page_size: int
) -> tuple[list[Usuario], int]:
    """Página de usuarios ordenada por email + total."""
    total = int(await session.scalar(select(func.count()).select_from(Usuario)) or 0)
    filas = (
        (
            await session.execute(
                select(Usuario)
                .order_by(Usuario.email)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return list(filas), total


async def obtener_usuario(session: AsyncSession, usuario_id: uuid.UUID) -> Usuario:
    """Un usuario por id o `UsuarioNoEncontradoError`."""
    usuario = await session.get(Usuario, usuario_id)
    if usuario is None:
        raise UsuarioNoEncontradoError(str(usuario_id))
    return usuario


async def actualizar_usuario(
    session: AsyncSession,
    *,
    usuario_id: uuid.UUID,
    rol: str | None,
    activo: bool | None,
    actor_id: uuid.UUID,
    ip: str | None = None,
) -> Usuario:
    """Cambia `rol` y/o `activo` con autobloqueo y auditoría de rol."""
    if rol is None and activo is None:
        raise ActualizacionVaciaError("sin_cambios")
    usuario = await obtener_usuario(session, usuario_id)
    es_propio = usuario.id == actor_id
    if es_propio and rol is not None and rol != "admin":
        raise AutobloqueoError("autodegradacion")
    if es_propio and activo is False:
        raise AutobloqueoError("autodesactivacion")

    rol_anterior = usuario.rol
    if rol is not None:
        usuario.rol = rol
    if activo is not None:
        usuario.activo = activo
    await session.flush()

    if rol is not None and rol != rol_anterior:
        await repo_auditoria.registrar_auditoria(
            session,
            accion="rol_cambiado",
            entidad="usuario",
            entidad_id=str(usuario.id),
            diff={
                "usuario_id": str(usuario.id),
                "rol_anterior": rol_anterior,
                "rol_nuevo": usuario.rol,
            },
            usuario_id=actor_id,
            ip=ip,
        )
    if activo is False:
        await repo_auditoria.registrar_auditoria(
            session,
            accion="usuario_desactivado",
            entidad="usuario",
            entidad_id=str(usuario.id),
            diff={"usuario_id": str(usuario.id), "email": usuario.email},
            usuario_id=actor_id,
            ip=ip,
        )
    await session.commit()
    await session.refresh(usuario)
    logger.info(
        "usuario actualizado",
        extra={"usuario_id": str(usuario.id), "rol": usuario.rol},
    )
    return usuario


async def desactivar_usuario(
    session: AsyncSession,
    *,
    usuario_id: uuid.UUID,
    actor_id: uuid.UUID,
    ip: str | None = None,
) -> Usuario:
    """Baja lógica (`activo=false`); ya inactivo → `200` sin duplicar evento."""
    usuario = await obtener_usuario(session, usuario_id)
    if usuario.id == actor_id:
        raise AutobloqueoError("autodesactivacion")
    if usuario.activo:
        usuario.activo = False
        await session.flush()
        await repo_auditoria.registrar_auditoria(
            session,
            accion="usuario_desactivado",
            entidad="usuario",
            entidad_id=str(usuario.id),
            diff={"usuario_id": str(usuario.id), "email": usuario.email},
            usuario_id=actor_id,
            ip=ip,
        )
        await session.commit()
        await session.refresh(usuario)
        logger.info("usuario desactivado", extra={"usuario_id": str(usuario.id)})
    return usuario


def salida_usuario(usuario: Usuario) -> UsuarioOut:
    """Convierte a contrato de salida (validado por pydantic)."""
    return UsuarioOut(
        id=usuario.id, email=usuario.email, rol=usuario.rol, activo=usuario.activo
    )
