"""Servicio clínico C-07: ficha/HCE + odontograma batch + evoluciones.

Gate de consentimiento en servicio (RN-CL-01, Ley 26.529): sin
`paciente.consentimiento_hc` → `ConsentimientoRequeridoError` (el router
responde `422` genérico sin crear nada). Toda escritura registra
`firmante_usuario_id + firmado_en` (RN-CL-04) y audita sin contenido
clínico (`sanitizar_diff`, R6): solo IDs/códigos/roles/fechas.

`profesional_id` de la ficha: C-07 no mapea `Usuario→Profesional`; el
servicio usa el primer profesional activo como referencia operativa
(seed demo lo garantiza). El vínculo tratante-paciente para exportación
es `firmante_usuario_id` (odontólogo JWT creador), no el profesional.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.models.clinica import (
    CatalogoOdontogramaEstado,
    Evolucion,
    Ficha,
    OdontogramaEntry,
)
from app.models.entidades import Paciente, Profesional
from app.repositories import auditoria as repo_auditoria
from app.schemas.clinica import CARAS_VALIDAS, OdontogramaEntryIn
from app.services.cifrado_hce import cifrar, clave_id_vigente

logger = get_logger(__name__)

PIEZAS_FDI_VALIDAS: frozenset[int] = frozenset(
    list(range(11, 19))
    + list(range(21, 29))
    + list(range(31, 39))
    + list(range(41, 49))
)


class ConsentimientoRequeridoError(Exception):
    """Sin `consentimiento_hc` no existe HCE (→ 422, sin crear nada)."""


class OdontogramaInvalidoError(Exception):
    """Entry inválida (pieza/cara/estado); el router responde 422 atómico."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


class FichaNoEncontradaError(Exception):
    """Ficha inexistente (→ 404 genérico, sin PII)."""


def ahora() -> datetime:
    return datetime.now(timezone.utc)


