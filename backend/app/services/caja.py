"""Servicio de caja y cierre diario C-09 (RN-PA-04/05, R0–R8).

- `registrar_movimiento`: valida método/tipo/monto/concepto, bloquea
  día `cerrado` (`SELECT cierre ... FOR UPDATE` → `DiaCerradoError`),
  exige `pago_id` único, audita `movimiento_registrado` sin concepto
  crudo ni PII (R6) y retorna el movimiento con `usuario_id` del JWT.
- `crear_cierre`: en UNA transacción snapshot de totales por método
  (neto ingresos − egresos por método; `total_egresos` informativo),
  `acreditado_mp` desde `pago` (`estado='acreditado'`, fecha operativa
  = `webhook_recibido_at` en `CAJA_TZ`, solo lectura C-08),
  `diferencia = total_mp − acreditado_mp` →
  `cuadrado|con_diferencia`; `UNIQUE(fecha,sede)` → `409` (la DB
  manda, incluso en concurrente) + evento `cierre_creado`.
- `reabrir_cierre`: `cerrado→abierto` + `reaperturas+1` + evento
  `cierre_reabierto` (motivo sanitizado); sin cierre → `404`,
  ya abierto → `422`.
- R6: logs/diffs/responses solo con IDs/montos/métodos/estados;
  el `concepto` libre se almacena pero JAMÁS se loguea, audita ni
  devuelve; el `motivo` se sanitiza (patrones PII) y trunca.

Todo dato sintético (R0); type hints siempre (R1).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger, sanitize
from app.core.settings import settings
from app.models.caja import (
    ESTADOS_CIERRE,  # noqa: F401 (re-export documentado)
    METODOS_CAJA,
    SEDE_DEFAULT,
    TIPOS_MOVIMIENTO,
    CierreDiario,
    MovimientoCaja,
)
from app.models.pago import Pago
from app.repositories import auditoria as repo_auditoria

logger = get_logger(__name__)


class DiaCerradoError(Exception):
    """Movimiento en día `cerrado` (→ `422` con `detalle == "dia_cerrado"`)."""


class MovimientoInvalidoError(Exception):
    """Validación de negocio del movimiento (→ `422` sin efectos)."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


class PagoYaVinculadoError(Exception):
    """`pago_id` ya atado a otro movimiento (→ `422`, sin duplicar)."""


class CierreExistenteError(Exception):
    """Segundo cierre del mismo día/sede (→ `409`, la DB manda)."""


class CierreNoEncontradoError(Exception):
    """Sin cierre para el día/sede (→ `404` `problema: no_encontrado`)."""


class CierreAbiertoError(Exception):
    """Reapertura de un día ya `abierto` (→ `422`, nada que reabrir)."""


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def estado_conciliacion_para(diferencia: Decimal) -> str:
    """`cuadrado` si `diferencia == 0`, si no `con_diferencia`."""
    return "cuadrado" if Decimal(diferencia) == Decimal(0) else "con_diferencia"


def _sede_norm(sede: str | None) -> str:
    texto = (sede or SEDE_DEFAULT).strip()
    if not texto:
        raise MovimientoInvalidoError("sede")
    return texto[:100]


def _caja_tz() -> ZoneInfo:
    """Zona operativa (`CAJA_TZ` con alias `_`→`/` para la IANA real)."""
    try:
        return ZoneInfo(settings.caja_tz)
    except ZoneInfoNotFoundError:
        alias = settings.caja_tz.replace(
            "Argentina_Buenos_Aires", "Argentina/Buenos_Aires"
        )
        try:
            return ZoneInfo(alias)
        except ZoneInfoNotFoundError:
            return ZoneInfo("America/Argentina/Buenos_Aires")


def fecha_operativa_de(marca: datetime | None) -> date | None:
    """Fecha operativa de un pago: `webhook_recibido_at` en `CAJA_TZ`."""
    if marca is None:
        return None
    momento = marca
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(_caja_tz()).date()


def _cuerpo_movimiento(mov: MovimientoCaja) -> dict[str, object]:
    """Serialización sin `concepto` (R6: jamás concepto crudo en responses)."""
    return {
        "id": str(mov.id),
        "fecha": mov.fecha.isoformat(),
        "sede": mov.sede,
        "tipo": mov.tipo,
        "metodo": mov.metodo,
        "monto": f"{Decimal(mov.monto):.2f}",
        "usuario_id": str(mov.usuario_id) if mov.usuario_id else None,
        "pago_id": str(mov.pago_id) if mov.pago_id else None,
        "origen": mov.origen,
    }


