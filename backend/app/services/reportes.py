"""Servicio de reportes operativos C-11 (spec `admin/reportes-operativos`).

- `alcance_reportes()`: scoping único por rol (design decisión 4):
  admin full; odontólogo solo su `profesional_id` propio (cualquier otro
  id → `AlcanceDenegadoError` → `403`); recepción solo el día operativo
  (`desde == hasta == hoy` en zona AR, otro rango → `403`).
- Agregaciones en DB (`COUNT/GROUP BY`, zona `America/Argentina/Buenos_Aires`;
  design decisión 2): ocupación por profesional/sillón sobre turnos
  no-cancelados; ausentismo sobre `presente+atendido+ausente`; ingresos
  desde `movimiento_caja` (neto ingresos−egresos por método) +
  `pago acreditado` (fuente C-08, solo lectura, fecha operativa en `CAJA_TZ`).
- Allowlist de columnas: solo IDs/conteos/montos/estados salen del servicio
  (jamás DNI/teléfonos/nombres/emails/HCE — R6).

Vínculo odontólogo→profesional: el modelo no tiene FK usuario→profesional
(non-goal); `propio` = profesional con el mismo id que el usuario si existe,
si no el primero por id (determinista y documentado). El filtro explícito
distinto del propio → `403` en todos los casos (no se fuga nada ajeno).

Todo dato sintético (R0); type hints siempre (R1).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.models.caja import METODOS_CAJA, SEDE_DEFAULT, MovimientoCaja
from app.models.entidades import Profesional, Sillon, Turno
from app.models.pago import Pago
from app.services.caja import fecha_operativa_de

ESTADOS_FINALIZADOS: tuple[str, ...] = ("presente", "atendido", "ausente")
ESTADO_AUSENTE = "ausente"
ESTADO_CANCELADO = "cancelado"

METODOS_INGRESOS: tuple[str, ...] = tuple(METODOS_CAJA)


class AlcanceDenegadoError(Exception):
    """Scoping por rol violado (→ `403` genérico, sin ejecutar agregación)."""


class RangoInvalidoError(Exception):
    """`hasta` anterior a `desde` (→ `422`, sin efectos)."""


def zona_ar() -> ZoneInfo:
    """Zona operativa AR (acepta el alias con `_` de `CAJA_TZ`)."""
    try:
        return ZoneInfo("America/Argentina/Buenos_Aires")
    except ZoneInfoNotFoundError:  # pragma: no cover - IANA siempre disponible
        alias = settings.caja_tz.replace(
            "Argentina/Buenos_Aires", "Argentina_Buenos_Aires"
        )
        try:
            return ZoneInfo(alias)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")


def hoy_ar() -> date:
    """Hoy calendario en zona AR (día operativo de recepción)."""
    return datetime.now(timezone.utc).astimezone(zona_ar()).date()


def inicio_rango(desde: date) -> datetime:
    return datetime(desde.year, desde.month, desde.day, tzinfo=zona_ar())


def fin_rango(hasta: date) -> datetime:
    siguiente = hasta + timedelta(days=1)
    return datetime(siguiente.year, siguiente.month, siguiente.day, tzinfo=zona_ar())


def _redondear2(valor: Decimal | float) -> float:
    return float(round(Decimal(str(valor)), 2))


def _pct(parte: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return _redondear2(Decimal(parte) * Decimal(100) / Decimal(total))


async def profesional_propio(
    session: AsyncSession, usuario_id: uuid.UUID
) -> uuid.UUID | None:
    """Profesional propio del odontólogo (vínculo documentado arriba)."""
    directo = await session.get(Profesional, usuario_id)
    if directo is not None:
        return directo.id
    primero = (
        await session.execute(select(Profesional.id).order_by(Profesional.id).limit(1))
    ).scalar_one_or_none()
    return primero


async def alcance_profesional(
    session: AsyncSession,
    *,
    rol: str,
    usuario_id: uuid.UUID,
    profesional_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Profesional efectivo o `AlcanceDenegadoError` (odontólogo ajeno → 403)."""
    if rol == "odontologo":
        propio = await profesional_propio(session, usuario_id)
        if propio is None:
            return None
        if profesional_id is not None and profesional_id != propio:
            raise AlcanceDenegadoError("profesional_ajeno")
        return propio
    return profesional_id


