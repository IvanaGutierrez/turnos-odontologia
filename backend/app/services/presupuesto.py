"""Servicio de presupuestos/planes C-07 (RN-CL-03 + máquina de estados).

Nace de hallazgos con total calculado en servicio; `borrador→aprobado`
exige `firma_paciente` (registro firma+fecha); plan con `sena_requerida >
0` sin firma → 422; `borrador→pagado` directo y salidas desde `rechazado`
→ 422. Presupuesto inmutable post-firma (cambiar exige nueva versión —
aquí se bloquea edición tras firma; nueva versión es deuda documentada).
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.models.clinica import Ficha, PlanTratamiento, Presupuesto, PresupuestoItem
from app.repositories import auditoria as repo_auditoria
from app.schemas.clinica import HallazgoIn

logger = get_logger(__name__)

ESTADO_BORRADOR = "borrador"
ESTADO_APROBADO = "aprobado"
ESTADO_RECHAZADO = "rechazado"


class PresupuestoError(Exception):
    """Transición o guarda inválida (el router responde 422, estado intacto)."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


class PresupuestoNoEncontradoError(Exception):
    pass


def ahora() -> datetime:
    return datetime.now(timezone.utc)


async def _presupuesto(session: AsyncSession, pid: UUID) -> Presupuesto:
    fila = await session.get(Presupuesto, pid)
    if fila is None:
        raise PresupuestoNoEncontradoError("presupuesto")
    return fila


