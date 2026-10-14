"""Cliente Mercado Pago C-08 (protocolo mockeable + HTTP prod, R0/R5/R7)."""

from app.infrastructure.mercadopago.client import (
    HttpMercadoPagoClient,
    MercadoPagoClient,
    MercadoPagoNoDisponibleError,
    cliente_para_app,
    normalizar_estado,
)

__all__ = [
    "HttpMercadoPagoClient",
    "MercadoPagoClient",
    "MercadoPagoNoDisponibleError",
    "cliente_para_app",
    "normalizar_estado",
]
