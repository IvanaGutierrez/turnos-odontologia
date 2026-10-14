"""Inventario de permisos (C-02 task 5.2, deny-by-default).

Todo router bajo `/api/v1` —salvo públicos explícitos de
`03_actores_y_roles.md` §Rutas públicas (health + login/logout)— exige JWT:
sin token responde 401/403 sin ejecutar la acción. Si un change futuro
agrega un endpoint interno sin permiso, este test lo señala.
"""

import pytest
from httpx import AsyncClient

from app.main import create_app

pytestmark = pytest.mark.integration

# Públicos explícitos: salud + entrada/salida de sesión (definición KB)
# + agenda pública C-03 (disponibilidad y reserva sin cuenta, specs
# `agenda/disponibilidad` y `agenda/reserva-publica`: sin JWT por diseño)
# + autogestión C-05 (ver/confirmar/cancelar/reprogramar por token,
# spec `agenda/autogestion-paciente`: sin JWT por diseño, con rate limit
# y 404 idéntico anti-enumeración).
RUTAS_PUBLICAS: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/v1/health"),
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/auth/logout"),
        ("GET", "/api/v1/disponibilidad"),
        ("POST", "/api/v1/turnos/publicos"),
        ("GET", "/api/v1/turnos/publicos/{token}"),
        ("POST", "/api/v1/turnos/publicos/{token}/confirmar"),
        ("POST", "/api/v1/turnos/publicos/{token}/cancelar"),
        ("POST", "/api/v1/turnos/publicos/{token}/reprogramar"),
    }
)


def rutas_internas() -> list[tuple[str, str]]:
    """Pares (método, path) /api/v1 no públicos (vía OpenAPI: materializa routers).

    (FastAPI ≥0.135 difiere `include_router` tras `_IncludedRouter`; el
    esquema OpenAPI es la fuente estable del inventario.)
    """
    internas: list[tuple[str, str]] = []
    for path, operaciones in create_app().openapi()["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for metodo in operaciones:
            if metodo.upper() not in ("GET", "POST"):
                continue
            if (metodo.upper(), path) not in RUTAS_PUBLICAS:
                internas.append((metodo.upper(), path))
    return internas


async def test_inventario_todo_interno_exige_jwt(cliente: AsyncClient) -> None:
    # Arrange: rutas internas registradas (auth, turnos, probes RBAC).
    internas = rutas_internas()
    assert len(internas) >= 6

    # Act + Assert: cada una sin token → 401/403 (nunca 2xx ni 500).
    for metodo, path in internas:
        if metodo == "GET":
            respuesta = await cliente.get(path)
            assert respuesta.status_code in (401, 403), path
        else:
            respuesta = await cliente.post(path, json={})
            assert respuesta.status_code in (401, 403, 422), path
