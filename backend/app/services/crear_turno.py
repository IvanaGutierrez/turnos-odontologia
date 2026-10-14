"""Servicio `crear_turno` (RN-AG-01/02/03, R3: la DB manda).

Doble defensa: chequeo aplicativo previo (409 rápido con alternativos) +
constraint de exclusión como última línea. Si la DB rechaza la inserción
concurrente, se re-consulta para clasificar el 409 con prioridad
determinista (`profesional_ocupado` antes que `sillon_ocupado`) y se
devuelven alternativos de igual duración. Nunca se expone PII (R6).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntidadNoEncontradaError, SlotOcupadoError
from app.core.settings import settings
from app.models.entidades import Paciente, Turno
from app.repositories import agenda as repo
from app.repositories import auditoria as repo_auditoria
from app.schemas.turno import TurnoCreate

PASO_ALTERNATIVOS_MIN = 15

PROBLEMA_PROFESIONAL_OCUPADO = "profesional_ocupado"
PROBLEMA_SILLON_OCUPADO = "sillon_ocupado"


def calcular_fin(inicio: datetime, duracion_min: int) -> datetime:
    """`fin = inicio + prestacion.duracion_min` (el `fin` del cliente se ignora)."""
    return inicio + timedelta(minutes=duracion_min)


def _offsets_ordenados(antes_min: int, despues_min: int) -> list[int]:
    """Offsets en pasos de 15' ordenados por cercanía (empate: futuro primero)."""
    pasos = [
        d for d in range(-antes_min, despues_min + 1, PASO_ALTERNATIVOS_MIN) if d != 0
    ]
    return sorted(pasos, key=lambda d: (abs(d), -d))


async def calcular_alternativos(
    session: AsyncSession,
    *,
    inicio: datetime,
    duracion_min: int,
    profesional_id: UUID,
    sillon_id: UUID | None,
    problema: str,
) -> list[dict[str, str]]:
    """Slots libres de igual duración sobre el recurso en conflicto."""
    alternativos: list[dict[str, str]] = []
    for delta in _offsets_ordenados(
        settings.slot_minutes_before, settings.slot_minutes_after
    ):
        cand_inicio = inicio + timedelta(minutes=delta)
        cand_fin = cand_inicio + timedelta(minutes=duracion_min)
        if problema == PROBLEMA_SILLON_OCUPADO:
            assert sillon_id is not None  # el problema lo implica
            ocupado = await repo.existe_solape_sillon(
                session, sillon_id, cand_inicio, cand_fin
            )
        else:
            ocupado = await repo.existe_solape_profesional(
                session, profesional_id, cand_inicio, cand_fin
            )
        if not ocupado:
            alternativos.append(
                {"inicio": cand_inicio.isoformat(), "fin": cand_fin.isoformat()}
            )
            if len(alternativos) >= settings.slot_limit:
                break
    return alternativos


async def crear_turno(
    session: AsyncSession,
    datos: TurnoCreate,
    *,
    usuario_id: UUID | None = None,
    ip: str | None = None,
) -> Turno:
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
        assert datos.paciente is not None  # Pydantic exige `paciente` xor `paciente_id`
        paciente = Paciente(
            nombre=datos.paciente.nombre,
            dni=datos.paciente.dni,
            telefono=datos.paciente.telefono,
            consentimiento_hc=datos.paciente.consentimiento_hc,
        )
        session.add(paciente)
        await session.flush()

    # int plano ANTES del commit: tras un rollback los atributos ORM expiran
    # y no pueden leerse sin refresh (sesión en recuperación).
    duracion_min: int = prestacion.duracion_min
    fin = calcular_fin(datos.inicio, duracion_min)

    if await repo.existe_solape_profesional(
        session, datos.profesional_id, datos.inicio, fin
    ):
        alternativos = await calcular_alternativos(
            session,
            inicio=datos.inicio,
            duracion_min=duracion_min,
            profesional_id=datos.profesional_id,
            sillon_id=datos.sillon_id,
            problema=PROBLEMA_PROFESIONAL_OCUPADO,
        )
        raise SlotOcupadoError(PROBLEMA_PROFESIONAL_OCUPADO, alternativos)
    if datos.sillon_id is not None and await repo.existe_solape_sillon(
        session, datos.sillon_id, datos.inicio, fin
    ):
        alternativos = await calcular_alternativos(
            session,
            inicio=datos.inicio,
            duracion_min=duracion_min,
            profesional_id=datos.profesional_id,
            sillon_id=datos.sillon_id,
            problema=PROBLEMA_SILLON_OCUPADO,
        )
        raise SlotOcupadoError(PROBLEMA_SILLON_OCUPADO, alternativos)

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
    )
    session.add(turno)
    try:
        await session.commit()
    except DBAPIError as exc:
        # Carrera concurrente: la DB mandó (`ExclusionViolation` o `deadlock`
        # por la contienda en el gist — ambos evidencian colisión real).
        # Re-clasificar con prioridad determinista (profesional, luego sillón).
        await session.rollback()
        if await repo.existe_solape_profesional(
            session, datos.profesional_id, datos.inicio, fin
        ):
            problema = PROBLEMA_PROFESIONAL_OCUPADO
        elif datos.sillon_id is not None and await repo.existe_solape_sillon(
            session, datos.sillon_id, datos.inicio, fin
        ):
            problema = PROBLEMA_SILLON_OCUPADO
        else:
            raise
        alternativos = await calcular_alternativos(
            session,
            inicio=datos.inicio,
            duracion_min=duracion_min,
            profesional_id=datos.profesional_id,
            sillon_id=datos.sillon_id,
            problema=problema,
        )
        raise SlotOcupadoError(problema, alternativos) from exc
    await session.refresh(turno)
    # RN-AU-03: la creación queda auditada; el diff lleva solo IDs/horarios
    # (jamás DNI, teléfonos ni HC — además `sanitizar_diff` lo garantiza, R6).
    await repo_auditoria.registrar_auditoria(
        session,
        accion="turno_creado",
        entidad="turno",
        entidad_id=str(turno.id),
        diff={
            "profesional_id": str(datos.profesional_id),
            "sillon_id": str(datos.sillon_id) if datos.sillon_id else None,
            "prestacion_id": str(datos.prestacion_id),
            "inicio": datos.inicio.isoformat(),
            "fin": fin.isoformat(),
            "estado": "reservado",
            "canal": datos.canal,
        },
        usuario_id=usuario_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(turno)
    return turno