async def crear_desde_hallazgos(
    session: AsyncSession,
    *,
    ficha_id: UUID,
    hallazgos: list[HallazgoIn],
    firmante_id: UUID,
    firmante_rol: str,
    ip: str | None = None,
) -> tuple[Presupuesto, list[PresupuestoItem]]:
    """`POST /presupuestos` → `201 borrador` con total calculado en servicio."""
    ficha = await session.get(Ficha, ficha_id)
    if ficha is None:
        raise PresupuestoNoEncontradoError("ficha")
    total = sum((h.precio_unitario * h.cantidad for h in hallazgos), Decimal(0))
    presupuesto = Presupuesto(
        ficha_id=ficha.id,
        estado=ESTADO_BORRADOR,
        total=total,
        moneda="ARS",
        sena_requerida=Decimal(0),
        version=1,
    )
    session.add(presupuesto)
    await session.flush()
    items: list[PresupuestoItem] = []
    for h in hallazgos:
        item = PresupuestoItem(
            presupuesto_id=presupuesto.id,
            pieza_fdi=h.pieza_fdi,
            estado_codigo=h.estado_codigo,
            cantidad=h.cantidad,
            precio_unitario=h.precio_unitario,
        )
        session.add(item)
        items.append(item)
    await session.flush()
    await repo_auditoria.registrar_auditoria(
        session,
        accion="presupuesto_creado",
        entidad="presupuesto",
        entidad_id=str(presupuesto.id),
        diff={"ficha_id": str(ficha.id), "firmante_rol": firmante_rol},
        usuario_id=firmante_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(presupuesto)
    for it in items:
        await session.refresh(it)
    logger.info("presupuesto creado")
    return presupuesto, items


async def registrar_firma(
    session: AsyncSession,
    pid: UUID,
    *,
    firma: str,
    fecha: date,
    firmante_id: UUID,
    ip: str | None = None,
) -> Presupuesto:
    """`POST …/firma`: registro firma+fecha + hash (sin contenido clínico)."""
    presupuesto = await _presupuesto(session, pid)
    if presupuesto.estado != ESTADO_BORRADOR:
        raise PresupuestoError("firma_solo_borrador")
    marca = datetime(fecha.year, fecha.month, fecha.day, tzinfo=timezone.utc)
    presupuesto.firma_paciente_en = marca
    presupuesto.firma_hash = hashlib.sha256(firma.encode("utf-8")).hexdigest()[:32]
    await session.flush()
    await repo_auditoria.registrar_auditoria(
        session,
        accion="firma_paciente",
        entidad="presupuesto",
        entidad_id=str(presupuesto.id),
        diff={"presupuesto_id": str(presupuesto.id)},
        usuario_id=firmante_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(presupuesto)
    logger.info("firma registrada")
    return presupuesto


async def aprobar(
    session: AsyncSession, pid: UUID, *, firmante_id: UUID, ip: str | None = None
) -> Presupuesto:
    """`borrador→aprobado` solo con firma; sin firma → 422 (sigue borrador)."""
    presupuesto = await _presupuesto(session, pid)
    if presupuesto.estado != ESTADO_BORRADOR:
        raise PresupuestoError("transicion_invalida")
    if presupuesto.firma_paciente_en is None:
        raise PresupuestoError("firma_requerida")
    presupuesto.estado = ESTADO_APROBADO
    await session.flush()
    await repo_auditoria.registrar_auditoria(
        session,
        accion="presupuesto_aprobado",
        entidad="presupuesto",
        entidad_id=str(presupuesto.id),
        diff={"presupuesto_id": str(presupuesto.id), "estado_nuevo": ESTADO_APROBADO},
        usuario_id=firmante_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(presupuesto)
    logger.info("presupuesto aprobado")
    return presupuesto


async def rechazar(
    session: AsyncSession,
    pid: UUID,
    *,
    motivo: str,
    firmante_id: UUID,
    ip: str | None = None,
) -> Presupuesto:
    """`borrador→rechazado` terminal con motivo (sin PII en el diff)."""
    presupuesto = await _presupuesto(session, pid)
    if presupuesto.estado != ESTADO_BORRADOR:
        raise PresupuestoError("transicion_invalida")
    presupuesto.estado = ESTADO_RECHAZADO
    presupuesto.motivo_rechazo = motivo
    await session.flush()
    await repo_auditoria.registrar_auditoria(
        session,
        accion="presupuesto_rechazado",
        entidad="presupuesto",
        entidad_id=str(presupuesto.id),
        diff={"presupuesto_id": str(presupuesto.id), "estado_nuevo": ESTADO_RECHAZADO},
        usuario_id=firmante_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(presupuesto)
    logger.info("presupuesto rechazado")
    return presupuesto


async def transicion(
    session: AsyncSession,
    pid: UUID,
    *,
    destino: str,
    firmante_id: UUID,
    ip: str | None = None,
) -> Presupuesto:
    """Vía genérica: solo `borrador→rechazado` vía motivo queda fuera.

    Reglas: `borrador→pagado(_parcial)` directo → 422 (solo vía C-08);
    salidas desde `rechazado|aprobado` → 422; `borrador→aprobado` exige
    firma (delega en `aprobar`). Destinos fuera de catálogo → 422.
    """
    presupuesto = await _presupuesto(session, pid)
    if destino not in {"borrador", "aprobado", "pagado_parcial", "pagado", "rechazado"}:
        raise PresupuestoError("transicion_invalida")
    if presupuesto.estado == ESTADO_RECHAZADO:
        raise PresupuestoError("transicion_invalida")
    if destino in {"pagado", "pagado_parcial"}:
        raise PresupuestoError("transicion_invalida")
    if destino == ESTADO_APROBADO:
        return await aprobar(session, pid, firmante_id=firmante_id, ip=ip)
    raise PresupuestoError("transicion_invalida")


async def crear_plan(
    session: AsyncSession,
    *,
    presupuesto_id: UUID,
    etapas: list[dict[str, object]],
    sena_requerida: Decimal,
    firmante_id: UUID,
    ip: str | None = None,
) -> PlanTratamiento:
    """`POST /planes`: con `sena_requerida > 0` exige firma previa (RN-CL-03)."""
    presupuesto = await _presupuesto(session, presupuesto_id)
    if sena_requerida > 0 and presupuesto.firma_paciente_en is None:
        raise PresupuestoError("firma_requerida")
    existente = (
        (
            await session.execute(
                select(PlanTratamiento).where(
                    PlanTratamiento.presupuesto_id == presupuesto.id
                )
            )
        )
        .scalars()
        .first()
    )
    if existente is not None:
        return existente
    plan = PlanTratamiento(
        presupuesto_id=presupuesto.id,
        etapas=list(etapas),
        estado="planificado",
        sena_requerida=sena_requerida,
    )
    session.add(plan)
    await session.flush()
    await repo_auditoria.registrar_auditoria(
        session,
        accion="plan_creado",
        entidad="plan_tratamiento",
        entidad_id=str(plan.id),
        diff={"presupuesto_id": str(presupuesto.id)},
        usuario_id=firmante_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(plan)
    logger.info("plan creado")
    return plan
