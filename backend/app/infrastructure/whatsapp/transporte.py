"""Transporte WhatsApp C-06 (design decisión 1, R5/R6/R7).

Protocolo `WhatsAppTransport`: servicios y workers solo conocen esta
interfaz; la implementación se resuelve por settings (`WA_TRANSPORT`):

- `HttpWhatsAppTransport` (prod): `httpx` contra la API de Meta con
  `WA_TIMEOUT_S`; modo `WA_DRY_RUN` que NO toca la red (encola y audita).
- `FakeWhatsAppTransport` (tests/dev): cola en memoria con fallos
  programables (`ok` / `5xx` / `timeout` / `4xx`); jamás red real.

`TransporteError` distingue transitorio (5xx/timeout/conexión → el
worker reintenta con backoff) de permanente (4xx de Meta → directo a
fallback sin reintentar). Jamás se loguean cuerpos ni teléfonos: el
destino viaja como `destino_hash` (`sha256(tel)[:12]`, R6, Ley 25.326).
Secretos (`WHATSAPP_TOKEN`) solo por env (R7). Todo sintético en tests
con prefijo `+54 9 11 15-000-XXXX` (R0); type hints siempre (R1).
"""

from __future__ import annotations

from typing import Protocol

from app.core.logger import get_logger
from app.core.settings import settings

logger = get_logger(__name__)


class TransporteError(Exception):
    """Fallo de envío con semántica de reintento (design decisión 2)."""

    def __init__(self, mensaje: str, estado_http: int = 500) -> None:
        super().__init__(mensaje)
        self.estado_http = estado_http
        self.transitorio = estado_http >= 500 or estado_http == 408

    @classmethod
    def timeout(cls, mensaje: str = "timeout_ficticio") -> TransporteError:
        return cls(mensaje, estado_http=504)

    @classmethod
    def permanente(cls, mensaje: str, estado_http: int = 400) -> TransporteError:
        return cls(mensaje, estado_http=estado_http)


class WhatsAppTransport(Protocol):
    """Contrato mínimo que usan scheduler y workers (standard fastapi)."""

    async def enviar(
        self,
        *,
        destino_hash: str,
        plantilla: str,
        variables: dict[str, str],
    ) -> str:
        """Un intento de envío; retorna `proveedor_msg_id` o falla."""
        ...


class FakeWhatsAppTransport:
    """Doble en memoria (tests/dev): fallos programables, cero red (R5).

    `fallos`: pasos por envío (`5xx`/`timeout`/`4xx`/`ok`); agotada la
    lista responde ok. `llamadas` registra solo hashes (R6) para los
    asserts de exactamente-una-vez.
    """

    def __init__(self, fallos: list[str] | None = None) -> None:
        self._fallos: list[str] = list(fallos or [])
        self.llamadas: list[dict[str, str]] = []
        self._seq: int = 0

    @property
    def fallos_restantes(self) -> int:
        return len(self._fallos)

    def programar(self, fallos: list[str]) -> None:
        self._fallos.extend(fallos)

    def reiniciar(self) -> None:
        self._fallos.clear()
        self.llamadas.clear()
        self._seq = 0

    async def enviar(
        self, *, destino_hash: str, plantilla: str, variables: dict[str, str]
    ) -> str:
        modo = self._fallos.pop(0) if self._fallos else "ok"
        self._seq += 1
        if modo == "ok":
            proveedor_id = f"wamid.ficticio-{self._seq:04d}"
            self.llamadas.append(
                {
                    "destino_hash": destino_hash,
                    "plantilla": plantilla,
                    "proveedor_msg_id": proveedor_id,
                }
            )
            return proveedor_id
        if modo == "4xx":
            raise TransporteError.permanente("numero_invalido_ficticio", 400)
        if modo == "timeout":
            raise TransporteError.timeout("timeout_ficticio")
        raise TransporteError(f"fallo_transitorio_ficticio_{modo}", 500)


class HttpWhatsAppTransport:
    """Transporte real (prod): `httpx` con timeout + dry-run (R7/R8).

    Con `WA_DRY_RUN=true` (default) no sale a la red: retorna un id
    `dryrun-*` para pilotos sin plantillas aprobadas (design riesgo 1).
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        phone_id: str | None = None,
        timeout_s: float | None = None,
        dry_run: bool | None = None,
    ) -> None:
        self._token = token or settings.whatsapp_token
        self._phone_id = phone_id or settings.whatsapp_phone_id
        self._timeout_s = timeout_s or settings.wa_timeout_s
        self._dry_run = settings.wa_dry_run if dry_run is None else dry_run
        self._seq = 0

    async def enviar(
        self, *, destino_hash: str, plantilla: str, variables: dict[str, str]
    ) -> str:
        if self._dry_run:
            self._seq += 1
            logger.info(
                "aviso en dry-run (sin red)",
                extra={"plantilla": plantilla, "destino": destino_hash},
            )
            return f"dryrun-{self._seq:04d}"
        import httpx

        url = f"https://graph.facebook.com/v21.0/{self._phone_id}/messages"
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as cliente:
                respuesta = await cliente.post(
                    url,
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={
                        "messaging_product": "whatsapp",
                        "to_hash": destino_hash,
                        "type": "template",
                        "template": {"name": plantilla},
                    },
                )
        except (TimeoutError, OSError) as exc:
            raise TransporteError.timeout(str(exc)) from exc
        except Exception as exc:
            raise TransporteError(str(exc), 500) from exc
        if respuesta.status_code >= 500 or respuesta.status_code == 408:
            raise TransporteError(
                f"meta_{respuesta.status_code}", respuesta.status_code
            )
        if respuesta.status_code >= 400:
            raise TransporteError.permanente(
                f"meta_{respuesta.status_code}", respuesta.status_code
            )
        self._seq += 1
        return f"wamid-{self._seq:04d}"


_fake_global: FakeWhatsAppTransport | None = None


def obtener_transporte() -> WhatsAppTransport:
    """Fábrica por settings (el worker real la usa; los tests inyectan).

    `WA_TRANSPORT=fake` → singleton Fake (dev/tests, sin red).
    Cualquier otro valor → HTTP prod (con dry-run según `WA_DRY_RUN`).
    """
    global _fake_global
    if settings.wa_transport == "fake":
        if _fake_global is None:
            _fake_global = FakeWhatsAppTransport()
        return _fake_global
    return HttpWhatsAppTransport()