def exigir_dia_operativo(*, rol: str, desde: date, hasta: date) -> None:
    """Recepción solo ve el día operativo (hoy AR); otro rango → 403."""
    if rol == "recepcion" and not (desde == hasta == hoy_ar()):
        raise AlcanceDenegadoError("fuera_dia_operativo")


def exigir_rango(desde: date, hasta: date) -> None:
    if hasta < desde:
        raise RangoInvalidoError("rango_invertido")


async def ocupacion(
    session: AsyncSession,
    *,
    desde: date,
    hasta: date,
    profesional_id: uuid.UUID | None = None,
    sillon_id: uuid.UUID | None = None,
    sede: str | None = None,
) -> dict[str, object]:
    """Ocupación por profesional y sillón calculada en DB (solo agregados)."""
    exigir_rango(desde, hasta)
    inicio = inicio_rango(desde)
    fin = fin_rango(hasta)
    activo = Turno.estado != ESTADO_CANCELADO

    consulta_prof = (
        select(
            Turno.profesional_id,
            func.count().label("totales"),
            func.sum(case((activo, 1), else_=0)).label("activos"),
            func.coalesce(
                func.sum(
                    case(
                        (activo, func.extract("epoch", Turno.fin - Turno.inicio)),
                        else_=0,
                    )
                ),
                0,
            ).label("segundos"),
        )
        .where(Turno.inicio >= inicio, Turno.inicio < fin)
        .group_by(Turno.profesional_id)
    )
    consulta_sillon = (
        select(
            Turno.sillon_id,
            func.count().label("totales"),
            func.sum(case((activo, 1), else_=0)).label("activos"),
            func.coalesce(
                func.sum(
                    case(
                        (activo, func.extract("epoch", Turno.fin - Turno.inicio)),
                        else_=0,
                    )
                ),
                0,
            ).label("segundos"),
        )
        .where(Turno.inicio >= inicio, Turno.inicio < fin, Turno.sillon_id.is_not(None))
        .group_by(Turno.sillon_id)
    )
    if profesional_id is not None:
        consulta_prof = consulta_prof.where(Turno.profesional_id == profesional_id)
        consulta_sillon = consulta_sillon.where(Turno.profesional_id == profesional_id)
    if sillon_id is not None:
        consulta_prof = consulta_prof.where(Turno.sillon_id == sillon_id)
        consulta_sillon = consulta_sillon.where(Turno.sillon_id == sillon_id)
    if sede is not None:
        consulta_prof = consulta_prof.join(Sillon, Sillon.id == Turno.sillon_id).where(
            Sillon.sede == sede
        )
        consulta_sillon = consulta_sillon.join(
            Sillon, Sillon.id == Turno.sillon_id
        ).where(Sillon.sede == sede)

    por_profesional: list[dict[str, object]] = []
    for pid, totales, activos, segundos in (await session.execute(consulta_prof)).all():
        totales_n = int(totales or 0)
        activos_n = int(activos or 0)
        por_profesional.append(
            {
                "profesional_id": str(pid),
                "turnos_totales": totales_n,
                "turnos_activos": activos_n,
                "horas_ocupadas": _redondear2(
                    Decimal(str(segundos or 0)) / Decimal(3600)
                ),
                "ocupacion_pct": _pct(activos_n, totales_n),
            }
        )
    por_profesional.sort(key=lambda f: str(f["profesional_id"]))

    por_sillon: list[dict[str, object]] = []
    for sid, totales, activos, segundos in (
        await session.execute(consulta_sillon)
    ).all():
        totales_n = int(totales or 0)
        activos_n = int(activos or 0)
        por_sillon.append(
            {
                "sillon_id": str(sid),
                "turnos_totales": totales_n,
                "turnos_activos": activos_n,
                "horas_ocupadas": _redondear2(
                    Decimal(str(segundos or 0)) / Decimal(3600)
                ),
                "ocupacion_pct": _pct(activos_n, totales_n),
            }
        )
    por_sillon.sort(key=lambda f: str(f["sillon_id"]))
    return {"por_profesional": por_profesional, "por_sillon": por_sillon}


