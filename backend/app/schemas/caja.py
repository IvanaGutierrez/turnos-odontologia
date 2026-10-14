"""Contratos de caja y cierre diario C-09 (documentan sin mirar el código).

- `POST /api/v1/caja/movimientos` (JWT `admin|recepcion`): crea UN
  movimiento `{fecha, sede, tipo: ingreso|egreso, concepto 1–280,
  monto > 0 ARS, metodo: efectivo|transferencia|tarjeta|mercadopago,
  pago_id?}` con `usuario_id` del operador → `201` con `{tipo,
  metodo, monto, usuario_id}` (el `concepto` se almacena pero JAMÁS
  se expone en responses/logs/auditoría — R6); método fuera del
  catálogo / monto ≤ 0 / concepto vacío → `422` sin efectos;
  fecha en día `cerrado` → `422` con `detalle == "dia_cerrado"`.
- `GET /api/v1/caja/movimientos?fecha&sede` → `200` con los del día
  (misma forma que el `201`, sin concepto — R6).
- `POST /api/v1/caja/cierre {fecha, sede}`: snapshot de totales por
  método desde movimientos (neto ingresos − egresos por método;
  `total_egresos` informativo) + `acreditado_mp` desde `pago`
  (`estado='acreditado'`, fecha operativa = `webhook_recibido_at`
  en `CAJA_TZ`) + `diferencia = total_mp − acreditado_mp` →
  `estado_conciliacion='cuadrado'` si `diferencia == 0` y
  `'con_diferencia'` si no; estado `cerrado` → `201`; segundo
  cierre del mismo día/sede → `409` (UNIQUE, la DB manda).
- `POST /api/v1/caja/reapertura {fecha, sede, motivo ≥10}`: solo
  `admin` → `200` con `estado='abierto'`; no-admin → `403`
  genérico + evento `reapertura_denegada`; sin cierre → `404`
  (`problema: no_encontrado`); ya abierto → `422`.
- `GET /api/v1/caja/cierre?fecha&sede` → `200` con snapshot o
  `404` (`problema: no_encontrado`).
- RBAC: `caja → {admin, recepcion}`, `reapertura_caja → {admin}`;
  odontólogo → `403` (`detalle: "Sin permiso."`); sin JWT → `401`.

Todo dato sintético (R0); type hints siempre (R1).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MetodoCaja = Literal["efectivo", "transferencia", "tarjeta", "mercadopago"]

TipoMovimiento = Literal["ingreso", "egreso"]

METODOS_CAJA: tuple[str, ...] = (
    "efectivo",
    "transferencia",
    "tarjeta",
    "mercadopago",
)

SEDE_DEFAULT = "Consultorio"


class MovimientoCreate(BaseModel):
    """`POST /caja/movimientos`: UN movimiento manual trazable (RN-PA-05)."""

    model_config = ConfigDict(extra="ignore")

    fecha: date = Field(description="Día operativo (en `CAJA_TZ`).")
    sede: str = Field(
        default=SEDE_DEFAULT,
        min_length=1,
        max_length=100,
        description='Sede como texto (default `"Consultorio"`).',
    )
    tipo: TipoMovimiento = Field(description="`ingreso` o `egreso`.")
    concepto: str = Field(
        min_length=1,
        max_length=280,
        description="Texto libre 1–280 (se almacena, jamás se expone — R6).",
    )
    monto: Decimal = Field(
        gt=0, description="Monto positivo en ARS (seña de juguete en tests — R0)."
    )
    metodo: MetodoCaja = Field(description="Catálogo: 4 métodos, otro → `422`.")
    pago_id: uuid.UUID | None = Field(
        default=None,
        description="Pago C-08 atado (opcional; único por movimiento de ingreso).",
    )


class CierreCreate(BaseModel):
    """`POST /caja/cierre`: cierra el día/sede (RN-PA-04)."""

    model_config = ConfigDict(extra="ignore")

    fecha: date = Field(description="Día operativo a cerrar (en `CAJA_TZ`).")
    sede: str = Field(
        default=SEDE_DEFAULT,
        min_length=1,
        max_length=100,
        description='Sede como texto (default `"Consultorio"`).',
    )


class ReaperturaCreate(BaseModel):
    """`POST /caja/reapertura`: revierte un cierre a `abierto` (solo admin)."""

    model_config = ConfigDict(extra="ignore")

    fecha: date = Field(description="Día operativo a reabrir.")
    sede: str = Field(
        default=SEDE_DEFAULT,
        min_length=1,
        max_length=100,
    )
    motivo: str = Field(
        min_length=10,
        max_length=500,
        description="Motivo obligatorio ≥10 (se audita sanitizado — R6).",
    )
