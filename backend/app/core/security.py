"""Seguridad C-02: hash Argon2id + JWT HS256 (R1: todo tipado, R7: sin secretos).

Decisiones de `design.md` §1-§2: Argon2id vía `pwdlib` (nunca `passlib`);
JWT vía `PyJWT` con HS256 (nunca `python-jose`). Validación explícita:
firma, `exp` (leeway 30 s por skew), `type` esperado por endpoint
(`access` vs `refresh`) y presencia de `sub`/`jti`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

# Único hasheador: Argon2id (ganador PHC, memory-hard). Sin hashes legacy
# que migrar: un bcrypt viejo se rechaza y se rota la credencial en el seed.
_hasheador = PasswordHash((Argon2Hasher(),))

ALGORITMO_JWT = "HS256"
LEEWAY_SEGUNDOS = 30


def hashear_password(password: str) -> str:
    """Hash Argon2id de una contraseña en claro (jamás se loguea ni audita)."""
    return _hasheador.hash(password)


def verificar_password(password: str, password_hash: str) -> bool:
    """Compara en tiempo constante; hash legado/inválido → `False` (R6)."""
    try:
        return bool(_hasheador.verify(password, password_hash))
    except (ValueError, AttributeError):
        return False


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def crear_token(
    *,
    secreto: str,
    usuario_id: uuid.UUID,
    email: str,
    roles: list[str],
    tipo: str,
    expira_en: timedelta,
) -> tuple[str, str]:
    """Emite un JWT firmado; retorna `(token, jti)`.

    Claims: `sub` (id usuario), `roles`, `email`, `jti`, `type`, `iat`, `exp`.
    """
    jti = str(uuid.uuid4())
    ahora = _ahora()
    claims: dict[str, Any] = {
        "sub": str(usuario_id),
        "roles": roles,
        "email": email,
        "jti": jti,
        "type": tipo,
        "iat": ahora,
        "exp": ahora + expira_en,
    }
    return jwt.encode(claims, secreto, algorithm=ALGORITMO_JWT), jti


def crear_par_tokens(
    *,
    secreto: str,
    usuario_id: uuid.UUID,
    email: str,
    roles: list[str],
    access_min: int,
    refresh_days: int,
) -> dict[str, tuple[str, str]]:
    """Par access (minutos) + refresh (días) con `jti` independientes."""
    access, jti_access = crear_token(
        secreto=secreto,
        usuario_id=usuario_id,
        email=email,
        roles=roles,
        tipo="access",
        expira_en=timedelta(minutes=access_min),
    )
    refresh, jti_refresh = crear_token(
        secreto=secreto,
        usuario_id=usuario_id,
        email=email,
        roles=roles,
        tipo="refresh",
        expira_en=timedelta(days=refresh_days),
    )
    return {"access": (access, jti_access), "refresh": (refresh, jti_refresh)}


def decodificar_y_validar(
    token: str, *, secreto: str, tipo_esperado: str
) -> dict[str, Any]:
    """Valida firma + `exp` (leeway 30 s) + `type` + presencia de `sub`/`jti`.

    Lanza `jwt.PyJWTError` (o subclase) ante cualquier problema: el llamador
    responde 401 genérico sin exponer el motivo (R6).
    """
    claims: dict[str, Any] = jwt.decode(
        token,
        secreto,
        algorithms=[ALGORITMO_JWT],
        leeway=LEEWAY_SEGUNDOS,
        options={"require": ["exp", "iat", "sub", "jti"]},
    )
    if claims.get("type") != tipo_esperado:
        raise jwt.InvalidTokenError("tipo de token inesperado")
    if not claims.get("sub") or not claims.get("jti"):
        raise jwt.InvalidTokenError("claims incompletos")
    return claims
