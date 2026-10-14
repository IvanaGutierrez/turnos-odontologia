"""Repositorio de auditoría + `registrar_auditoria` (RN-AU-03, R6).

`sanitizar_diff()` elimina por denylist toda clave sensible antes de
persistir: el `diff` jamás contiene DNI, teléfonos, historia clínica,
hashes ni tokens. `email` SÍ puede auditarse como identificador de login
(es la identidad, no PII sorpresiva), pero jamás junto a credenciales.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auditoria import AuditoriaLog

# Denylist R6: claves prohibidas en cualquier nivel del diff.
# C-13 suma `afiliado` (cubre `nro_afiliado` y variantes): el nro. de
# afiliado es PII tan sensible como el DNI (Ley 25.326).
CLAVES_PROHIBIDAS: frozenset[str] = frozenset(
    {
        "password",
        "password_hash",
        "hash",
        "dni",
        "telefono",
        "afiliado",
        "anamnesis",
        "historia_clinica",
        "hc",
        "token",
        "token_publico",
        "refresh_token",
        "access_token",
        "authorization",
    }
)


def sanitizar_diff(diff: dict[str, Any]) -> dict[str, Any]:
    """Purga recursiva por denylist (case-insensitive, subcadenas incluidas)."""

    def _limpia(valor: Any) -> Any:
        if isinstance(valor, dict):
            return {
                k: ("[REDACTED]" if _prohibida(k) else _limpia(v))
                for k, v in valor.items()
            }
        if isinstance(valor, list):
            return [_limpia(v) for v in valor]
        return valor

    def _prohibida(clave: str) -> bool:
        baja = clave.lower()
        return any(p in baja for p in CLAVES_PROHIBIDAS)

    limpio = _limpia(diff)
    assert isinstance(limpio, dict)
    return limpio


async def registrar_auditoria(
    session: AsyncSession,
    *,
    accion: str,
    entidad: str,
    entidad_id: str | None = None,
    diff: dict[str, Any] | None = None,
    usuario_id: uuid.UUID | None = None,
    ip: str | None = None,
) -> AuditoriaLog:
    """Inserta un evento (append-only; la lectura llega en C-11)."""
    fila = AuditoriaLog(
        accion=accion,
        entidad=entidad,
        entidad_id=entidad_id,
        diff=sanitizar_diff(diff or {}),
        usuario_id=usuario_id,
        ip=ip,
    )
    session.add(fila)
    await session.flush()
    return fila