async def _profesional_referencia(session: AsyncSession) -> Profesional | None:
    fila = (
        (
            await session.execute(
                select(Profesional)
                .where(Profesional.activo.is_(True))
                .order_by(Profesional.nombre)
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    return fila


async def obtener_ficha(session: AsyncSession, ficha_id: UUID) -> Ficha | None:
    return await session.get(Ficha, ficha_id)


async def crear_ficha(
    session: AsyncSession,
    *,
    paciente_id: UUID,
    anamnesis: str | None,
    firmante_id: UUID,
    firmante_rol: str,
    ip: str | None = None,
) -> Ficha:
    """Crea HCE solo con consentimiento; audita `ficha_creada` sin contenido."""
    paciente = await session.get(Paciente, paciente_id)
    if paciente is None:
        raise FichaNoEncontradaError("paciente")
    if not paciente.consentimiento_hc:
        logger.info("ficha bloqueada sin consentimiento")
        raise ConsentimientoRequeridoError("consentimiento")
    profesional = await _profesional_referencia(session)
    if profesional is None:
        raise FichaNoEncontradaError("profesional")
    marca = ahora()
    ficha = Ficha(
        paciente_id=paciente.id,
        profesional_id=profesional.id,
        anamnesis_cifrada=cifrar(anamnesis),
        firmante_usuario_id=firmante_id,
        firmado_en=marca,
        consentimiento_en=marca,
        clave_id=clave_id_vigente(),
    )
    session.add(ficha)
    await session.flush()
    await repo_auditoria.registrar_auditoria(
        session,
        accion="ficha_creada",
        entidad="ficha",
        entidad_id=str(ficha.id),
        diff={"paciente_id": str(paciente.id), "firmante_rol": firmante_rol},
        usuario_id=firmante_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(ficha)
    logger.info("ficha creada")
    return ficha


async def editar_ficha(
    session: AsyncSession,
    ficha_id: UUID,
    *,
    anamnesis: str | None,
    firmante_id: UUID,
    firmante_rol: str,
    ip: str | None = None,
) -> Ficha:
    """Edición del tratante con re-firma; audita `ficha_editada` sin contenido."""
    ficha = await session.get(Ficha, ficha_id)
    if ficha is None:
        raise FichaNoEncontradaError("ficha")
    if anamnesis is not None:
        ficha.anamnesis_cifrada = cifrar(anamnesis)
        ficha.clave_id = clave_id_vigente()
    ficha.firmante_usuario_id = firmante_id
    ficha.firmado_en = ahora()
    await session.flush()
    await repo_auditoria.registrar_auditoria(
        session,
        accion="ficha_editada",
        entidad="ficha",
        entidad_id=str(ficha.id),
        diff={"ficha_id": str(ficha.id), "firmante_rol": firmante_rol},
        usuario_id=firmante_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(ficha)
    logger.info("ficha editada")
    return ficha


async def _version_para_estado(session: AsyncSession, codigo: str) -> int | None:
    """Versión mínima activa con ese código (v1 preservada ante v2, RN-CL-02)."""
    fila = (
        await session.execute(
            select(func.min(CatalogoOdontogramaEstado.version)).where(
                CatalogoOdontogramaEstado.codigo == codigo,
                CatalogoOdontogramaEstado.activo.is_(True),
            )
        )
    ).scalar()
    return int(fila) if fila is not None else None


async def batch_odontograma(
    session: AsyncSession,
    ficha_id: UUID,
    entries: list[OdontogramaEntryIn],
    *,
    firmante_id: UUID,
    firmante_rol: str,
    ip: str | None = None,
) -> list[OdontogramaEntry]:
    """Upsert atómico por `(ficha_id, pieza_fdi, cara)`; inválido → 422 sin persistir."""
    ficha = await session.get(Ficha, ficha_id)
    if ficha is None:
        raise FichaNoEncontradaError("ficha")
    # Validación total ANTES de mutar (atomicidad R5).
    versiones: list[int] = []
    for e in entries:
        if e.pieza_fdi not in PIEZAS_FDI_VALIDAS:
            raise OdontogramaInvalidoError("pieza_fdi")
        if e.cara is not None and e.cara not in CARAS_VALIDAS:
            raise OdontogramaInvalidoError("cara")
        version = await _version_para_estado(session, e.estado_codigo)
        if version is None:
            raise OdontogramaInvalidoError("estado_codigo")
        versiones.append(version)
    filas: list[OdontogramaEntry] = []
    for e, version in zip(entries, versiones, strict=True):
        existente = (
            (
                await session.execute(
                    select(OdontogramaEntry).where(
                        OdontogramaEntry.ficha_id == ficha.id,
                        OdontogramaEntry.pieza_fdi == e.pieza_fdi,
                        OdontogramaEntry.cara.is_not_distinct_from(e.cara),
                    )
                )
            )
            .scalars()
            .first()
        )
        if existente is None:
            fila = OdontogramaEntry(
                ficha_id=ficha.id,
                pieza_fdi=e.pieza_fdi,
                estado_codigo=e.estado_codigo,
                catalogo_version=version,
                cara=e.cara,
            )
            session.add(fila)
            filas.append(fila)
        else:
            existente.estado_codigo = e.estado_codigo
            existente.catalogo_version = version
            existente.cara = e.cara
            filas.append(existente)
    await session.flush()
    await repo_auditoria.registrar_auditoria(
        session,
        accion="odontograma_actualizado",
        entidad="ficha",
        entidad_id=str(ficha.id),
        diff={
            "ficha_id": str(ficha.id),
            "piezas": sorted({e.pieza_fdi for e in entries}),
            "codigos": sorted({e.estado_codigo for e in entries}),
            "firmante_rol": firmante_rol,
        },
        usuario_id=firmante_id,
        ip=ip,
    )
    await session.commit()
    for f in filas:
        await session.refresh(f)
    logger.info("odontograma actualizado")
    return filas


async def agregar_evolucion(
    session: AsyncSession,
    ficha_id: UUID,
    *,
    texto: str,
    firmante_id: UUID,
    firmante_rol: str,
    ip: str | None = None,
) -> Evolucion:
    """Evolución firmada con texto cifrado; audita `evolucion_agregada`."""
    ficha = await session.get(Ficha, ficha_id)
    if ficha is None:
        raise FichaNoEncontradaError("ficha")
    marca = ahora()
    evolucion = Evolucion(
        ficha_id=ficha.id,
        texto_cifrado=cifrar(texto) or b"",
        firmante_usuario_id=firmante_id,
        firmado_en=marca,
        clave_id=clave_id_vigente(),
    )
    session.add(evolucion)
    await session.flush()
    await repo_auditoria.registrar_auditoria(
        session,
        accion="evolucion_agregada",
        entidad="ficha",
        entidad_id=str(ficha.id),
        diff={"ficha_id": str(ficha.id), "firmante_rol": firmante_rol},
        usuario_id=firmante_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(evolucion)
    logger.info("evolucion agregada")
    return evolucion
