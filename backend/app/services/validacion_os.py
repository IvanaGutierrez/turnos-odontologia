"""Servicio de validación OS preventiva C-13 (RN-OS-01/02, R0–R8).

- `validar_cobertura`: matching en 3 pasos con cortocircuito sobre datos
  LOCALES (IN-01, sin webservices): (a) afiliación vigente del paciente
  del turno (`vigente` + `paciente_id` + `vigencia_desde/hasta` contra
  la fecha del turno); (b) lookup de la prestación del turno en el
  nomenclador vigente (por nombre normalizado); (c) topes/frecuencias
  contra el historial propio (`ValidacionCobertura` previas del
  afiliado, `fuente: historial_local` — aproximado por diseño). Cada
  paso fallido mapea a motivo (`sin_afiliacion_vigente|
  fuera_de_nomenclador|tope_agotado|frecuencia_excedida`) y resultado
  (`no_cubre` para a/b, `parcial` para c). Persiste UNA fila con la
  versión de nomenclador CONGELADA + evento `validacion_os_registrada`
  sin PII. NUNCA muta el turno (la derivación a particular es propuesta,
  el presupuesto nace por el flujo C-07 existente).
- CRUD afiliaciones: alta con nro. aceptado pero jamás devuelto en
  claro (enmascarado últimos 4), duplicada vigente → `409` (la DB
  manda con el índice parcial), vigencia inválida → `422`, baja
  lógica + eventos `afiliacion_creada|afiliacion_actualizada` sin PII.
- R6: logs/diffs/responses solo con IDs/resultado/versión/motivos; el
  nro. de afiliado JAMÁS se loguea, audita ni devuelve en claro.

Todo dato sintético (R0); type hints siempre (R1).
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntidadNoEncontradaError
from app.core.logger import get_logger
from app.models.entidades import Paciente, Prestacion, Turno
from app.models.obra_social import (
    RESULTADOS_VALIDACION,
    AfiliacionOS,
    ObraSocial,
    ValidacionCobertura,
)
from app.repositories import auditoria as repo_auditoria
from app.schemas.obra_social import enmascarar_nro

logger = get_logger(__name__)

FUENTE_HISTORIAL = "historial_local"

RESULTADO_CUBRE = "cubre"
RESULTADO_PARCIAL = "parcial"
RESULTADO_NO_CUBRE = "no_cubre"

MOTIVO_SIN_AFILIACION = "sin_afiliacion_vigente"
MOTIVO_FUERA_NOMENCLADOR = "fuera_de_nomenclador"
MOTIVO_TOPE_AGOTADO = "tope_agotado"
MOTIVO_FRECUENCIA_EXCEDIDA = "frecuencia_excedida"

_FREC_RE = re.compile(r"^\s*(\d+)")


class AfiliacionAjenaError(Exception):
    """La afiliación pertenece a otro paciente (→ `422`, sin PII)."""


class OSInactivaError(Exception):
    """La OS está inactiva (→ `422`, sin PII)."""


class AfiliacionDuplicadaError(Exception):
    """Afiliación vigente ya existente paciente+OS (→ `409`, la DB manda)."""


class AfiliacionInvalidaError(Exception):
    """Vigencia inválida (`hasta < desde`, → `422`, sin efectos)."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


def codigo_para(nombre_prestacion: str) -> str:
    """Clave de nomenclador: nombre normalizado en minúsculas."""
    return nombre_prestacion.strip().lower()


def _frecuencia_maxima(frecuencia: object) -> int | None:
    """`'2-anual'` → `2`; irreconocible → `None` (regla no aplica)."""
    if not isinstance(frecuencia, str):
        return None
    m = _FREC_RE.match(frecuencia)
    return int(m.group(1)) if m else None


def _entero_no_negativo(valor: object) -> int | None:
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int) and valor >= 0:
        return valor
    return None


