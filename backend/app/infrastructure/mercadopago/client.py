"""Cliente Mercado Pago C-08 (design decisión 2, R0/R5/R6/R7).

- `MercadoPagoClient`: protocolo que solo conocen los servicios (crea
  preferencia con `metadata={turno_id, presupuesto_id?}` en ARS y
  consulta el estado de un pago). El `FakeMercadoPagoClient` de
  `tests/conftest.py` lo implementa estructuralmente (mismos nombres y
  firmas con keywords): los tests lo programan y la app NUNCA toca red
  real en la suite (R0/R5).
- `HttpMercadoPagoClient`: implementación prod (`httpx` con
  `MP_TIMEOUT_S`, `MP_ACCESS_TOKEN` solo por env — R7). Timeouts,
  caídas y 5xx levantan `MercadoPagoNoDisponibleError` (degrada a
  manual, nunca pierde el turno).
- `cliente_para_app`: selección por settings (`MP_CLIENT=fake` en
  tests/dev usa `app.state.mp_fake`; `http` en prod).

R6: jamás viaja ni se loguea PII del pagador por aquí (solo monto,
moneda y metadata de IDs). El `access_token` jamás aparece en logs.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol

import httpx

from app.core.logger import get_logger
from app.core.settings import settings

logger = get_logger(__name__)

API_BASE = "https://api.mercadopago.com"

# Contratos que la parte de tests (Fake) y prod (HTTP) honran.
MONEDA_SENA = "ARS"
TITULO_PREFERENCIA = "Seña turno odontológico"


class MercadoPagoNoDisponibleError(Exception):
    """MP caído/transitorio → degradar a manual (turno intacto)."""


class MercadoPagoClient(Protocol):
    """Protocolo mockeable (el Fake de tests lo cumple por forma)."""

    async def crear_preferencia(
        self,
        *,
        monto: Decimal,
        moneda: str,
        metadata: dict[str, str],
    ) -> dict[str, Any]:
        """Crea la preferencia; retorna `{"id", "init_point", ...}`."""
        ...  # pragma: no cover - protocolo

    async def obtener_pago(self, mp_payment_id: str) -> dict[str, Any] | None:
        """Estado confirmado contra MP (`None` si es desconocido)."""
        ...  # pragma: no cover - protocolo


def normalizar_estado(estado_mp: str) -> str:
    """Estado MP → dominio (`aprobado|rechazado|pendiente`).

    Acepta el vocabulario del Fake (`aprobado|rechazado|pendiente`) y el
    de la API real (`approved|rejected|cancelled|in_process|pending`).
    Desconocido → `pendiente` (nunca acredita por defecto, CRITICO).
    """
    valor = estado_mp.strip().lower()
    if valor in ("aprobado", "approved", "accredited"):
        return "aprobado"
    if valor in ("rechazado", "rejected", "cancelled", "canceled"):
        return "rechazado"
    return "pendiente"


class HttpMercadoPagoClient:
    """Cliente prod (jamás usado en tests; R0: cero llamadas de red real)."""

    def __init__(self, *, access_token: str, timeout_s: float) -> None:
        self._access_token = access_token
        self._timeout_s = timeout_s

    def _cabeceras(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    async def crear_preferencia(
        self,
        *,
        monto: Decimal,
        moneda: str,
        metadata: dict[str, str],
    ) -> dict[str, Any]:
        """`POST /checkout/preferences` (timeout + 5xx → no disponible)."""
        cuerpo = {
            "items": [
                {
                    "title": TITULO_PREFERENCIA,
                    "quantity": 1,
                    "unit_price": float(monto),
                    "currency_id": moneda,
                }
            ],
            "metadata": dict(metadata),
            "external_reference": metadata.get("turno_id", ""),
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as http:
                respuesta = await http.post(
                    f"{API_BASE}/checkout/preferences",
                    json=cuerpo,
                    headers=self._cabeceras(),
                )
                respuesta.raise_for_status()
                datos = respuesta.json()
        except Exception as exc:
            logger.warning("mercadopago no disponible al crear preferencia")
            raise MercadoPagoNoDisponibleError("mp_no_disponible") from exc
        return {
            "id": str(datos.get("id", "")),
            "init_point": str(datos.get("init_point") or ""),
            "monto": monto,
            "moneda": moneda,
            "metadata": dict(metadata),
        }

    async def obtener_pago(self, mp_payment_id: str) -> dict[str, Any] | None:
        """`GET /v1/payments/:id` normalizado (404 MP → `None`)."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as http:
                respuesta = await http.get(
                    f"{API_BASE}/v1/payments/{mp_payment_id}",
                    headers=self._cabeceras(),
                )
                if respuesta.status_code == 404:
                    return None
                respuesta.raise_for_status()
                datos = respuesta.json()
        except Exception as exc:
            logger.warning("mercadopago no disponible al consultar pago")
            raise MercadoPagoNoDisponibleError("mp_no_disponible") from exc
        metadata = datos.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        if datos.get("external_reference") and "turno_id" not in metadata:
            metadata = {**metadata, "turno_id": str(datos["external_reference"])}
        return {
            "id": str(datos.get("id", mp_payment_id)),
            "estado": normalizar_estado(str(datos.get("status", ""))),
            "monto": Decimal(str(datos.get("transaction_amount", "0"))),
            "moneda": str(datos.get("currency_id", MONEDA_SENA)),
            "metadata": {str(k): str(v) for k, v in metadata.items()},
        }


def cliente_para_app(app: Any) -> MercadoPagoClient:
    """Resuelve el cliente según `MP_CLIENT` (design decisión 2).

    `fake` → `app.state.mp_fake` (la instancia que cada test programa;
    sin ella, no disponible en vez de red real). `http` → cliente prod.
    """
    if settings.mp_client == "fake":
        fake = getattr(app.state, "mp_fake", None)
        if fake is None:
            raise MercadoPagoNoDisponibleError("mp_fake_no_inyectado")
        return fake  # type: ignore[no-any-return]
    return HttpMercadoPagoClient(
        access_token=settings.mp_access_token,
        timeout_s=settings.mp_timeout_s,
    )
