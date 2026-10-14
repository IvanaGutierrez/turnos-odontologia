"""Operación de recepción C-04 (spec `agenda/agenda-recepcion`).

Grilla día/semana agregada + máquina mínima (confirmar, check-in,
reprogramar por enlace) + sobreturno dedicado auditado. R3: el camino
normal mantiene pre-chequeo (que cuenta sobreturnos como ocupantes) + GiST
como última línea; el sobreturno solo entra por `crear_sobreturno` con
permiso fino y motivo obligatorio. R6: diffs solo con IDs/horarios/estados.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    EntidadNoEncontradaError,
    SlotOcupadoError,
    SobreturnoNoPermitidoError,
    TransicionInvalidaError,
    VentanaAgendaError,
)
from app.core.logger import get_logger
from app.core.settings import settings
from app.models.entidades import Paciente, Turno
from app.repositories import agenda as repo
from app.repositories import auditoria as repo_auditoria
from app.schemas.turno import (
    ESTADO_ALIAS_LECTURA,
    AgendaItem,
    SobreturnoCreate,
)
from app.services.avisos import tras_cancelar, tras_confirmar, tras_reprogramar
from app.services.crear_turno import (
    PROBLEMA_PROFESIONAL_OCUPADO,
    PROBLEMA_SILLON_OCUPADO,
    calcular_alternativos,
    calcular_fin,
)

logger = get_logger(__name__)

BA = ZoneInfo("America/Argentina/Buenos_Aires")

# Máquina mínima C-04 (design decisión 2; C-05 es dueña de la completa).
CONFIRMABLE_DESDE: frozenset[str] = frozenset({"reservado"})
CHECKIN_DESDE: frozenset[str] = frozenset({"reservado", "confirmado"})
REPROGRAMABLE_DESDE: frozenset[str] = frozenset({"reservado", "confirmado"})

# Roles con permiso fino de sobreturno (design decisión 6: dentro del
# servicio, no en la matriz — `odontologo` tiene `turnos` pero no este).
ROLES_SOBRETURNO: frozenset[str] = frozenset({"recepcion", "admin"})


def _normalizar_estado(estado: str) -> str:
    """`en_sala` → `presente` (alias transitorio solo de lectura)."""
    return ESTADO_ALIAS_LECTURA.get(estado, estado)


async def obtener_grilla(
    session: AsyncSession,
    *,
    vista: str,
    profesional_id: UUID | None = None,
    sillon_id: UUID | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
) -> list[AgendaItem]:
    """Grilla agregada en una query (design decisión 4, R6 minimizada)."""
    if vista == "dia":
        base = desde if desde is not None else datetime.now(BA)
        if base.tzinfo is None:  # naive → se asume hora AR (el server puede ser UTC)
            base = base.replace(tzinfo=BA)
        base = base.astimezone(BA)
        inicio_dia = base.replace(hour=0, minute=0, second=0, microsecond=0)
        ventana_desde, ventana_hasta = inicio_dia, inicio_dia + timedelta(days=1)
    elif vista == "semana":
        if desde is None or hasta is None:
            raise VentanaAgendaError("semana exige `desde` y `hasta`")
        if desde.tzinfo is None:
            desde = desde.replace(tzinfo=BA)
        if hasta.tzinfo is None:
            hasta = hasta.replace(tzinfo=BA)
        if desde >= hasta:
            raise VentanaAgendaError("`desde` debe ser anterior a `hasta`")
        if hasta - desde > timedelta(days=settings.agenda_semana_max_dias):
            raise VentanaAgendaError("ventana mayor al máximo configurable")
        ventana_desde, ventana_hasta = desde, hasta
    else:
        raise VentanaAgendaError("vista inválida (dia|semana)")

    turnos = await repo.listar_turnos_rango(
        session,
        desde=ventana_desde,
        hasta=ventana_hasta,
        profesional_id=profesional_id,
        sillon_id=sillon_id,
        limite=settings.agenda_grilla_max_items,
    )
    logger.info(
        "grilla consultada",
        extra={"vista": vista, "cantidad": len(turnos)},
    )
    return [
        AgendaItem(
            id=t.id,
            inicio=t.inicio,
            fin=t.fin,
            estado=_normalizar_estado(t.estado),
            profesional_id=t.profesional_id,
            sillon_id=t.sillon_id,
            prestacion_id=t.prestacion_id,
            sobreturno=bool(t.sobreturno),
            paciente_nombre=t.paciente.nombre if t.paciente is not None else None,
            canal=t.canal,
        )
        for t in turnos
    ]


async def _turno_existente(session: AsyncSession, turno_id: UUID) -> Turno:
    turno = await repo.obtener_turno_por_id(session, turno_id)
    if turno is None:
        raise EntidadNoEncontradaError("turno")
    return turno


async def confirmar_turno(
    session: AsyncSession,
    turno_id: UUID,
    *,
    usuario_id: UUID | None = None,
    ip: str | None = None,
) -> Turno:
    """`reservado→confirmado` (+ auditoría `turno_confirmado`, sin PII)."""
    turno = await _turno_existente(session, turno_id)
    if turno.estado not in CONFIRMABLE_DESDE:
        raise TransicionInvalidaError("confirmar", turno.estado)
    anterior = turno.estado
    turno.estado = "confirmado"
    await session.commit()
    await session.refresh(turno)
    await repo_auditoria.registrar_auditoria(
        session,
        accion="turno_confirmado",
        entidad="turno",
        entidad_id=str(turno.id),
        diff={"estado_anterior": anterior, "estado_nuevo": "confirmado"},
        usuario_id=usuario_id,
        ip=ip,
    )
    await session.commit()
    # C-06: programa confirmación + 24 h + 3 h (fresco: el commit expiró).
    fresco = await _turno_existente(session, turno_id)
    assert fresco is not None
    await tras_confirmar(session, fresco)
    await session.refresh(fresco)
    return fresco


async def registrar_checkin(
    session: AsyncSession,
    turno_id: UUID,
    *,
    usuario_id: UUID | None = None,
    ip: str | None = None,
) -> Turno:
    """Check-in a `presente` (canónico; solo desde `reservado|confirmado`)."""
    turno = await _turno_existente(session, turno_id)
    if turno.estado not in CHECKIN_DESDE:
        raise TransicionInvalidaError("check-in", turno.estado)
    anterior = turno.estado
    turno.estado = "presente"
    await session.commit()
    await session.refresh(turno)
    await repo_auditoria.registrar_auditoria(
        session,
        accion="turno_presente",
        entidad="turno",
        entidad_id=str(turno.id),
        diff={"estado_anterior": anterior, "estado_nuevo": "presente"},
        usuario_id=usuario_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(turno)
    # C-06: en sala ya no necesita recordatorios (idempotente).
    await tras_cancelar(session, turno_id=turno_id, motivo="presente")
    await session.refresh(turno)
    return turno


async def reprogramar_turno(
    session: AsyncSession,
    turno_id: UUID,
    *,
    nuevo_inicio: datetime,
    motivo_override: str | None = None,
    usuario_id: UUID | None = None,
    ip: str | None = None,
) -> Turno:
    """Reprogramación por enlace (RN-AG-07, design decisión 3).

    Destino libre → original a `reprogramado` + turno nuevo con idéntico
    `token_publico` y `reprogramado_de_id` al original. Destino ocupado →
    409 + alternativos sin mutar nada.
    """
    original = await _turno_existente(session, turno_id)
    if original.estado not in REPROGRAMABLE_DESDE:
        raise TransicionInvalidaError("reprogramar", original.estado)
    original_id: UUID = original.id

    # Plano antes de mutar (tras commits/rollbacks los atributos expiran).
    prestacion_id = original.prestacion_id
    prestacion = await repo.obtener_prestacion(session, prestacion_id)
    if prestacion is None:
        raise EntidadNoEncontradaError("prestacion")
    duracion_min: int = prestacion.duracion_min
    nuevo_fin = calcular_fin(nuevo_inicio, duracion_min)
    profesional_id = original.profesional_id
    sillon_id = original.sillon_id
    paciente_id = original.paciente_id
    canal = original.canal
    token = str(original.token_publico)
    estado_previo = str(original.estado)
    inicio_anterior = original.inicio

    if await repo.existe_solape_profesional(
        session,
        profesional_id,
        nuevo_inicio,
        nuevo_fin,
        excluir_turno_id=original.id,
    ):
        alternativos = await calcular_alternativos(
            session,
            inicio=nuevo_inicio,
            duracion_min=duracion_min,
            profesional_id=profesional_id,
            sillon_id=sillon_id,
            problema=PROBLEMA_PROFESIONAL_OCUPADO,
        )
        raise SlotOcupadoError(PROBLEMA_PROFESIONAL_OCUPADO, alternativos)
    if sillon_id is not None and await repo.existe_solape_sillon(
        session,
        sillon_id,
        nuevo_inicio,
        nuevo_fin,
        excluir_turno_id=original.id,
    ):
        alternativos = await calcular_alternativos(
            session,
            inicio=nuevo_inicio,
            duracion_min=duracion_min,
            profesional_id=profesional_id,
            sillon_id=sillon_id,
            problema=PROBLEMA_SILLON_OCUPADO,
        )
        raise SlotOcupadoError(PROBLEMA_SILLON_OCUPADO, alternativos)

    original.estado = "reprogramado"
    await session.flush()
    nuevo = Turno(
        paciente_id=paciente_id,
        profesional_id=profesional_id,
        sillon_id=sillon_id,
        prestacion_id=prestacion_id,
        inicio=nuevo_inicio,
        fin=nuevo_fin,
        estado=estado_previo,
        canal=canal,
        token_publico=token,
        motivo_override=(
            motivo_override if motivo_override is not None else original.motivo_override
        ),
        sobreturno=False,
        reprogramado_de_id=original.id,
    )
    session.add(nuevo)
    try:
        await session.commit()
    except DBAPIError as exc:
        # Carrera (doble reprogramación): la DB mandó; sin mutar de más.
        await session.rollback()
        raise SlotOcupadoError(
            PROBLEMA_PROFESIONAL_OCUPADO,
            await calcular_alternativos(
                session,
                inicio=nuevo_inicio,
                duracion_min=duracion_min,
                profesional_id=profesional_id,
                sillon_id=sillon_id,
                problema=PROBLEMA_PROFESIONAL_OCUPADO,
            ),
        ) from exc
    await session.refresh(nuevo)
    await repo_auditoria.registrar_auditoria(
        session,
        accion="turno_reprogramado",
        entidad="turno",
        entidad_id=str(nuevo.id),
        diff={
            "turno_original_id": str(original.id),
            "inicio_anterior": inicio_anterior.isoformat(),
            "inicio_nuevo": nuevo_inicio.isoformat(),
            "fin_nuevo": nuevo_fin.isoformat(),
            "estado_original": "reprogramado",
        },
        usuario_id=usuario_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(nuevo)
    # C-06: cancela pendientes del viejo y programa el nuevo (staff y
    # autogestión comparten este núcleo; fresco porque el commit expiró).
    nuevo_id: UUID = nuevo.id
    fresco = await _turno_existente(session, nuevo_id)
    assert fresco is not None
    await tras_reprogramar(session, original_id=original_id, nuevo=fresco)
    await session.refresh(fresco)
    return fresco


async def crear_sobreturno(
    session: AsyncSession,
    datos: SobreturnoCreate,
    *,
    usuario_rol: str,
    usuario_id: UUID | None = None,
    ip: str | None = None,
) -> Turno:
    """Sobreturno explícito (bypass GiST a nivel aplicación, R3).

    Solo `recepcion`/`admin` con motivo no vacío; cualquier otro rol →
    403 + `acceso_denegado` auditado, sin crear nada.
    """
    if usuario_rol not in ROLES_SOBRETURNO:
        await repo_auditoria.registrar_auditoria(
            session,
            accion="acceso_denegado",
            entidad="sobreturno",
            entidad_id=None,
            diff={"recurso": "sobreturno"},
            usuario_id=usuario_id,
            ip=ip,
        )
        await session.commit()
        raise SobreturnoNoPermitidoError()

    prestacion = await repo.obtener_prestacion(session, datos.prestacion_id)
    if prestacion is None:
        raise EntidadNoEncontradaError("prestacion")
    profesional = await repo.obtener_profesional(session, datos.profesional_id)
    if profesional is None:
        raise EntidadNoEncontradaError("profesional")
    if datos.sillon_id is not None:
        sillon = await repo.obtener_sillon(session, datos.sillon_id)
        if sillon is None:
            raise EntidadNoEncontradaError("sillon")

    if datos.paciente_id is not None:
        paciente = await repo.obtener_paciente(session, datos.paciente_id)
        if paciente is None:
            raise EntidadNoEncontradaError("paciente")
    else:
        assert datos.paciente is not None
        paciente = Paciente(
            nombre=datos.paciente.nombre,
            dni=datos.paciente.dni,
            telefono=datos.paciente.telefono,
            consentimiento_hc=datos.paciente.consentimiento_hc,
        )
        session.add(paciente)
        await session.flush()

    duracion_min: int = prestacion.duracion_min
    fin = calcular_fin(datos.inicio, duracion_min)
    assert datos.motivo_sobreturno is not None  # validado en el schema
    turno = Turno(
        paciente_id=paciente.id,
        profesional_id=datos.profesional_id,
        sillon_id=datos.sillon_id,
        prestacion_id=datos.prestacion_id,
        inicio=datos.inicio,
        fin=fin,
        estado="reservado",
        canal=datos.canal,
        token_publico=secrets.token_urlsafe(32),
        motivo_override=datos.motivo_override,
        sobreturno=True,
        motivo_sobreturno=datos.motivo_sobreturno,
    )
    session.add(turno)
    try:
        await session.commit()
    except DBAPIError:
        await session.rollback()
        raise
    await session.refresh(turno)
    await repo_auditoria.registrar_auditoria(
        session,
        accion="sobreturno_creado",
        entidad="turno",
        entidad_id=str(turno.id),
        diff={
            "profesional_id": str(datos.profesional_id),
            "sillon_id": str(datos.sillon_id) if datos.sillon_id else None,
            "prestacion_id": str(datos.prestacion_id),
            "inicio": datos.inicio.isoformat(),
            "fin": fin.isoformat(),
            "motivo_sobreturno": datos.motivo_sobreturno,
        },
        usuario_id=usuario_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(turno)
    return turno