async def ausentismo(
    session: AsyncSession,
    *,
    desde: date,
    hasta: date,
    profesional_id: uuid.UUID | None = None,
    sede: str | None = None,
) -> dict[str, object]:
    """Ausentismo global + por profesional (solo agregados, sin PII)."""
    exigir_rango(desde, hasta)
    inicio = inicio_rango(desde)
    hasta_fin = fin_rango(hasta)

    base = select(Turno).where(
        Turno.inicio >= inicio,
        Turno.inicio < hasta_fin,
        Turno.estado.in_(ESTADOS_FINALIZADOS),
    )
    if profesional_id is not None:
        base = base.where(Turno.profesional_id == profesional_id)
    if sede is not None:
        base = base.join(Sillon, Sillon.id == Turno.sillon_id).where(
            Sillon.sede == sede
        )
    filas = (await session.execute(base)).scalars().all()

    finalizados = len(filas)
    ausentes = sum(1 for t in filas if t.estado == ESTADO_AUSENTE)
    por_prof_map: dict[str, dict[str, int]] = {}
    for turno in filas:
        clave = str(turno.profesional_id)
        grupo = por_prof_map.setdefault(clave, {"finalizados": 0, "ausentes": 0})
        grupo["finalizados"] += 1
        if turno.estado == ESTADO_AUSENTE:
            grupo["ausentes"] += 1
    por_profesional = [
        {
            "profesional_id": clave,
            "turnos_finalizados": grupo["finalizados"],
            "ausentes": grupo["ausentes"],
            "ausentismo_pct": _pct(grupo["ausentes"], grupo["finalizados"]),
        }
        for clave, grupo in sorted(por_prof_map.items())
    ]
    return {
        "turnos_finalizados": finalizados,
        "ausentes": ausentes,
        "ausentismo_pct": _pct(ausentes, finalizados),
        "por_profesional": por_profesional,
    }


async def ingresos(
    session: AsyncSession,
    *,
    desde: date,
    hasta: date,
    sede: str = SEDE_DEFAULT,
    usuario_id: uuid.UUID | None = None,
) -> dict[str, object]:
    """Ingresos por método + conciliación MP (solo montos agregados)."""
    exigir_rango(desde, hasta)
    consulta = select(MovimientoCaja).where(
        MovimientoCaja.fecha >= desde,
        MovimientoCaja.fecha <= hasta,
        MovimientoCaja.sede == sede,
    )
    if usuario_id is not None:
        consulta = consulta.where(MovimientoCaja.usuario_id == usuario_id)
    movimientos = (await session.execute(consulta)).scalars().all()

    netos: dict[str, Decimal] = {m: Decimal(0) for m in METODOS_INGRESOS}
    for mov in movimientos:
        monto = Decimal(mov.monto)
        if mov.tipo == "ingreso":
            netos[mov.metodo] = netos.get(mov.metodo, Decimal(0)) + monto
        else:
            netos[mov.metodo] = netos.get(mov.metodo, Decimal(0)) - monto

    pagos = (
        (await session.execute(select(Pago).where(Pago.estado == "acreditado")))
        .scalars()
        .all()
    )
    acreditado = Decimal(0)
    for pago in pagos:
        operativa = fecha_operativa_de(pago.webhook_recibido_at)
        if operativa is not None and desde <= operativa <= hasta:
            acreditado += Decimal(pago.monto)

    por_metodo = {m: _redondear2(netos.get(m, Decimal(0))) for m in METODOS_INGRESOS}
    total = _redondear2(
        sum((netos.get(m, Decimal(0)) for m in METODOS_INGRESOS), Decimal(0))
    )
    acreditado_f = _redondear2(acreditado)
    diferencia = _redondear2(
        Decimal(str(por_metodo.get("mercadopago", 0.0))) - acreditado
    )
    return {
        "por_metodo": por_metodo,
        "total": total,
        "acreditado_mp": acreditado_f,
        "diferencia": diferencia,
    }
