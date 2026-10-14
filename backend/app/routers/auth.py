"""Endpoints de autenticación JWT (spec `auth/autenticacion-jwt`, design §2-§6).

- `POST /auth/login`: 200 + access en cuerpo + refresh en cookie HttpOnly;
  401 genérico sin revelar existencia (R6); rate limit 5/60 s por IP+email
  hasheado → 429 + `Retry-After`; 10 fallidos → bloqueo 900 s.
- `POST /auth/refresh`: rotación (revoca fila vieja + blacklista en Redis,
  emite par nuevo); reuso → 401 + revocación de cadena + auditoría.
- `POST /auth/logout`: revoca + blacklista (idempotente) → 200.
- `GET /auth/me`: perfil propio sin `password_hash` (R6).

Errores con clave `detalle` (contrato de los tests RED); jamás PII, hashes
ni tokens en respuestas ni logs (R6, Ley 25.326).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.dependencies import get_current_user
from app.core.logger import get_logger
from app.core.security import (
    ALGORITMO_JWT,
    crear_par_tokens,
    decodificar_y_validar,
    verificar_password,
)
from app.core.settings import settings
from app.models.entidades import Usuario
from app.repositories import auditoria as repo_auditoria
from app.repositories import sesiones as repo_sesiones
from app.schemas.auth import LoginRequest, MeResponse, TokenResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_REFRESH = "refresh_token"
DETALLE_CREDENCIALES = "Credenciales inválidas."
DETALLE_SIN_SESION = "Sesión inválida."
DETALLE_RATELIMIT = "Demasiados intentos. Reintentá más tarde."
DETALLE_BLOQUEO = "Cuenta bloqueada temporalmente. Reintentá más tarde."

# Hash inválido fijo: evita revelar por timing si el email existe (R6).
_HASH_SIN_USUARIO = "$argon2id$v=19$m=65536,t=3,p=4$AAAAAAAAAAAAAAAAAAAAAA$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def _email_norm(email: str) -> str:
    return email.strip().lower()


def _huella_email(email_norm: str) -> str:
    return hashlib.sha256(email_norm.encode()).hexdigest()


def _ip(request: Request) -> str:
    if request.client is not None:
        return str(request.client.host)
    return "desconocida"


def _redis(request: Request) -> Any:
    return request.app.state.redis


def _respuesta(
    estado: int, detalle: str, reintento_s: int | None = None
) -> JSONResponse:
    headers = {"Retry-After": str(reintento_s)} if reintento_s is not None else None
    return JSONResponse(
        status_code=estado, content={"detalle": detalle}, headers=headers
    )


async def _redis_seguro(request: Request, operacion: str, *args: Any) -> Any:
    """Ejecuta una operación Redis con degradación fail-open (design riesgo)."""
    try:
        cliente = _redis(request)
        metodo = getattr(cliente, operacion)
        return await metodo(*args)
    except Exception as exc:  # noqa: BLE001 — fail-open intencional: CUALQUIER
        # falla de Redis (red, timeout, tipos) degrada con warning; la DB manda.
        logger.warning("redis no disponible, degradando", extra={"op": operacion})
        logger.debug("detalle redis: %s", type(exc).__name__)
        return None


async def _chequear_ratelimit(request: Request, email_norm: str) -> int | None:
    """INCR+EXPIRE (equivalente al Lua del design); retorna espera o `None`."""
    clave = f"rl:login:{_ip(request)}:{_huella_email(email_norm)}"
    conteo = await _redis_seguro(request, "incr", clave)
    if conteo is None:
        return None  # Redis caído → fail-open con warning ya logueado.
    if conteo == 1:
        await _redis_seguro(request, "expire", clave, settings.rate_login_window_s)
    if conteo > settings.rate_login_max:
        ttl = await _redis_seguro(request, "ttl", clave)
        espera = (
            ttl if isinstance(ttl, int) and ttl > 0 else settings.rate_login_window_s
        )
        return espera
    return None


async def _chequear_bloqueo(request: Request, email_norm: str) -> int | None:
    clave = f"lock:login:{_huella_email(email_norm)}"
    existe = await _redis_seguro(request, "exists", clave)
    if existe:
        ttl = await _redis_seguro(request, "ttl", clave)
        espera = ttl if isinstance(ttl, int) and ttl > 0 else settings.lockout_s
        return espera
    return None


async def _registrar_fallido(request: Request, email_norm: str) -> None:
    clave_fallos = f"fail:login:{_huella_email(email_norm)}"
    fallos = await _redis_seguro(request, "incr", clave_fallos)
    if fallos is None:
        return
    if fallos == 1:
        await _redis_seguro(request, "expire", clave_fallos, settings.lockout_s)
    if fallos >= settings.lockout_max_intentos:
        await _redis_seguro(
            request,
            "set",
            f"lock:login:{_huella_email(email_norm)}",
            "1",
            "EX",
            settings.lockout_s,
        )


def _par_tokens(usuario: Usuario) -> dict[str, tuple[str, str]]:
    return crear_par_tokens(
        secreto=settings.jwt_secret,
        usuario_id=usuario.id,
        email=usuario.email,
        roles=[usuario.rol],
        access_min=settings.jwt_access_min,
        refresh_days=settings.jwt_refresh_days,
    )


def _set_cookie_refresh(respuesta: JSONResponse, refresh: str) -> None:
    respuesta.set_cookie(
        COOKIE_REFRESH,
        refresh,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api/v1/auth",
        max_age=settings.jwt_refresh_days * 24 * 3600,
    )


@router.post("/login", response_model=TokenResponse, summary="Iniciar sesión")
async def login(
    datos: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> JSONResponse:
    email_norm = _email_norm(datos.email)

    espera = await _chequear_ratelimit(request, email_norm)
    if espera is not None:
        return _respuesta(429, DETALLE_RATELIMIT, espera)
    espera = await _chequear_bloqueo(request, email_norm)
    if espera is not None:
        return _respuesta(429, DETALLE_BLOQUEO, espera)

    usuario = (
        await session.execute(select(Usuario).where(Usuario.email == email_norm))
    ).scalar_one_or_none()
    candidato = usuario.password_hash if usuario is not None else _HASH_SIN_USUARIO
    valida = verificar_password(datos.password, candidato) and usuario is not None

    if not valida or (usuario is not None and not usuario.activo):
        # Mismo 401 para inexistente/incorrecta/inactivo (R6: no revela nada).
        await _registrar_fallido(request, email_norm)
        await repo_auditoria.registrar_auditoria(
            session,
            accion="login",
            entidad="sesion",
            diff={"resultado": "fallido"},
            usuario_id=usuario.id if usuario is not None else None,
            ip=_ip(request),
        )
        await session.commit()
        logger.warning("login fallido")
        return _respuesta(401, DETALLE_CREDENCIALES)

    assert usuario is not None  # `valida` lo implica; ayuda a mypy.
    par = _par_tokens(usuario)
    access, _jti_access = par["access"]
    refresh, jti_refresh = par["refresh"]
    await repo_sesiones.crear_sesion(
        session,
        jti=jti_refresh,
        usuario_id=usuario.id,
        expira_at=datetime.now(timezone.utc)
        + timedelta(days=settings.jwt_refresh_days),
    )
    await repo_auditoria.registrar_auditoria(
        session,
        accion="login",
        entidad="sesion",
        diff={"resultado": "exitoso"},
        usuario_id=usuario.id,
        ip=_ip(request),
    )
    await session.commit()

    respuesta = JSONResponse(
        status_code=200,
        content=TokenResponse(access_token=access).model_dump(),
    )
    _set_cookie_refresh(respuesta, refresh)
    return respuesta


async def _revocar_cadena(
    session: AsyncSession, request: Request, usuario_id: Any, jti: str
) -> None:
    """Reuso/logout: revoca fila(s) + blacklista el jti con TTL remanente."""
    uid = _uuid_o_nulo(usuario_id)
    if uid is None:
        return
    await repo_sesiones.revocar_cadena_usuario(session, uid)
    await _redis_seguro(
        request,
        "set",
        f"bl:refresh:{jti}",
        "1",
        "EX",
        settings.jwt_refresh_days * 24 * 3600,
    )


def _uuid_o_nulo(valor: Any) -> uuid.UUID | None:
    """`sub` del claim → UUID para auditoría (nulo si no parsea, R6)."""
    try:
        return valor if isinstance(valor, uuid.UUID) else uuid.UUID(str(valor))
    except (ValueError, AttributeError):
        return None


@router.post("/refresh", response_model=TokenResponse, summary="Rotar par")
async def refresh(
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> JSONResponse:
    token = request.cookies.get(COOKIE_REFRESH)
    if not token:
        return _respuesta(401, DETALLE_SIN_SESION)
    try:
        claims = decodificar_y_validar(
            token, secreto=settings.jwt_secret, tipo_esperado="refresh"
        )
    except jwt.PyJWTError:
        return _respuesta(401, DETALLE_SIN_SESION)

    jti = str(claims["jti"])
    if await _redis_seguro(request, "exists", f"bl:refresh:{jti}"):
        # Reuso de refresh revocado: señal de robo → revocar cadena + 401.
        await _revocar_cadena(session, request, claims["sub"], jti)
        await repo_auditoria.registrar_auditoria(
            session,
            accion="refresh",
            entidad="sesion",
            diff={"resultado": "reuso_revocado"},
            usuario_id=_uuid_o_nulo(claims["sub"]),
            ip=_ip(request),
        )
        await session.commit()
        logger.warning("reuso de refresh revocado")
        return _respuesta(401, DETALLE_SIN_SESION)

    fila = await repo_sesiones.buscar_por_jti(session, jti)
    if fila is None or fila.revocado or fila.expira_at <= datetime.now(timezone.utc):
        if fila is not None and fila.revocado:
            await _revocar_cadena(session, request, claims["sub"], jti)
            await repo_auditoria.registrar_auditoria(
                session,
                accion="refresh",
                entidad="sesion",
                diff={"resultado": "reuso_revocado"},
                usuario_id=_uuid_o_nulo(claims["sub"]),
                ip=_ip(request),
            )
            await session.commit()
            logger.warning("reuso de refresh revocado")
        return _respuesta(401, DETALLE_SIN_SESION)

    usuario = (
        await session.execute(select(Usuario).where(Usuario.id == fila.usuario_id))
    ).scalar_one_or_none()
    if usuario is None or not usuario.activo:
        return _respuesta(401, DETALLE_SIN_SESION)

    # Rotación: revoca fila vieja + blacklista + emite par nuevo.
    await repo_sesiones.revocar_por_jti(session, jti)
    await _redis_seguro(
        request,
        "set",
        f"bl:refresh:{jti}",
        "1",
        "EX",
        settings.jwt_refresh_days * 24 * 3600,
    )
    par = _par_tokens(usuario)
    access, _jti_access = par["access"]
    refresh_nuevo, jti_nuevo = par["refresh"]
    await repo_sesiones.crear_sesion(
        session,
        jti=jti_nuevo,
        usuario_id=usuario.id,
        expira_at=datetime.now(timezone.utc)
        + timedelta(days=settings.jwt_refresh_days),
    )
    await repo_auditoria.registrar_auditoria(
        session,
        accion="refresh",
        entidad="sesion",
        diff={"resultado": "rotado"},
        usuario_id=usuario.id,
        ip=_ip(request),
    )
    await session.commit()

    respuesta = JSONResponse(
        status_code=200,
        content=TokenResponse(access_token=access).model_dump(),
    )
    _set_cookie_refresh(respuesta, refresh_nuevo)
    return respuesta


@router.post("/logout", summary="Cerrar sesión")
async def logout(
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> JSONResponse:
    token = request.cookies.get(COOKIE_REFRESH)
    if token:
        try:
            # Idempotente: admite expirado (solo destruye); firma/tipo mandan.
            claims: dict[str, Any] = jwt.decode(
                token,
                settings.jwt_secret,
                algorithms=[ALGORITMO_JWT],
                options={"verify_exp": False, "require": ["sub", "jti"]},
            )
            if (
                claims.get("type") == "refresh"
                and claims.get("sub")
                and claims.get("jti")
            ):
                jti = str(claims["jti"])
                await repo_sesiones.revocar_por_jti(session, jti)
                await _redis_seguro(
                    request,
                    "set",
                    f"bl:refresh:{jti}",
                    "1",
                    "EX",
                    settings.jwt_refresh_days * 24 * 3600,
                )
                await repo_auditoria.registrar_auditoria(
                    session,
                    accion="logout",
                    entidad="sesion",
                    diff={"resultado": "exitoso"},
                    usuario_id=_uuid_o_nulo(claims["sub"]),
                    ip=_ip(request),
                )
                await session.commit()
        except jwt.PyJWTError:
            pass
    respuesta = JSONResponse(status_code=200, content={"detalle": "Sesión cerrada."})
    respuesta.delete_cookie(COOKIE_REFRESH, path="/api/v1/auth")
    return respuesta


@router.get("/me", response_model=MeResponse, summary="Perfil propio")
async def me(
    usuario: Usuario = Depends(get_current_user),  # noqa: B008
) -> MeResponse:
    return MeResponse(
        id=usuario.id, email=usuario.email, roles=[usuario.rol], activo=usuario.activo
    )
