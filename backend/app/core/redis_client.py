"""Capa de abstracción Redis (design §3-§4): fast-path, nunca verdad.

Producción usa Redis real vía `REDIS_URL` (compose canónico). En tests no
hay instancia local, así que `USAR_REDIS_FALSO=true` inyecta `fakeredis`
(API asyncio compatible) SIN cambiar el código que lo consume. Ante caída
de Redis el llamador degrada a fail-open con warning (la DB manda).

NOTA de decisión (delta mínimo en `design.md`, sin reescribir): se elige
`fakeredis` + INCR+EXPIRE por pipeline ("o equivalente" del design) en vez
de Lua, porque `fakeredis` no ejecuta Lua; el comportamiento observable
(tope 5/60 s, 429 + Retry-After) es idéntico y la suite lo verifica.
"""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.core.settings import settings

logger = get_logger(__name__)

_redis_falso: Any | None = None


def obtener_redis() -> Any:
    """Retorna el cliente Redis del proceso (real o falso según env).

    El cliente falso vive en `app.state.redis` cuando la app lo crea; este
    helper es el fallback para código fuera del ciclo request (tests unit.).
    """
    global _redis_falso
    if settings.usar_redis_falso:
        if _redis_falso is None:
            from fakeredis.aioredis import FakeRedis

            _redis_falso = FakeRedis(decode_responses=True)
        return _redis_falso
    import redis.asyncio as redis_real

    return redis_real.from_url(settings.redis_url, decode_responses=True)


def crear_redis_para_app() -> Any:
    """Fábrica por app: en tests cada `create_app()` aísla su contador."""
    if settings.usar_redis_falso:
        from fakeredis.aioredis import FakeRedis

        return FakeRedis(decode_responses=True)
    import redis.asyncio as redis_real

    return redis_real.from_url(settings.redis_url, decode_responses=True)


def reiniciar_redis_falso() -> None:
    """Solo tests: suelta el singleton entre suites (aislamiento total)."""
    global _redis_falso
    _redis_falso = None