def _cuerpo_cierre(cierre: CierreDiario) -> dict[str, object]:
    """Snapshot + `diferencia` + `estado` + conciliación derivada."""
    diferencia = Decimal(cierre.diferencia)
    return {
        "id": str(cierre.id),
        "fecha": cierre.fecha.isoformat(),
        "sede": cierre.sede,
        "total_efectivo": f"{Decimal(cierre.total_efectivo):.2f}",
        "total_transferencia": f"{Decimal(cierre.total_transferencia):.2f}",
        "total_tarjeta": f"{Decimal(cierre.total_tarjeta):.2f}",
        "total_mp": f"{Decimal(cierre.total_mp):.2f}",
        "total_egresos": f"{Decimal(cierre.total_egresos):.2f}",
        "acreditado_mp": f"{Decimal(cierre.acreditado_mp):.2f}",
        "diferencia": f"{diferencia:.2f}",
        "estado": cierre.estado,
        "estado_conciliacion": estado_conciliacion_para(diferencia),
        "reaperturas": cierre.reaperturas,
        "cerrado_por": str(cierre.cerrado_por) if cierre.cerrado_por else None,
        "cerrado_at": cierre.cerrado_at.isoformat() if cierre.cerrado_at else None,
    }


async def registrar_movimiento(
    session: AsyncSession,
    *,
    fecha: date,
    sede: str,
    tipo: str,
    concepto: str,
    monto: Decimal,
    metodo: str,
    usuario_id: UUID,
    pago_id: UUID | None = None,
    ip: str | None = None,
) -> MovimientoCaja:
    """Crea UN movimiento manual (bloquea día `cerrado` en la transacción)."""
    sede_norm = _sede_norm(sede)
    if tipo not in TIPOS_MOVIMIENTO:
        raise MovimientoInvalidoError("tipo")
    if metodo not in METODOS_CAJA:
        raise MovimientoInvalidoError("metodo")
    if Decimal(monto) <= Decimal(0):
        raise MovimientoInvalidoError("monto")
    texto = (concepto or "").strip()
    if not 1 <= len(texto) <= 280:
        raise MovimientoInvalidoError("concepto")
    if pago_id is not None and tipo != "ingreso":
        raise MovimientoInvalidoError("pago_id")

    if pago_id is not None:
        previo = (
            await session.execute(
                select(MovimientoCaja.id).where(MovimientoCaja.pago_id == pago_id)
            )
        ).first()
        if previo is not None:
            raise PagoYaVinculadoError("pago_ya_vinculado")

    cierre = (
        await session.execute(
            select(CierreDiario)
            .where(CierreDiario.fecha == fecha, CierreDiario.sede == sede_norm)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if cierre is not None and cierre.estado == "cerrado":
        logger.info("movimiento bloqueado por día cerrado")
        raise DiaCerradoError("dia_cerrado")

    mov = MovimientoCaja(
        fecha=fecha,
        sede=sede_norm,
        tipo=tipo,
        concepto=texto,
        monto=Decimal(monto),
        metodo=metodo,
        usuario_id=usuario_id,
        pago_id=pago_id,
        origen="manual",
    )
    session.add(mov)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        logger.info("movimiento rechazado por integridad")
        if pago_id is not None:
            raise PagoYaVinculadoError("pago_ya_vinculado") from exc
        raise MovimientoInvalidoError("integridad") from exc

    await repo_auditoria.registrar_auditoria(
        session,
        accion="movimiento_registrado",
        entidad="movimiento_caja",
        entidad_id=str(mov.id),
        diff={
            "movimiento_id": str(mov.id),
            "fecha": fecha.isoformat(),
            "sede": sede_norm,
            "tipo": tipo,
            "metodo": metodo,
            "monto": f"{Decimal(monto):.2f}",
        },
        usuario_id=usuario_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(mov)
    logger.info(
        "movimiento registrado",
        extra={
            "movimiento_id": str(mov.id),
            "fecha": fecha.isoformat(),
            "sede": sede_norm,
            "tipo": tipo,
            "metodo": metodo,
            "monto": f"{Decimal(monto):.2f}",
        },
    )
    return mov


async def listar_movimientos(
    session: AsyncSession, *, fecha: date, sede: str
) -> list[MovimientoCaja]:
    """Movimientos del día/sede para el arqueo (Flujo 6 paso 1, sin concepto)."""
    sede_norm = _sede_norm(sede)
    filas = (
        (
            await session.execute(
                select(MovimientoCaja)
                .where(MovimientoCaja.fecha == fecha, MovimientoCaja.sede == sede_norm)
                .order_by(MovimientoCaja.creado_en)
            )
        )
        .scalars()
        .all()
    )
    return list(filas)


async def _acreditado_mp_dia(session: AsyncSession, dia: date) -> Decimal:
    """Suma `acreditado` con fecha operativa `== dia` (fuente C-08, solo lectura)."""
    filas = (
        await session.execute(
            select(Pago.monto, Pago.webhook_recibido_at).where(
                Pago.estado == "acreditado"
            )
        )
    ).all()
    total = Decimal(0)
    for monto, marca in filas:
        if fecha_operativa_de(marca) == dia:
            total += Decimal(monto)
    return total


async def crear_cierre(
    session: AsyncSession,
    *,
    fecha: date,
    sede: str,
    usuario_id: UUID,
    ip: str | None = None,
) -> CierreDiario:
    """Cierra el día/sede en UNA transacción (snapshot + conciliación)."""
    sede_norm = _sede_norm(sede)
    movimientos = (
        (
            await session.execute(
                select(MovimientoCaja).where(
                    MovimientoCaja.fecha == fecha, MovimientoCaja.sede == sede_norm
                )
            )
        )
        .scalars()
        .all()
    )

    netos: dict[str, Decimal] = {m: Decimal(0) for m in METODOS_CAJA}
    egresos = Decimal(0)
    for mov in movimientos:
        monto = Decimal(mov.monto)
        if mov.tipo == "ingreso":
            netos[mov.metodo] = netos.get(mov.metodo, Decimal(0)) + monto
        else:
            netos[mov.metodo] = netos.get(mov.metodo, Decimal(0)) - monto
            egresos += monto

    acreditado = await _acreditado_mp_dia(session, fecha)
    total_mp = netos.get("mercadopago", Decimal(0))
    diferencia = total_mp - acreditado

    cierre = CierreDiario(
        fecha=fecha,
        sede=sede_norm,
        total_efectivo=netos.get("efectivo", Decimal(0)),
        total_transferencia=netos.get("transferencia", Decimal(0)),
        total_tarjeta=netos.get("tarjeta", Decimal(0)),
        total_mp=total_mp,
        total_egresos=egresos,
        acreditado_mp=acreditado,
        diferencia=diferencia,
        estado="cerrado",
        cerrado_por=usuario_id,
        cerrado_at=ahora_utc(),
        reaperturas=0,
    )
    session.add(cierre)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        logger.info("doble cierre rechazado por UNIQUE")
        raise CierreExistenteError("cierre_existente") from exc

    await repo_auditoria.registrar_auditoria(
        session,
        accion="cierre_creado",
        entidad="cierre_diario",
        entidad_id=str(cierre.id),
        diff={
            "cierre_id": str(cierre.id),
            "fecha": fecha.isoformat(),
            "sede": sede_norm,
            "total_mp": f"{total_mp:.2f}",
            "acreditado_mp": f"{acreditado:.2f}",
            "diferencia": f"{diferencia:.2f}",
            "estado": "cerrado",
            "estado_conciliacion": estado_conciliacion_para(diferencia),
        },
        usuario_id=usuario_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(cierre)
    logger.info(
        "cierre creado",
        extra={
            "cierre_id": str(cierre.id),
            "fecha": fecha.isoformat(),
            "sede": sede_norm,
            "diferencia": f"{diferencia:.2f}",
            "estado": "cerrado",
        },
    )
    return cierre


async def obtener_cierre(
    session: AsyncSession, *, fecha: date, sede: str
) -> CierreDiario | None:
    """Cierre del día/sede o `None` (el router responde `404` de dominio)."""
    sede_norm = _sede_norm(sede)
    return (
        await session.execute(
            select(CierreDiario).where(
                CierreDiario.fecha == fecha, CierreDiario.sede == sede_norm
            )
        )
    ).scalar_one_or_none()


async def reabrir_cierre(
    session: AsyncSession,
    *,
    fecha: date,
    sede: str,
    motivo: str,
    usuario_id: UUID,
    ip: str | None = None,
) -> CierreDiario:
    """Revierte `cerrado→abierto` (`reaperturas+1`) + `cierre_reabierto`."""
    sede_norm = _sede_norm(sede)
    texto = (motivo or "").strip()
    if len(texto) < 10:
        raise MovimientoInvalidoError("motivo")
    motivo_ok = sanitize(texto)[:500]

    cierre = (
        await session.execute(
            select(CierreDiario)
            .where(CierreDiario.fecha == fecha, CierreDiario.sede == sede_norm)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if cierre is None:
        raise CierreNoEncontradoError("cierre")
    if cierre.estado == "abierto":
        raise CierreAbiertoError("ya_abierto")

    cierre.estado = "abierto"
    cierre.reaperturas = int(cierre.reaperturas or 0) + 1
    await session.flush()
    await repo_auditoria.registrar_auditoria(
        session,
        accion="cierre_reabierto",
        entidad="cierre_diario",
        entidad_id=str(cierre.id),
        diff={
            "cierre_id": str(cierre.id),
            "fecha": fecha.isoformat(),
            "sede": sede_norm,
            "motivo": motivo_ok,
            "reaperturas": cierre.reaperturas,
            "estado": "abierto",
        },
        usuario_id=usuario_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(cierre)
    logger.info(
        "cierre reabierto",
        extra={
            "cierre_id": str(cierre.id),
            "fecha": fecha.isoformat(),
            "sede": sede_norm,
            "estado": "abierto",
            "reaperturas": cierre.reaperturas,
        },
    )
    return cierre
