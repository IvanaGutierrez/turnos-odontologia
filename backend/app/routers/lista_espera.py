"""Router de lista de espera inteligente (C-14).

RBAC: la guarda de rol es una dependencia (`_escritura` / `_lectura`)
y FastAPI la resuelve ANTES de validar el body — un odontólogo que
intenta escribir recibe `403` + `acceso_denegado` aunque el payload
fuese inválido (nunca `422` por permiso). Sin JWT → `401` (R6).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.dependencies import (
    DETALLE_SIN_PERMISO,
    get_current_user,
)
from app.models.entidades import Usuario
from app.models.lista_espera import ListaEspera
from app.repositories import auditoria as repo_auditoria
from app.services.lista_espera import (
    crear_entrada_lista_espera,
    dar_de_baja_lista_espera,
)
from app.core.exceptions import EntidadNoEncontradaError

router = APIRouter(prefix="/lista-espera", tags=["lista-espera"])

_ROLES_ESCRITURA: frozenset[str] = frozenset({"admin", "recepcion"})
_ROLES_LECTURA: frozenset[str] = frozenset({"admin", "recepcion", "odontologo"})


class ListaEsperaAlta(BaseModel):
    """Alta de espera: ventana futura válida (R1: sin `Any` en el borde)."""

    model_config = ConfigDict(extra="forbid")

    paciente_id: uuid.UUID
    prestacion_id: uuid.UUID
    profesional_id: uuid.UUID | None = None
    ventana_desde: datetime
    ventana_hasta: datetime


def _ip(request: Request) -> str | None:
    if request.client is not None:
        return str(request.client.host)
    return None


async def _escritura(
    request: Request,
    usuario: Annotated[Usuario, Depends(get_current_user)],
    sesion: Annotated[AsyncSession, Depends(get_session)],
) -> Usuario:
    """Guarda de escritura: `admin|recepcion` o `403` + `acceso_denegado`."""
    if usuario.rol not in _ROLES_ESCRITURA:
        await repo_auditoria.registrar_auditoria(
            sesion,
            accion="acceso_denegado",
            entidad="lista_espera",
            entidad_id=None,
            diff={"recurso": "lista_espera"},
            usuario_id=usuario.id,
            ip=_ip(request),
        )
        await sesion.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DETALLE_SIN_PERMISO,
        )
    return usuario


async def _lectura(
    request: Request,
    usuario: Annotated[Usuario, Depends(get_current_user)],
    sesion: Annotated[AsyncSession, Depends(get_session)],
) -> Usuario:
    """Guarda de lectura: staff + odontólogo o `403` + `acceso_denegado`."""
    if usuario.rol not in _ROLES_LECTURA:
        await repo_auditoria.registrar_auditoria(
            sesion,
            accion="acceso_denegado",
            entidad="lista_espera",
            entidad_id=None,
            diff={"recurso": "lista_espera"},
            usuario_id=usuario.id,
            ip=_ip(request),
        )
        await sesion.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DETALLE_SIN_PERMISO,
        )
    return usuario


def _resumen(entrada: ListaEspera) -> dict[str, Any]:
    """Vista mínima sin PII (R6: solo IDs, estado y score)."""
    return {
        "id": str(entrada.id),
        "paciente_id": str(entrada.paciente_id),
        "prestacion_id": str(entrada.prestacion_id),
        "estado": entrada.estado,
        "score": float(entrada.score or 0.0),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def crear_lista_espera(
    payload: ListaEsperaAlta,
    sesion: AsyncSession = Depends(get_session),
    usuario: Usuario = Depends(_escritura),
) -> dict[str, Any]:
    entrada = await crear_entrada_lista_espera(
        sesion,
        paciente_id=payload.paciente_id,
        prestacion_id=payload.prestacion_id,
        profesional_id=payload.profesional_id,
        ventana_desde=payload.ventana_desde,
        ventana_hasta=payload.ventana_hasta,
    )
    # Un solo commit: la entrada + `lista_espera_creada` quedan visibles
    # juntas (el test lee el evento con otra sesión).
    await repo_auditoria.registrar_auditoria(
        sesion,
        accion="lista_espera_creada",
        entidad="lista_espera",
        entidad_id=str(entrada.id),
        diff={"estado": entrada.estado, "prestacion_id": str(payload.prestacion_id)},
        usuario_id=usuario.id,
    )
    await sesion.commit()
    await sesion.refresh(entrada)
    return _resumen(entrada)


@router.get("", status_code=status.HTTP_200_OK)
async def listar_lista_espera(
    estado: str | None = Query(None),
    sesion: AsyncSession = Depends(get_session),
    usuario: Usuario = Depends(_lectura),
) -> list[dict[str, Any]]:
    _ = usuario
    stmt = select(ListaEspera)
    if estado:
        stmt = stmt.where(ListaEspera.estado == estado)

    filas = (await sesion.execute(stmt)).scalars().all()
    return [_resumen(f) for f in filas]


@router.get("/{espera_id}", status_code=status.HTTP_200_OK)
async def obtener_lista_espera(
    espera_id: str,
    sesion: AsyncSession = Depends(get_session),
    usuario: Usuario = Depends(_lectura),
) -> dict[str, Any]:
    _ = usuario
    try:
        uid = uuid.UUID(espera_id)
    except ValueError:
        raise EntidadNoEncontradaError("lista_espera") from None

    entrada = await sesion.get(ListaEspera, uid)
    if entrada is None:
        raise EntidadNoEncontradaError("lista_espera")

    return _resumen(entrada)


@router.delete("/{espera_id}", status_code=status.HTTP_200_OK)
async def eliminar_lista_espera(
    espera_id: str,
    sesion: AsyncSession = Depends(get_session),
    usuario: Usuario = Depends(_escritura),
) -> dict[str, Any]:
    _ = usuario
    try:
        uid = uuid.UUID(espera_id)
    except ValueError:
        raise EntidadNoEncontradaError("lista_espera") from None

    entrada = await dar_de_baja_lista_espera(sesion, uid)
    await sesion.commit()

    return {
        "id": str(entrada.id),
        "estado": entrada.estado,
    }
