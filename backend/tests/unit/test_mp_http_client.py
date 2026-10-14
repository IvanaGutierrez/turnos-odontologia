"""C-08 unitario: `HttpMercadoPagoClient` con transporte simulado (R0/R5).

El cliente prod NUNCA toca red en la suite: se simula `httpx.AsyncClient`
(a nivel de constructor) y se verifica forma de preferencia,
normalización del pago (metadata + `external_reference`), 404→`None` y
timeout/5xx→`MercadoPagoNoDisponibleError` (degrada a manual).

Todo dato sintético (R0); type hints siempre (R1).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from types import TracebackType
from typing import Any, Self
from unittest.mock import patch

import httpx
import pytest

from app.infrastructure.mercadopago.client import (
    HttpMercadoPagoClient,
    MercadoPagoNoDisponibleError,
)


class _RespuestaSimulada:
    """Doble mínimo de `httpx.Response` (solo lo que el cliente lee)."""

    def __init__(
        self,
        *,
        estado_http: int = 200,
        cuerpo: dict[str, Any] | None = None,
        fallar: bool = False,
    ) -> None:
        self.status_code = estado_http
        self._cuerpo = cuerpo or {}
        self._fallar = fallar

    def raise_for_status(self) -> None:
        if self._fallar or self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "fallo-ficticio", request=None, response=None  # type: ignore[arg-type]
            )

    def json(self) -> dict[str, Any]:
        return dict(self._cuerpo)


class _TransporteSimulado:
    """Doble de `httpx.AsyncClient` (gestor asíncrono + post/get)."""

    def __init__(self, respuesta: _RespuestaSimulada | BaseException) -> None:
        self._respuesta = respuesta
        self.peticiones: list[dict[str, Any]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        tipo: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def post(
        self, url: str, json: dict[str, Any], headers: dict[str, str]
    ) -> _RespuestaSimulada:
        self.peticiones.append({"metodo": "POST", "url": url, "cuerpo": json})
        assert "Authorization" in headers
        if isinstance(self._respuesta, BaseException):
            raise self._respuesta
        assert isinstance(self._respuesta, _RespuestaSimulada)
        return self._respuesta

    async def get(self, url: str, headers: dict[str, str]) -> _RespuestaSimulada:
        self.peticiones.append({"metodo": "GET", "url": url})
        assert "Authorization" in headers
        if isinstance(self._respuesta, BaseException):
            raise self._respuesta
        assert isinstance(self._respuesta, _RespuestaSimulada)
        return self._respuesta


@contextmanager
def _red_simulada(
    respuesta: _RespuestaSimulada | BaseException,
) -> Iterator[_TransporteSimulado]:
    transporte = _TransporteSimulado(respuesta)
    with patch(
        "app.infrastructure.mercadopago.client.httpx.AsyncClient",
        return_value=transporte,
    ):
        yield transporte


def _cliente() -> HttpMercadoPagoClient:
    return HttpMercadoPagoClient(access_token="token-ficticio-no-real", timeout_s=1.0)


async def test_crear_preferencia_con_metadata_ars() -> None:
    # Arrange: API simulada que devuelve preferencia ficticia.
    respuesta = _RespuestaSimulada(
        cuerpo={"id": "pref-ficticia-1", "init_point": "https://mp.ficticia/1"}
    )
    cliente = _cliente()

    # Act: crear preferencia en ARS con metadata.
    with _red_simulada(respuesta) as red:
        preferencia = await cliente.crear_preferencia(
            monto=Decimal("5000.00"),
            moneda="ARS",
            metadata={"turno_id": "tid-ficticio"},
        )

    # Assert: forma + metadata round-trip + ARS en el cuerpo enviado.
    assert preferencia["id"] == "pref-ficticia-1"
    assert preferencia["init_point"] == "https://mp.ficticia/1"
    assert preferencia["metadata"] == {"turno_id": "tid-ficticio"}
    enviado = red.peticiones[0]["cuerpo"]
    assert enviado["items"][0]["currency_id"] == "ARS"
    assert enviado["metadata"] == {"turno_id": "tid-ficticio"}
    assert enviado["external_reference"] == "tid-ficticio"


async def test_obtener_pago_normaliza_metadata_y_referencia() -> None:
    # Arrange: pago `approved` con metadata + external_reference.
    respuesta = _RespuestaSimulada(
        cuerpo={
            "id": "pay-ficticio-1",
            "status": "approved",
            "transaction_amount": 5000.0,
            "currency_id": "ARS",
            "metadata": {"presupuesto_id": "pid-ficticio"},
            "external_reference": "tid-ficticio",
        }
    )

    # Act: consultar el pago.
    with _red_simulada(respuesta):
        pago = await _cliente().obtener_pago("pay-ficticio-1")

    # Assert: estado normalizado + metadata fusionada + monto Decimal.
    assert pago is not None
    assert pago["estado"] == "aprobado"
    assert pago["metadata"]["turno_id"] == "tid-ficticio"
    assert pago["metadata"]["presupuesto_id"] == "pid-ficticio"
    assert pago["monto"] == Decimal("5000.0")
    assert pago["moneda"] == "ARS"


async def test_obtener_pago_inexistente_es_none() -> None:
    # Arrange: la API simulada responde 404.
    with _red_simulada(_RespuestaSimulada(estado_http=404)):
        pago = await _cliente().obtener_pago("pay-ficticio-ausente")

    # Assert: desconocido (el webhook lo deriva a conciliar, nunca acredita).
    assert pago is None


@pytest.mark.parametrize("falla", ["timeout", "http_500"])
async def test_falla_de_red_degrada_a_no_disponible(falla: str) -> None:
    # Arrange: timeout o 500 simulados en ambas operaciones.
    if falla == "timeout":
        simulada: _RespuestaSimulada | BaseException = httpx.ConnectTimeout(
            "corte-ficticio"
        )
    else:
        simulada = _RespuestaSimulada(estado_http=500, fallar=True)
    cliente = _cliente()

    # Act + Assert: crear y consultar degradan (el turno queda intacto).
    with _red_simulada(simulada), pytest.raises(MercadoPagoNoDisponibleError):
        await cliente.crear_preferencia(
            monto=Decimal("5000.00"),
            moneda="ARS",
            metadata={"turno_id": "tid-ficticio"},
        )
    with _red_simulada(simulada), pytest.raises(MercadoPagoNoDisponibleError):
        await cliente.obtener_pago("pay-ficticio-1")


async def test_obtener_pago_con_metadata_invalida_la_ignora() -> None:
    # Arrange: `metadata` no-dict (forma inesperada de la API).
    respuesta = _RespuestaSimulada(
        cuerpo={
            "id": "pay-ficticio-2",
            "status": "approved",
            "transaction_amount": 1000.0,
            "currency_id": "ARS",
            "metadata": "forma-invalida-ficticia",
        }
    )

    # Act: consultar el pago.
    with _red_simulada(respuesta):
        pago = await _cliente().obtener_pago("pay-ficticio-2")

    # Assert: metadata saneada a `{}` sin romper (nunca acredita por forma).
    assert pago is not None
    assert pago["estado"] == "aprobado"
    assert pago["metadata"] == {}


async def test_cliente_para_app_fake_http_y_faltante(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange: apps simuladas con/sin Fake + settings por defecto.
    from types import SimpleNamespace

    from app.core.settings import settings
    from app.infrastructure.mercadopago.client import cliente_para_app
    from tests.conftest import FakeMercadoPagoClient as FakeMP

    fake = FakeMP()
    con_fake = SimpleNamespace(state=SimpleNamespace(mp_fake=fake))
    sin_fake = SimpleNamespace(state=SimpleNamespace())

    # Act + Assert: `fake` usa la instancia inyectada (programable).
    assert cliente_para_app(con_fake) is fake  # type: ignore[arg-type]
    # Sin instancia no hay red real: degrada en vez de llamar a MP.
    with pytest.raises(MercadoPagoNoDisponibleError):
        cliente_para_app(sin_fake)  # type: ignore[arg-type]
    # `http` construye el cliente prod (sin red en el constructor).
    monkeypatch.setattr(settings, "mp_client", "http")
    construido = cliente_para_app(con_fake)
    assert isinstance(construido, HttpMercadoPagoClient)
