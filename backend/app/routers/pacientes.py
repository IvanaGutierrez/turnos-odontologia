"""Router de pacientes C-07: contacto (recepción ok) + exportación Ley 25.326.

`PATCH /pacientes/:id` edita solo contacto (nombre/teléfono) con
`puede(rol, "pacientes")` (admin/odontólogo/recepción → 200); la HCE queda
intacta. `GET /pacientes/:id/exportacion` entrega las 7 secciones solo al
tratante (`firmante_usuario_id` = odontólogo JWT creador); cualquier otro
rol → `403` genérico sin exponer nada clínico + `acceso_clinico_denegado`.
Éxito audita `datos_exportados` sin PII (solo IDs). Anamnesis/evoluciones
descifradas solo para el tratante (R6 minimización por rol).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.dependencies import get_current_user
from app.domain.auth.matriz import puede
from app.models.clinica import (
    Evolucion,
    Ficha,
    OdontogramaEntry,
    Presupuesto,
    PresupuestoItem,
)
from app.models.entidades import Paciente, Turno, Usuario
from app.repositories import auditoria as repo_auditoria
from app.schemas.clinica import PacienteContactoPatch
from app.schemas.validators_ar import validar_telefono_ar
from app.services.cifrado_hce import descifrar

router = APIRouter(prefix="/pacientes", tags=["pacientes"])

DETALLE_SIN_PERMISO = "Sin permiso."


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.patch("/{paciente_id}", summary="Editar contacto (recepción ok, HCE intacta)")
async def patch_contacto(
    paciente_id: uuid.UUID,
    datos: PacienteContactoPatch,
    request: Request,
    usuario: Annotated[Usuario, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    if not puede(usuario.rol, "pacientes"):
        await repo_auditoria.registrar_auditoria(
            session,
            accion="acceso_denegado",
            entidad="paciente",
            entidad_id=str(paciente_id),
            diff={"recurso": "pacientes"},
            usuario_id=usuario.id,
            ip=_ip(request),
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=DETALLE_SIN_PERMISO
        )
    paciente = await session.get(Paciente, paciente_id)
    if paciente is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado."
        )
    if datos.nombre is not None:
        paciente.nombre = datos.nombre.strip()
    if datos.telefono is not None:
        try:
            paciente.telefono = validar_telefono_ar(datos.telefono)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="La solicitud contiene datos inválidos.",
            ) from None
    await session.commit()
    await session.refresh(paciente)
    return {"id": str(paciente.id), "telefono": paciente.telefono}


@router.get(
    "/{paciente_id}/exportacion", summary="Exportación Ley 25.326 (7 secciones)"
)
async def get_exportacion(
    paciente_id: uuid.UUID,
    request: Request,
    usuario: Annotated[Usuario, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    paciente = await session.get(Paciente, paciente_id)
    if paciente is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado."
        )
    fichas = (
        (
            await session.execute(
                select(Ficha)
                .where(Ficha.paciente_id == paciente.id)
                .order_by(Ficha.creado_en)
            )
        )
        .scalars()
        .all()
    )
    ficha = fichas[0] if fichas else None
    es_tratante = (
        ficha is not None
        and usuario.rol == "odontologo"
        and ficha.firmante_usuario_id == usuario.id
    )
    if not es_tratante:
        await repo_auditoria.registrar_auditoria(
            session,
            accion="acceso_clinico_denegado",
            entidad="paciente",
            entidad_id=str(paciente.id),
            diff={"recurso": "exportacion", "rol": usuario.rol},
            usuario_id=usuario.id,
            ip=_ip(request),
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=DETALLE_SIN_PERMISO
        )
    assert ficha is not None
    entries = (
        (
            await session.execute(
                select(OdontogramaEntry).where(OdontogramaEntry.ficha_id == ficha.id)
            )
        )
        .scalars()
        .all()
    )
    evoluciones = (
        (await session.execute(select(Evolucion).where(Evolucion.ficha_id == ficha.id)))
        .scalars()
        .all()
    )
    presupuestos = (
        (
            await session.execute(
                select(Presupuesto).where(Presupuesto.ficha_id == ficha.id)
            )
        )
        .scalars()
        .all()
    )
    items_por_pres: dict[str, list[dict[str, object]]] = {}
    for p in presupuestos:
        items = (
            (
                await session.execute(
                    select(PresupuestoItem).where(
                        PresupuestoItem.presupuesto_id == p.id
                    )
                )
            )
            .scalars()
            .all()
        )
        items_por_pres[str(p.id)] = [
            {
                "pieza_fdi": it.pieza_fdi,
                "estado_codigo": it.estado_codigo,
                "cantidad": it.cantidad,
                "precio_unitario": f"{it.precio_unitario:.2f}",
            }
            for it in items
        ]
    turnos = (
        (await session.execute(select(Turno).where(Turno.paciente_id == paciente.id)))
        .scalars()
        .all()
    )
    await repo_auditoria.registrar_auditoria(
        session,
        accion="datos_exportados",
        entidad="paciente",
        entidad_id=str(paciente.id),
        diff={"paciente_id": str(paciente.id)},
        usuario_id=usuario.id,
        ip=_ip(request),
    )
    await session.commit()
    return {
        "datos_contacto": {"nombre": paciente.nombre},
        "consentimientos": {"consentimiento_hc": bool(paciente.consentimiento_hc)},
        "ficha": {"id": str(ficha.id), "anamnesis": descifrar(ficha.anamnesis_cifrada)},
        "odontograma": [
            {
                "pieza_fdi": e.pieza_fdi,
                "estado_codigo": e.estado_codigo,
                "catalogo_version": e.catalogo_version,
                "cara": e.cara,
            }
            for e in entries
        ],
        "evoluciones": [
            {"id": str(ev.id), "texto": descifrar(ev.texto_cifrado)}
            for ev in evoluciones
        ],
        "presupuestos": [
            {
                "id": str(p.id),
                "estado": p.estado,
                "total": f"{p.total:.2f}",
                "items": items_por_pres.get(str(p.id), []),
            }
            for p in presupuestos
        ],
        "turnos": [
            {
                "id": str(t.id),
                "estado": t.estado,
                "inicio": t.inicio.isoformat(),
                "fin": t.fin.isoformat(),
            }
            for t in turnos
        ],
    }