async def _consumo_previo(
    session: AsyncSession, *, afiliacion_id: uuid.UUID, codigo: str
) -> int:
    """Validaciones previas del afiliado sobre el mismo código (cubre/parcial).

    El historial por afiliado es chico: se filtra el código en Python
    (evita operadores JSONB en SQL; el `detalle` siempre lleva `codigo`).
    """
    filas = (
        (
            await session.execute(
                select(ValidacionCobertura.detalle).where(
                    ValidacionCobertura.afiliacion_id == afiliacion_id,
                    ValidacionCobertura.resultado.in_(
                        [RESULTADO_CUBRE, RESULTADO_PARCIAL]
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    return sum(1 for d in filas if isinstance(d, dict) and d.get("codigo") == codigo)


async def validar_cobertura(
    session: AsyncSession,
    *,
    turno_id: uuid.UUID,
    afiliacion_id: uuid.UUID,
    usuario_id: uuid.UUID | None,
    ip: str | None,
) -> dict[str, Any]:
    """Valida UN turno y persiste la `ValidacionCobertura` (el turno intacto)."""
    turno = await session.get(Turno, turno_id)
    if turno is None:
        raise EntidadNoEncontradaError("turno")
    afiliacion = await session.get(AfiliacionOS, afiliacion_id)
    if afiliacion is None:
        raise EntidadNoEncontradaError("afiliacion")
    if afiliacion.paciente_id != turno.paciente_id:
        raise AfiliacionAjenaError("afiliacion de otro paciente")
    obra_social = await session.get(ObraSocial, afiliacion.obra_social_id)
    if obra_social is None:
        raise EntidadNoEncontradaError("obra_social")
    if not obra_social.activa:
        raise OSInactivaError("obra social inactiva")
    prestacion = await session.get(Prestacion, turno.prestacion_id)
    if prestacion is None:
        raise EntidadNoEncontradaError("prestacion")

    version = int(obra_social.nomenclador_version)
    codigo = codigo_para(prestacion.nombre)
    fecha_turno: date = turno.inicio.date()

    async def _falla(motivo: str) -> dict[str, Any]:
        """Atajo `no_cubre` de los pasos (a)/(b) con cortocircuito."""
        return await _registrar(
            session,
            turno=turno,
            afiliacion=afiliacion,
            obra_social=obra_social,
            version=version,
            codigo=codigo,
            resultado=RESULTADO_NO_CUBRE,
            motivo=motivo,
            usuario_id=usuario_id,
            ip=ip,
        )

    # Paso (a): afiliación vigente del paciente a la fecha del turno.
    if not _vigente_en(afiliacion, fecha_turno):
        return await _falla(MOTIVO_SIN_AFILIACION)

    # Paso (b): prestación en el nomenclador LOCAL vigente.
    nomenclador = obra_social.nomenclador or {}
    entrada = nomenclador.get(codigo)
    if not isinstance(entrada, dict) or entrada.get("cubre") is not True:
        return await _falla(MOTIVO_FUERA_NOMENCLADOR)

    # Paso (c): topes/frecuencias contra el historial local.
    consumo = await _consumo_previo(session, afiliacion_id=afiliacion.id, codigo=codigo)
    topes = obra_social.topes or {}
    tope_cantidad = _entero_no_negativo(topes.get(f"cantidad_{codigo}_anual"))
    if tope_cantidad is not None and consumo >= tope_cantidad:
        return await _registrar(
            session,
            turno=turno,
            afiliacion=afiliacion,
            obra_social=obra_social,
            version=version,
            codigo=codigo,
            resultado=RESULTADO_PARCIAL,
            motivo=MOTIVO_TOPE_AGOTADO,
            consumo=consumo,
            tope=tope_cantidad,
            copago=_entero_no_negativo(entrada.get("copago")) or 0,
            usuario_id=usuario_id,
            ip=ip,
        )
    frecuencia_max = _frecuencia_maxima(entrada.get("frecuencia"))
    if frecuencia_max is not None and consumo >= frecuencia_max:
        return await _registrar(
            session,
            turno=turno,
            afiliacion=afiliacion,
            obra_social=obra_social,
            version=version,
            codigo=codigo,
            resultado=RESULTADO_PARCIAL,
            motivo=MOTIVO_FRECUENCIA_EXCEDIDA,
            consumo=consumo,
            tope=frecuencia_max,
            copago=_entero_no_negativo(entrada.get("copago")) or 0,
            usuario_id=usuario_id,
            ip=ip,
        )

    return await _registrar(
        session,
        turno=turno,
        afiliacion=afiliacion,
        obra_social=obra_social,
        version=version,
        codigo=codigo,
        resultado=RESULTADO_CUBRE,
        consumo=consumo,
        copago=_entero_no_negativo(entrada.get("copago")) or 0,
        frecuencia=(
            entrada.get("frecuencia")
            if isinstance(entrada.get("frecuencia"), str)
            else None
        ),
        usuario_id=usuario_id,
        ip=ip,
    )


def _vigente_en(afiliacion: AfiliacionOS, fecha: date) -> bool:
    """Vigencia a la fecha del turno (flag + ventana desde/hasta)."""
    if not afiliacion.vigente:
        return False
    if afiliacion.vigencia_desde > fecha:
        return False
    if afiliacion.vigencia_hasta is None:
        return True
    return fecha <= afiliacion.vigencia_hasta


async def _registrar(
    session: AsyncSession,
    *,
    turno: Turno,
    afiliacion: AfiliacionOS,
    obra_social: ObraSocial,
    version: int,
    codigo: str,
    resultado: str,
    motivo: str | None = None,
    consumo: int = 0,
    tope: int | None = None,
    copago: int = 0,
    frecuencia: str | None = None,
    usuario_id: uuid.UUID | None,
    ip: str | None,
) -> dict[str, Any]:
    """Persiste la validación + auditoría y arma la respuesta (sin PII)."""
    assert resultado in RESULTADOS_VALIDACION
    detalle: dict[str, Any] = {
        "codigo": codigo,
        "fuente": FUENTE_HISTORIAL,
        "nomenclador_version": version,
        "consumo_previo": consumo,
    }
    if resultado == RESULTADO_CUBRE:
        detalle.update({"cubre": True, "copago": copago})
        if frecuencia is not None:
            detalle["frecuencia"] = frecuencia
    elif resultado == RESULTADO_PARCIAL:
        assert motivo in (MOTIVO_TOPE_AGOTADO, MOTIVO_FRECUENCIA_EXCEDIDA)
        detalle.update(
            {
                "motivo": motivo,
                "tope": tope,
                "copago": copago,
                "particular_a_cargo": copago,
            }
        )
    else:
        assert motivo in (MOTIVO_SIN_AFILIACION, MOTIVO_FUERA_NOMENCLADOR)
        detalle["motivo"] = motivo

    fila = ValidacionCobertura(
        turno_id=turno.id,
        afiliacion_id=afiliacion.id,
        obra_social_id=obra_social.id,
        nomenclador_version=version,
        resultado=resultado,
        detalle=detalle,
    )
    session.add(fila)
    await session.flush()
    await repo_auditoria.registrar_auditoria(
        session,
        accion="validacion_os_registrada",
        entidad="validacion_cobertura",
        entidad_id=str(fila.id),
        diff={
            "validacion_id": str(fila.id),
            "turno_id": str(turno.id),
            "obra_social_id": str(obra_social.id),
            "resultado": resultado,
            "nomenclador_version": version,
        },
        usuario_id=usuario_id,
        ip=ip,
    )
    await session.commit()
    logger.info(
        "validacion os registrada",
        extra={
            "resultado": resultado,
            "nomenclador_version": version,
            "deriva_particular": resultado == RESULTADO_NO_CUBRE,
        },
    )
    respuesta: dict[str, Any] = {
        "resultado": resultado,
        "detalle": detalle,
        "validacion_id": str(fila.id),
        "nomenclador_version": version,
        "deriva_particular": resultado == RESULTADO_NO_CUBRE,
    }
    if resultado == RESULTADO_NO_CUBRE:
        respuesta["derivacion"] = {
            "flujo": "particular",
            "accion": "generar_presupuesto",
        }
    return respuesta


def cuerpo_afiliacion(afiliacion: AfiliacionOS) -> dict[str, Any]:
    """Serialización con nro. enmascarado (R6: jamás en claro)."""
    return {
        "id": str(afiliacion.id),
        "paciente_id": str(afiliacion.paciente_id),
        "obra_social_id": str(afiliacion.obra_social_id),
        "nro_afiliado": enmascarar_nro(afiliacion.nro_afiliado),
        "vigencia_desde": afiliacion.vigencia_desde.isoformat(),
        "vigencia_hasta": (
            afiliacion.vigencia_hasta.isoformat()
            if afiliacion.vigencia_hasta is not None
            else None
        ),
        "vigente": bool(afiliacion.vigente),
    }


async def _existe_vigente(
    session: AsyncSession,
    *,
    paciente_id: uuid.UUID,
    obra_social_id: uuid.UUID,
    excluir_id: uuid.UUID | None = None,
) -> bool:
    consulta = (
        select(func.count())
        .select_from(AfiliacionOS)
        .where(
            AfiliacionOS.paciente_id == paciente_id,
            AfiliacionOS.obra_social_id == obra_social_id,
            AfiliacionOS.vigente.is_(True),
        )
    )
    if excluir_id is not None:
        consulta = consulta.where(AfiliacionOS.id != excluir_id)
    return int(await session.scalar(consulta) or 0) > 0


def _validar_vigencia(desde: date, hasta: date | None) -> None:
    if hasta is not None and hasta < desde:
        raise AfiliacionInvalidaError("vigencia_hasta anterior a vigencia_desde")


async def crear_afiliacion(
    session: AsyncSession,
    *,
    paciente_id: uuid.UUID,
    obra_social_id: uuid.UUID,
    nro_afiliado: str,
    vigencia_desde: date,
    vigencia_hasta: date | None,
    usuario_id: uuid.UUID | None,
    ip: str | None,
) -> AfiliacionOS:
    """Alta de afiliación (duplicada vigente → `409`, vigencia → `422`)."""
    _validar_vigencia(vigencia_desde, vigencia_hasta)
    if await session.get(Paciente, paciente_id) is None:
        raise EntidadNoEncontradaError("paciente")
    if await session.get(ObraSocial, obra_social_id) is None:
        raise EntidadNoEncontradaError("obra_social")
    if await _existe_vigente(
        session, paciente_id=paciente_id, obra_social_id=obra_social_id
    ):
        raise AfiliacionDuplicadaError("afiliacion vigente existente")
    fila = AfiliacionOS(
        paciente_id=paciente_id,
        obra_social_id=obra_social_id,
        nro_afiliado=nro_afiliado,
        vigencia_desde=vigencia_desde,
        vigencia_hasta=vigencia_hasta,
        vigente=True,
    )
    session.add(fila)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AfiliacionDuplicadaError("afiliacion vigente existente") from exc
    await repo_auditoria.registrar_auditoria(
        session,
        accion="afiliacion_creada",
        entidad="afiliacion_os",
        entidad_id=str(fila.id),
        diff={
            "afiliacion_id": str(fila.id),
            "paciente_id": str(paciente_id),
            "obra_social_id": str(obra_social_id),
            "vigencia_desde": vigencia_desde.isoformat(),
            "vigencia_hasta": (
                vigencia_hasta.isoformat() if vigencia_hasta is not None else None
            ),
            "vigente": True,
        },
        usuario_id=usuario_id,
        ip=ip,
    )
    await session.commit()
    logger.info("afiliacion creada")
    return fila


async def obtener_afiliacion(
    session: AsyncSession, afiliacion_id: uuid.UUID
) -> AfiliacionOS:
    """Una afiliación o `404` idéntico (sin PII)."""
    fila = await session.get(AfiliacionOS, afiliacion_id)
    if fila is None:
        raise EntidadNoEncontradaError("afiliacion")
    return fila


async def listar_afiliaciones(session: AsyncSession) -> list[AfiliacionOS]:
    """Padrón completo (solo staff; nro. siempre enmascarado en el router)."""
    return list(
        (
            await session.execute(
                select(AfiliacionOS).order_by(
                    AfiliacionOS.creado_en.desc(), AfiliacionOS.id.desc()
                )
            )
        )
        .scalars()
        .all()
    )


async def actualizar_afiliacion(
    session: AsyncSession,
    *,
    afiliacion_id: uuid.UUID,
    vigencia_hasta: date | None,
    tocar_hasta: bool,
    vigente: bool | None,
    usuario_id: uuid.UUID | None,
    ip: str | None,
) -> AfiliacionOS:
    """PATCH de vigencia/flag (revalida; audita sin PII)."""
    fila = await obtener_afiliacion(session, afiliacion_id)
    nueva_hasta = vigencia_hasta if tocar_hasta else fila.vigencia_hasta
    _validar_vigencia(fila.vigencia_desde, nueva_hasta)
    fila.vigencia_hasta = nueva_hasta
    if vigente is not None:
        if vigente and await _existe_vigente(
            session,
            paciente_id=fila.paciente_id,
            obra_social_id=fila.obra_social_id,
            excluir_id=fila.id,
        ):
            raise AfiliacionDuplicadaError("afiliacion vigente existente")
        fila.vigente = vigente
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AfiliacionDuplicadaError("afiliacion vigente existente") from exc
    await repo_auditoria.registrar_auditoria(
        session,
        accion="afiliacion_actualizada",
        entidad="afiliacion_os",
        entidad_id=str(fila.id),
        diff={
            "afiliacion_id": str(fila.id),
            "vigencia_hasta": (
                fila.vigencia_hasta.isoformat()
                if fila.vigencia_hasta is not None
                else None
            ),
            "vigente": bool(fila.vigente),
        },
        usuario_id=usuario_id,
        ip=ip,
    )
    await session.commit()
    logger.info("afiliacion actualizada")
    return fila


async def baja_afiliacion(
    session: AsyncSession,
    *,
    afiliacion_id: uuid.UUID,
    usuario_id: uuid.UUID | None,
    ip: str | None,
) -> AfiliacionOS:
    """Baja lógica (`vigente=false`, sin borrado físico)."""
    return await actualizar_afiliacion(
        session,
        afiliacion_id=afiliacion_id,
        vigencia_hasta=None,
        tocar_hasta=False,
        vigente=False,
        usuario_id=usuario_id,
        ip=ip,
    )
