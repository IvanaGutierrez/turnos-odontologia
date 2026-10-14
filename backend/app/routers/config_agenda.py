"""CRUD del catálogo de agenda C-04 (spec `agenda/configuracion-agenda`).

Escritura solo `admin` (recurso `configuracion_agenda`: 403 + auditoría
`acceso_denegado` para el resto, sin mutar nada); lectura para roles con
permiso `turnos`. Altas auditadas sin PII (solo IDs/nombres de catálogo).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.dependencies import require_role
from app.core.exceptions import EntidadNoEncontradaError
from app.models.base import BaseModel
from app.models.disponibilidad import Bloqueo, HorarioProfesional
from app.models.entidades import Prestacion, Profesional, Sillon, Usuario
from app.repositories import auditoria as repo_auditoria
from app.schemas.config import (
    BloqueoCreate,
    BloqueoRead,
    HorarioCreate,
    HorarioRead,
    PrestacionCreate,
    PrestacionRead,
    ProfesionalCreate,
    ProfesionalRead,
    SillonCreate,
    SillonRead,
)

router = APIRouter(tags=["configuracion-agenda"])

EscribeConfig = require_role("configuracion_agenda")
LeeAgenda = require_role("turnos")


async def _auditar_alta(
    session: AsyncSession,
    *,
    tipo: str,
    entidad_id: str,
    diff: dict[str, Any],
    usuario: Usuario,
    ip: str | None,
) -> None:
    await repo_auditoria.registrar_auditoria(
        session,
        accion="configuracion_alta",
        entidad="configuracion",
        entidad_id=entidad_id,
        diff={"tipo": tipo, **diff},
        usuario_id=usuario.id,
        ip=ip,
    )
    await session.commit()


async def _guardar(session: AsyncSession) -> None:
    """Commit con 409 ante duplicados (matrículas/nombres únicos)."""
    try:
        await session.commit()
    except DBAPIError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recurso duplicado o en conflicto.",
        ) from exc


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _obtener_o_404(
    session: AsyncSession, modelo: type[BaseModel], id: uuid.UUID, nombre: str
) -> BaseModel:
    fila = await session.get(modelo, id)
    if fila is None:
        raise EntidadNoEncontradaError(nombre)
    return fila


async def _validar_profesional(
    session: AsyncSession, profesional_id: uuid.UUID | None
) -> None:
    if (
        profesional_id is not None
        and await session.get(Profesional, profesional_id) is None
    ):
        raise EntidadNoEncontradaError("profesional")


async def _validar_sillon(session: AsyncSession, sillon_id: uuid.UUID | None) -> None:
    if sillon_id is not None and await session.get(Sillon, sillon_id) is None:
        raise EntidadNoEncontradaError("sillon")


# --- Profesionales -------------------------------------------------------

profesionales = APIRouter(prefix="/profesionales", tags=["configuracion-agenda"])


@profesionales.get("", response_model=list[ProfesionalRead])
async def listar_profesionales(
    usuario: Annotated[Usuario, Depends(LeeAgenda)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[Profesional]:
    _ = usuario
    filas = (
        (await session.execute(select(Profesional).order_by(Profesional.nombre)))
        .scalars()
        .all()
    )
    return list(filas)


@profesionales.post("", response_model=ProfesionalRead, status_code=201)
async def crear_profesional(
    datos: ProfesionalCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(EscribeConfig)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Profesional:
    fila = Profesional(nombre=datos.nombre, matricula=datos.matricula, activo=True)
    session.add(fila)
    await _guardar(session)
    await session.refresh(fila)
    await _auditar_alta(
        session,
        tipo="profesional",
        entidad_id=str(fila.id),
        diff={"nombre": datos.nombre},
        usuario=usuario,
        ip=_ip(request),
    )
    await session.refresh(fila)
    return fila


@profesionales.get("/{profesional_id}", response_model=ProfesionalRead)
async def ver_profesional(
    profesional_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(LeeAgenda)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Profesional:
    _ = usuario
    fila = await _obtener_o_404(session, Profesional, profesional_id, "profesional")
    assert isinstance(fila, Profesional)
    return fila


@profesionales.put("/{profesional_id}", response_model=ProfesionalRead)
async def actualizar_profesional(
    profesional_id: uuid.UUID,
    datos: ProfesionalCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(EscribeConfig)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Profesional:
    _ = request
    fila = await _obtener_o_404(session, Profesional, profesional_id, "profesional")
    assert isinstance(fila, Profesional)
    fila.nombre, fila.matricula = datos.nombre, datos.matricula
    await _guardar(session)
    await session.refresh(fila)
    return fila


@profesionales.delete("/{profesional_id}")
async def eliminar_profesional(
    profesional_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(EscribeConfig)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    _ = usuario
    fila = await _obtener_o_404(session, Profesional, profesional_id, "profesional")
    await session.delete(fila)
    await _guardar(session)
    return {"id": str(profesional_id)}


# --- Sillones ------------------------------------------------------------

sillones = APIRouter(prefix="/sillones", tags=["configuracion-agenda"])


@sillones.get("", response_model=list[SillonRead])
async def listar_sillones(
    usuario: Annotated[Usuario, Depends(LeeAgenda)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[Sillon]:
    _ = usuario
    filas = (
        (await session.execute(select(Sillon).order_by(Sillon.nombre))).scalars().all()
    )
    return list(filas)


@sillones.post("", response_model=SillonRead, status_code=201)
async def crear_sillon(
    datos: SillonCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(EscribeConfig)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Sillon:
    fila = Sillon(nombre=datos.nombre, sede=datos.sede, activo=True)
    session.add(fila)
    await _guardar(session)
    await session.refresh(fila)
    await _auditar_alta(
        session,
        tipo="sillon",
        entidad_id=str(fila.id),
        diff={"nombre": datos.nombre},
        usuario=usuario,
        ip=_ip(request),
    )
    await session.refresh(fila)
    return fila


@sillones.get("/{sillon_id}", response_model=SillonRead)
async def ver_sillon(
    sillon_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(LeeAgenda)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Sillon:
    _ = usuario
    fila = await _obtener_o_404(session, Sillon, sillon_id, "sillon")
    assert isinstance(fila, Sillon)
    return fila


@sillones.put("/{sillon_id}", response_model=SillonRead)
async def actualizar_sillon(
    sillon_id: uuid.UUID,
    datos: SillonCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(EscribeConfig)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Sillon:
    _ = request
    fila = await _obtener_o_404(session, Sillon, sillon_id, "sillon")
    assert isinstance(fila, Sillon)
    fila.nombre, fila.sede = datos.nombre, datos.sede
    await _guardar(session)
    await session.refresh(fila)
    return fila


@sillones.delete("/{sillon_id}")
async def eliminar_sillon(
    sillon_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(EscribeConfig)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    _ = usuario
    fila = await _obtener_o_404(session, Sillon, sillon_id, "sillon")
    await session.delete(fila)
    await _guardar(session)
    return {"id": str(sillon_id)}


# --- Prestaciones ---------------------------------------------------------

prestaciones = APIRouter(prefix="/prestaciones", tags=["configuracion-agenda"])


@prestaciones.get("", response_model=list[PrestacionRead])
async def listar_prestaciones(
    usuario: Annotated[Usuario, Depends(LeeAgenda)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[Prestacion]:
    _ = usuario
    filas = (
        (await session.execute(select(Prestacion).order_by(Prestacion.nombre)))
        .scalars()
        .all()
    )
    return list(filas)


@prestaciones.post("", response_model=PrestacionRead, status_code=201)
async def crear_prestacion(
    datos: PrestacionCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(EscribeConfig)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Prestacion:
    fila = Prestacion(nombre=datos.nombre, duracion_min=datos.duracion_min)
    session.add(fila)
    await _guardar(session)
    await session.refresh(fila)
    await _auditar_alta(
        session,
        tipo="prestacion",
        entidad_id=str(fila.id),
        diff={"nombre": datos.nombre, "duracion_min": datos.duracion_min},
        usuario=usuario,
        ip=_ip(request),
    )
    await session.refresh(fila)
    return fila


@prestaciones.get("/{prestacion_id}", response_model=PrestacionRead)
async def ver_prestacion(
    prestacion_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(LeeAgenda)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Prestacion:
    _ = usuario
    fila = await _obtener_o_404(session, Prestacion, prestacion_id, "prestacion")
    assert isinstance(fila, Prestacion)
    return fila


@prestaciones.put("/{prestacion_id}", response_model=PrestacionRead)
async def actualizar_prestacion(
    prestacion_id: uuid.UUID,
    datos: PrestacionCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(EscribeConfig)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Prestacion:
    _ = request
    fila = await _obtener_o_404(session, Prestacion, prestacion_id, "prestacion")
    assert isinstance(fila, Prestacion)
    fila.nombre, fila.duracion_min = datos.nombre, datos.duracion_min
    await _guardar(session)
    await session.refresh(fila)
    return fila


@prestaciones.delete("/{prestacion_id}")
async def eliminar_prestacion(
    prestacion_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(EscribeConfig)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    _ = usuario
    fila = await _obtener_o_404(session, Prestacion, prestacion_id, "prestacion")
    await session.delete(fila)
    await _guardar(session)
    return {"id": str(prestacion_id)}


# --- Horarios -------------------------------------------------------------

horarios = APIRouter(prefix="/horarios", tags=["configuracion-agenda"])


@horarios.get("", response_model=list[HorarioRead])
async def listar_horarios(
    usuario: Annotated[Usuario, Depends(LeeAgenda)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[HorarioProfesional]:
    _ = usuario
    filas = (
        (
            await session.execute(
                select(HorarioProfesional).order_by(
                    HorarioProfesional.dia_semana, HorarioProfesional.hora_inicio
                )
            )
        )
        .scalars()
        .all()
    )
    return list(filas)


@horarios.post("", response_model=HorarioRead, status_code=201)
async def crear_horario(
    datos: HorarioCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(EscribeConfig)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HorarioProfesional:
    return await _crear_horario(datos, request, usuario, session)


async def _crear_horario(
    datos: HorarioCreate,
    request: Request,
    usuario: Usuario,
    session: AsyncSession,
) -> HorarioProfesional:
    await _validar_profesional(session, datos.profesional_id)
    fila = HorarioProfesional(
        profesional_id=datos.profesional_id,
        dia_semana=datos.dia_semana,
        hora_inicio=datos.hora_inicio,
        hora_fin=datos.hora_fin,
        vigente_desde=datos.vigente_desde,
        vigente_hasta=datos.vigente_hasta,
        activo=True,
    )
    session.add(fila)
    await _guardar(session)
    await session.refresh(fila)
    await _auditar_alta(
        session,
        tipo="horario",
        entidad_id=str(fila.id),
        diff={"dia_semana": datos.dia_semana},
        usuario=usuario,
        ip=_ip(request),
    )
    await session.refresh(fila)
    return fila


@horarios.get("/{horario_id}", response_model=HorarioRead)
async def ver_horario(
    horario_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(LeeAgenda)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HorarioProfesional:
    _ = usuario
    fila = await _obtener_o_404(session, HorarioProfesional, horario_id, "horario")
    assert isinstance(fila, HorarioProfesional)
    return fila


@horarios.put("/{horario_id}", response_model=HorarioRead)
async def actualizar_horario(
    horario_id: uuid.UUID,
    datos: HorarioCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(EscribeConfig)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HorarioProfesional:
    _ = request
    await _validar_profesional(session, datos.profesional_id)
    fila = await _obtener_o_404(session, HorarioProfesional, horario_id, "horario")
    assert isinstance(fila, HorarioProfesional)
    fila.profesional_id = datos.profesional_id
    fila.dia_semana = datos.dia_semana
    fila.hora_inicio = datos.hora_inicio
    fila.hora_fin = datos.hora_fin
    fila.vigente_desde = datos.vigente_desde
    fila.vigente_hasta = datos.vigente_hasta
    await _guardar(session)
    await session.refresh(fila)
    return fila


@horarios.delete("/{horario_id}")
async def eliminar_horario(
    horario_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(EscribeConfig)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    _ = usuario
    fila = await _obtener_o_404(session, HorarioProfesional, horario_id, "horario")
    await session.delete(fila)
    await _guardar(session)
    return {"id": str(horario_id)}


# --- Bloqueos -------------------------------------------------------------

bloqueos = APIRouter(prefix="/bloqueos", tags=["configuracion-agenda"])


@bloqueos.get("", response_model=list[BloqueoRead])
async def listar_bloqueos(
    usuario: Annotated[Usuario, Depends(LeeAgenda)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[Bloqueo]:
    _ = usuario
    filas = (
        (await session.execute(select(Bloqueo).order_by(Bloqueo.desde))).scalars().all()
    )
    return list(filas)


@bloqueos.post("", response_model=BloqueoRead, status_code=201)
async def crear_bloqueo(
    datos: BloqueoCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(EscribeConfig)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Bloqueo:
    await _validar_profesional(session, datos.profesional_id)
    await _validar_sillon(session, datos.sillon_id)
    fila = Bloqueo(
        profesional_id=datos.profesional_id,
        sillon_id=datos.sillon_id,
        desde=datos.desde,
        hasta=datos.hasta,
        motivo=datos.motivo,
        creado_por=usuario.id,
    )
    session.add(fila)
    await _guardar(session)
    await session.refresh(fila)
    await _auditar_alta(
        session,
        tipo="bloqueo",
        entidad_id=str(fila.id),
        diff={
            "desde": datos.desde.isoformat(),
            "hasta": datos.hasta.isoformat(),
        },
        usuario=usuario,
        ip=_ip(request),
    )
    await session.refresh(fila)
    return fila


@bloqueos.get("/{bloqueo_id}", response_model=BloqueoRead)
async def ver_bloqueo(
    bloqueo_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(LeeAgenda)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Bloqueo:
    _ = usuario
    fila = await _obtener_o_404(session, Bloqueo, bloqueo_id, "bloqueo")
    assert isinstance(fila, Bloqueo)
    return fila


@bloqueos.put("/{bloqueo_id}", response_model=BloqueoRead)
async def actualizar_bloqueo(
    bloqueo_id: uuid.UUID,
    datos: BloqueoCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(EscribeConfig)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Bloqueo:
    _ = request
    await _validar_profesional(session, datos.profesional_id)
    await _validar_sillon(session, datos.sillon_id)
    fila = await _obtener_o_404(session, Bloqueo, bloqueo_id, "bloqueo")
    assert isinstance(fila, Bloqueo)
    fila.profesional_id = datos.profesional_id
    fila.sillon_id = datos.sillon_id
    fila.desde = datos.desde
    fila.hasta = datos.hasta
    fila.motivo = datos.motivo
    await _guardar(session)
    await session.refresh(fila)
    return fila


@bloqueos.delete("/{bloqueo_id}")
async def eliminar_bloqueo(
    bloqueo_id: uuid.UUID,
    usuario: Annotated[Usuario, Depends(EscribeConfig)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    _ = usuario
    fila = await _obtener_o_404(session, Bloqueo, bloqueo_id, "bloqueo")
    await session.delete(fila)
    await _guardar(session)
    return {"id": str(bloqueo_id)}


router.include_router(profesionales)
router.include_router(sillones)
router.include_router(prestaciones)
router.include_router(horarios)
router.include_router(bloqueos)
