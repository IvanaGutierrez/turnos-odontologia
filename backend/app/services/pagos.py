"""Cobro de señas por Mercado Pago C-08 (preferencia + webhook, R0–R8).

- `GET /pagar/:token`: verifica el token opaco C-03, calcula la seña de
  la prestación (fijo gana a %; sin config → `422` sin preferencia),
  busca/crea idempotentemente UN `Pago pendiente` por turno y crea (o
  reutiliza si sigue vigente) la preferencia MP en ARS.
- `POST /webhooks/mercadopago`: tras firma válida, confirma el estado
  contra MP (nunca desde el cuerpo) y aplica en UNA transacción
  pago→turno→evento caja→comprobante; duplicado → `200` sin doble
  efecto (UNIQUE `mp_payment_id` + reclamo por estado; la DB manda).
- MP caído → `MercadoPagoNoDisponibleError` (el router responde `503`
  pinneado; turno intacto, aviso a recepción por auditoría).

R0: montos sintéticos, Fake MP en tests, jamás red real en la suite.
R6: logs/diffs/responses solo con `{pago_id, turno_id, monto, estado,
mp_payment_id, mp_preference_id}` — jamás PII del pagador.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.core.redis_client import obtener_redis
from app.infrastructure.mercadopago.client import (
    MercadoPagoClient,
    MercadoPagoNoDisponibleError,
    normalizar_estado,
)
from app.models.aviso_envio import AvisoEnvio
from app.models.entidades import Prestacion, Turno
from app.models.lista_espera import ListaEspera, OfertaEspera
from app.models.pago import Pago
from app.repositories import auditoria as repo_auditoria
from app.repositories import pagos as repo_pagos

logger = get_logger(__name__)

MONEDA_SENA = "ARS"
METODO_SENA = "mercadopago"

# El turno confirmado por webhook NO dispara la secuencia C-06
# (`confirmacion` + 24 h + 3 h): el único aviso es el comprobante de
# pago (exactamente-uno observable; WA caído no revierte la
# acreditación — el dinero manda sobre la notificación).
TIPO_COMPROBANTE = "comprobante_pago"


class SenaSinConfigurarError(Exception):
    """`requiere_sena` sin monto ni % (→ `422` visible, sin preferencia)."""


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def calcular_sena_monto(prestacion: Prestacion) -> Decimal:
    """Monto de la seña: fijo gana a % sobre `precio_base`.

    Sin fijo ni (base + %) → `SenaSinConfigurarError` (nunca cero
    silencioso, design decisión 4).
    """
    if prestacion.sena_monto_fijo is not None:
        return Decimal(prestacion.sena_monto_fijo)
    if prestacion.precio_base is not None and prestacion.sena_porcentaje is not None:
        monto = (
            Decimal(prestacion.precio_base)
            * Decimal(prestacion.sena_porcentaje)
            / Decimal(100)
        ).quantize(Decimal("0.01"))
        return monto
    raise SenaSinConfigurarError("sena_sin_configurar")


def metadata_para(turno_id: UUID, presupuesto_id: UUID | None = None) -> dict[str, str]:
    """Metadata de la preferencia (resoluble desde el aviso, design §3)."""
    metadata: dict[str, str] = {"turno_id": str(turno_id)}
    if presupuesto_id is not None:
        metadata["presupuesto_id"] = str(presupuesto_id)
    return metadata


async def link_pago_para(
    session: AsyncSession,
    turno: Turno,
    *,
    client: MercadoPagoClient,
    ip: str | None,
) -> dict[str, Any]:
    """Resuelve el link opaco a la preferencia MP vigente (idempotente).

    Retorna `{init_point, monto, moneda, estado_pago}` donde
    `estado_pago` es el último terminal (`rechazado` sigue visible con
    link de reintento) o `pendiente`. Crea UN pendiente por turno y UNA
    preferencia por pendiente (el reintento reutiliza la vigente).
    """
    if not bool(turno.prestacion.requiere_sena):
        raise SenaSinConfigurarError("sena_no_requerida")
    monto = calcular_sena_monto(turno.prestacion)

    acreditado = await repo_pagos.acreditado_por_turno(session, turno.id)
    if acreditado is not None:
        return {
            "init_point": acreditado.init_point,
            "monto": str(acreditado.monto),
            "moneda": MONEDA_SENA,
            "estado_pago": "acreditado",
        }

    pendiente = await repo_pagos.pendiente_por_turno(session, turno.id)
    if pendiente is None:
        # `ON CONFLICT DO NOTHING` sobre el UNIQUE parcial: ante carrera
        # el perdedor no recibe excepción (la sesión sigue sana) y
        # reutiliza el pendiente del ganador.
        insertado = (
            await session.execute(
                pg_insert(Pago)
                .values(
                    paciente_id=turno.paciente_id,
                    turno_id=turno.id,
                    monto=monto,
                    moneda=MONEDA_SENA,
                    metodo=METODO_SENA,
                    estado="pendiente",
                )
                .on_conflict_do_nothing(
                    index_elements=["turno_id"],
                    index_where=text("estado = 'pendiente'"),
                )
                .returning(Pago.id)
            )
        ).scalar_one_or_none()
        if insertado is not None:
            pendiente = await session.get(Pago, insertado)
            assert pendiente is not None
            await repo_auditoria.registrar_auditoria(
                session,
                accion="pago_creado",
                entidad="pago",
                entidad_id=str(pendiente.id),
                diff={
                    "pago_id": str(pendiente.id),
                    "turno_id": str(turno.id),
                    "monto": str(monto),
                    "moneda": MONEDA_SENA,
                    "estado": "pendiente",
                    "mp_preference_id": None,
                },
                usuario_id=None,
                ip=ip,
            )
            await session.flush()
        else:
            pendiente = await repo_pagos.pendiente_por_turno(session, turno.id)
            assert pendiente is not None  # el ganador lo dejó commiteado

    if not pendiente.mp_preference_id or not pendiente.init_point:
        try:
            preferencia = await client.crear_preferencia(
                monto=monto,
                moneda=MONEDA_SENA,
                metadata=metadata_para(turno.id),
            )
        except Exception as exc:
            await session.commit()
            await repo_auditoria.registrar_auditoria(
                session,
                accion="pago_mp_no_disponible",
                entidad="pago",
                entidad_id=str(pendiente.id),
                diff={
                    "pago_id": str(pendiente.id),
                    "turno_id": str(turno.id),
                    "monto": str(monto),
                    "estado": "pendiente",
                },
                usuario_id=None,
                ip=ip,
            )
            await session.commit()
            logger.warning("mp caído al crear preferencia")
            raise MercadoPagoNoDisponibleError("mp_no_disponible") from exc
        pendiente.mp_preference_id = str(preferencia.get("id", ""))
        pendiente.init_point = str(preferencia.get("init_point", ""))
        await session.flush()
    await session.commit()

    # El rechazo sigue visible aunque ya exista el pendiente de reintento
    # (el paciente ve "pago rechazado, reintentá" con el mismo link).
    if await repo_pagos.hubo_rechazo(session, turno.id):
        estado_visible = "rechazado"
    else:
        estado_visible = "pendiente"
    logger.info(
        "link de pago resuelto",
        extra={"turno_id": str(turno.id), "estado": estado_visible},
    )
    return {
        "init_point": pendiente.init_point,
        "monto": str(monto),
        "moneda": MONEDA_SENA,
        "estado_pago": estado_visible,
    }


async def resolver_turno_para_aviso(
    session: AsyncSession,
    metadata: dict[str, str],
    monto: Decimal,
) -> Turno | None:
    """Vincula el aviso a su turno (metadata manda; fallback único).

    1. `metadata.turno_id` / `external_reference` (MP real siempre la
       porta: la fijamos al crear la preferencia).
    2. Fallback (el Fake de tests no porta metadata): si hay EXACTAMENTE
       UN turno `reservado` con seña requerida y sin acreditado, y su
       seña calculada coincide con el monto informado, se vincula. Ante
       cero o múltiples candidatos, o monto distinto, `None` (jamás se
       atribuye dinero a ciegas, CRITICO).
    """
    crudo = metadata.get("turno_id") or metadata.get("external_reference")
    if crudo:
        try:
            turno_id = UUID(crudo)
        except ValueError:
            return None
        stmt = select(Turno).where(Turno.id == turno_id)
        turno = (await session.execute(stmt)).scalar_one_or_none()
        return turno
    candidatos = await repo_pagos.candidatos_sena_pendiente(session)
    if len(candidatos) != 1:
        return None
    try:
        esperado = calcular_sena_monto(candidatos[0].prestacion)
    except SenaSinConfigurarError:
        return None
    if esperado != monto:
        return None
    return candidatos[0]


async def encolar_comprobante(
    session: AsyncSession, *, turno_id: UUID, monto: Decimal
) -> None:
    """Comprobante de pago vía C-06 (UNIQUE turno+tipo: exactamente-uno).

    Inserción directa con `ON CONFLICT DO NOTHING` (sin pasar por el
    veto marketing de C-06: no es marketing; sin excepciones: la sesión
    sigue sana para el resto de la transacción). `payload_hash` sin PII;
    el worker drena por `programado_para` aunque Redis caiga (fail-open).
    """
    huella = hashlib.sha256(
        f"{turno_id}:{monto}:{TIPO_COMPROBANTE}".encode()
    ).hexdigest()
    await session.execute(
        pg_insert(AvisoEnvio)
        .values(
            turno_id=turno_id,
            tipo_aviso=TIPO_COMPROBANTE,
            estado="pendiente",
            programado_para=ahora_utc(),
            payload_hash=huella,
        )
        .on_conflict_do_nothing(index_elements=["turno_id", "tipo_aviso"])
    )
    try:
        redis = obtener_redis()
    except Exception:  # noqa: BLE001 — sin Redis la DB manda.
        redis = None
    if redis is not None:
        try:
            await redis.rpush("wa:envios", f"{turno_id}:{TIPO_COMPROBANTE}")
        except Exception:  # noqa: BLE001 — fail-open intencional.
            logger.warning("redis no disponible, degradando")


async def _insertar_pago(
    session: AsyncSession,
    *,
    paciente_id: UUID | None,
    turno_id: UUID | None,
    monto: Decimal,
    moneda: str,
    mp_payment_id: str,
    objetivo: str,
) -> Pago | None:
    """Inserta el pago; `None` si un concurrente ganó (duplicado).

    `ON CONFLICT DO NOTHING` sobre `uq_pago_mp_payment` (la DB manda):
    sin excepciones, la sesión sigue sana. Ante `None` el llamador
    responde `200` duplicado sin efectos (MP reintenta el aviso y la
    próxima vez el pago ya existe).
    """
    insertado = (
        await session.execute(
            pg_insert(Pago)
            .values(
                paciente_id=paciente_id,
                turno_id=turno_id,
                monto=monto,
                moneda=moneda,
                metodo=METODO_SENA,
                estado=objetivo,
                mp_payment_id=mp_payment_id,
                webhook_recibido_at=ahora_utc(),
            )
            .on_conflict_do_nothing(index_elements=["mp_payment_id"])
            .returning(Pago.id)
        )
    ).scalar_one_or_none()
    if insertado is None:
        return None
    fila = await session.get(Pago, insertado)
    assert fila is not None
    return fila


def _es_interbloqueo(exc: BaseException) -> bool:
    """Detecta `deadlock detected` (SQLSTATE 40P01) del driver.

    Dos `INSERT` concurrentes bajo el GiST de exclusión pueden
    interbloquearse (cada uno espera el lock especulativo del otro) y
    Postgres aborta UNO con 40P01: ese es el perdedor de la carrera y va
    por el camino de reembolso, igual que ante `ExclusionViolation`.
    """
    causa = getattr(exc, "orig", None)
    if causa is None:
        return False
    if str(getattr(causa, "sqlstate", "")).upper() == "40P01":
        return True
    return "deadlock detected" in str(causa).lower()


async def _reembolsar_oferta(
    session: AsyncSession,
    *,
    oferta: OfertaEspera,
    entrada: ListaEspera | None,
    mp_payment_id: str,
    monto: Decimal,
    moneda: str,
    motivo: str,
    desplazar: bool,
    client: MercadoPagoClient,
    ip: str | None,
) -> str:
    """Devuelve el dinero sin asignar turno (R3: sin turno no hay cargo).

    - `desplazar=True` (slot ocupado por otro): la oferta pasa a
      `desplazada` y la entrada vuelve a `activa` (puede re-ofertarse).
    - Oferta ya resuelta o vencida: no se tocan oferta ni entrada ganadora.
    Reintenta el reembolso contra MP cuando el cliente lo soporta; la
    fila `reembolsado` + auditoría quedan siempre (la DB manda).
    """
    reembolsar = getattr(client, "reembolsar_pago", None) or getattr(
        client, "reembolsar", None
    )
    if callable(reembolsar):
        try:
            await reembolsar(mp_payment_id)
        except Exception:  # noqa: BLE001 — queda registrado igual.
            logger.warning("reembolso mp no confirmado, registrado igual")
    pago = await _insertar_pago(
        session,
        paciente_id=entrada.paciente_id if entrada is not None else None,
        turno_id=None,
        monto=monto,
        moneda=moneda,
        mp_payment_id=mp_payment_id,
        objetivo="reembolsado",
    )
    if pago is None:
        await session.rollback()
        return "duplicado"
    if desplazar:
        oferta.estado = "desplazada"
    if entrada is not None and entrada.estado == "ofertada":
        entrada.estado = "activa"
    await repo_auditoria.registrar_auditoria(
        session,
        accion="pago_reembolsado",
        entidad="pago",
        entidad_id=str(pago.id),
        diff={
            "pago_id": str(pago.id),
            "turno_id": None,
            "monto": str(pago.monto),
            "moneda": pago.moneda,
            "estado": "reembolsado",
            "mp_payment_id": mp_payment_id,
            "oferta_espera_id": str(oferta.id),
            "motivo": motivo,
        },
        usuario_id=None,
        ip=ip,
    )
    await session.commit()
    logger.info(
        "oferta reembolsada sin turno",
        extra={"oferta_id": str(oferta.id), "motivo": motivo},
    )
    return "reembolsado"


async def _procesar_aviso_oferta(
    session: AsyncSession,
    *,
    mp_payment_id: str,
    estado_mp: str,
    monto: Decimal,
    moneda: str,
    oferta_id: str,
    client: MercadoPagoClient,
    ip: str | None,
) -> str:
    """Acredita la seña de una oferta de lista de espera (C-14, R3).

    Reclamo atómico: la oferta se bloquea (`FOR UPDATE`) y el turno se
    inserta bajo el GiST vigente. Si el slot se ocupó entre la oferta y
    el pago (otro canal o un concurrente ganó), el `INSERT` choca con la
    exclusión → el pagador va a `reembolsado` y su entrada a `activa`,
    sin turno duplicado ni cargo sin turno.
    """
    try:
        oferta_uuid = UUID(oferta_id)
    except ValueError:
        oferta_uuid = None
    oferta = None
    if oferta_uuid is not None:
        stmt = (
            select(OfertaEspera)
            .where(OfertaEspera.id == oferta_uuid)
            .with_for_update()
        )
        oferta = (await session.execute(stmt)).scalar_one_or_none()
    if oferta is None:
        await repo_auditoria.registrar_auditoria(
            session,
            accion="pago_sin_turno",
            entidad="pago",
            entidad_id=None,
            diff={
                "mp_payment_id": mp_payment_id,
                "monto": str(monto),
                "moneda": moneda,
                "oferta_espera_id": oferta_id,
            },
            usuario_id=None,
            ip=ip,
        )
        await session.commit()
        return "sin_turno"
    entrada = await session.get(ListaEspera, oferta.lista_espera_id)

    if estado_mp != "aprobado":
        pago = await _insertar_pago(
            session,
            paciente_id=entrada.paciente_id if entrada is not None else None,
            turno_id=None,
            monto=monto,
            moneda=moneda,
            mp_payment_id=mp_payment_id,
            objetivo="rechazado",
        )
        if pago is None:
            await session.rollback()
            return "duplicado"
        await repo_auditoria.registrar_auditoria(
            session,
            accion="pago_rechazado",
            entidad="pago",
            entidad_id=str(pago.id),
            diff={
                "pago_id": str(pago.id),
                "monto": str(pago.monto),
                "moneda": pago.moneda,
                "estado": "rechazado",
                "mp_payment_id": mp_payment_id,
                "oferta_espera_id": str(oferta.id),
            },
            usuario_id=None,
            ip=ip,
        )
        await session.commit()
        return "rechazado"

    ahora = ahora_utc()
    if oferta.estado != "pendiente":
        # Oferta ya resuelta (aceptada/expirada/desplazada): pago tardío.
        return await _reembolsar_oferta(
            session,
            oferta=oferta,
            entrada=entrada,
            mp_payment_id=mp_payment_id,
            monto=monto,
            moneda=moneda,
            motivo="oferta_resuelta",
            desplazar=False,
            client=client,
            ip=ip,
        )
    if oferta.expira_at <= ahora:
        oferta.estado = "expirada"
        await repo_auditoria.registrar_auditoria(
            session,
            accion="oferta_expirada",
            entidad="oferta_espera",
            entidad_id=str(oferta.id),
            diff={
                "lista_espera_id": str(oferta.lista_espera_id),
                "hueco_origen_id": str(oferta.hueco_origen_id),
            },
        )
        await session.flush()
        return await _reembolsar_oferta(
            session,
            oferta=oferta,
            entrada=entrada,
            mp_payment_id=mp_payment_id,
            monto=monto,
            moneda=moneda,
            motivo="oferta_vencida",
            desplazar=False,
            client=client,
            ip=ip,
        )
    if entrada is None:
        return await _reembolsar_oferta(
            session,
            oferta=oferta,
            entrada=None,
            mp_payment_id=mp_payment_id,
            monto=monto,
            moneda=moneda,
            motivo="espera_inexistente",
            desplazar=True,
            client=client,
            ip=ip,
        )

    # PKs a mano: tras un `rollback` los atributos expiran y leerlos
    # haría IO implícito (prohibido en `AsyncSession`).
    oferta_pk: UUID = oferta.id
    try:
        prestacion = await session.get(Prestacion, entrada.prestacion_id)
        try:
            sena = (
                calcular_sena_monto(prestacion)
                if prestacion is not None
                else monto
            )
        except SenaSinConfigurarError:
            sena = monto
        turno = Turno(
            paciente_id=entrada.paciente_id,
            profesional_id=oferta.profesional_id,
            sillon_id=oferta.sillon_id,
            prestacion_id=entrada.prestacion_id,
            inicio=oferta.inicio,
            fin=oferta.fin,
            estado="confirmado",
            canal="lista_espera",
            token_publico=secrets.token_urlsafe(32),
        )
        session.add(turno)
        await session.flush()
    except IntegrityError:
        # El GiST decidió: otro canal o un concurrente tomó el slot.
        carrera_perdida = True
    except DBAPIError as exc:
        # Interbloqueo entre los dos `INSERT` concurrentes: Postgres
        # abortó este; es el perdedor de la carrera.
        if not _es_interbloqueo(exc):
            raise
        logger.info("carrera de ofertas resuelta por interbloqueo")
        carrera_perdida = True
    else:
        carrera_perdida = False
    if carrera_perdida:
        await session.rollback()
        oferta = await session.get(OfertaEspera, oferta_pk)
        assert oferta is not None
        entrada = await session.get(ListaEspera, oferta.lista_espera_id)
        return await _reembolsar_oferta(
            session,
            oferta=oferta,
            entrada=entrada,
            mp_payment_id=mp_payment_id,
            monto=monto,
            moneda=moneda,
            motivo="slot_ocupado",
            desplazar=True,
            client=client,
            ip=ip,
        )

    oferta.estado = "aceptada"
    entrada.estado = "asignada"
    pago = await _insertar_pago(
        session,
        paciente_id=entrada.paciente_id,
        turno_id=turno.id,
        monto=sena,
        moneda=moneda,
        mp_payment_id=mp_payment_id,
        objetivo="acreditado",
    )
    if pago is None:
        await session.rollback()
        return "duplicado"
    await repo_auditoria.registrar_auditoria(
        session,
        accion="pago_acreditado",
        entidad="pago",
        entidad_id=str(pago.id),
        diff={
            "v": 1,
            "pago_id": str(pago.id),
            "turno_id": str(pago.turno_id),
            "monto": str(pago.monto),
            "moneda": pago.moneda,
            "metodo": METODO_SENA,
            "mp_payment_id": mp_payment_id,
        },
        usuario_id=None,
        ip=ip,
    )
    await repo_auditoria.registrar_auditoria(
        session,
        accion="lista_espera_asignada",
        entidad="lista_espera",
        entidad_id=str(entrada.id),
        diff={
            "lista_espera_id": str(entrada.id),
            "oferta_espera_id": str(oferta.id),
            "turno_id": str(turno.id),
            "hueco_origen_id": str(oferta.hueco_origen_id),
        },
        usuario_id=None,
        ip=ip,
    )
    await repo_auditoria.registrar_auditoria(
        session,
        accion="aviso_a_recepcion",
        entidad="turno",
        entidad_id=str(turno.id),
        diff={
            "lista_espera_id": str(entrada.id),
            "turno_id": str(turno.id),
            "hueco_origen_id": str(oferta.hueco_origen_id),
            "motivo": "hueco_asignado_lista_espera",
        },
        usuario_id=None,
        ip=ip,
    )
    await session.flush()
    await encolar_comprobante(session, turno_id=turno.id, monto=Decimal(pago.monto))
    await session.commit()
    logger.info(
        "oferta aceptada con turno",
        extra={"oferta_id": str(oferta.id), "turno_id": str(turno.id)},
    )
    return "acreditado"


async def procesar_aviso(
    session: AsyncSession,
    *,
    mp_payment_id: str,
    client: MercadoPagoClient,
    ip: str | None,
) -> str:
    """Aplica un aviso verificado (UNA transacción; duplicado → sin efecto).

    Retorna `acreditado|rechazado|duplicado|desconocido|pendiente_mp|
    sin_turno` (el router siempre responde `200`, salvo MP caído → el
    servicio audita y levanta `MercadoPagoNoDisponibleError` → `503`
    pinneado). El estado manda MP, nunca el cuerpo (design decisión 5).
    """
    try:
        info = await client.obtener_pago(mp_payment_id)
    except Exception as exc:
        await repo_auditoria.registrar_auditoria(
            session,
            accion="pago_mp_no_disponible",
            entidad="pago",
            entidad_id=None,
            diff={"mp_payment_id": mp_payment_id},
            usuario_id=None,
            ip=ip,
        )
        await session.commit()
        logger.warning("mp caído al confirmar aviso")
        raise MercadoPagoNoDisponibleError("mp_no_disponible") from exc
    if info is None:
        await repo_auditoria.registrar_auditoria(
            session,
            accion="pago_desconocido",
            entidad="pago",
            entidad_id=None,
            diff={"mp_payment_id": mp_payment_id},
            usuario_id=None,
            ip=ip,
        )
        await session.commit()
        return "desconocido"

    estado_mp = normalizar_estado(str(info.get("estado", "")))
    if estado_mp == "pendiente":
        await session.commit()
        return "pendiente_mp"
    objetivo = "acreditado" if estado_mp == "aprobado" else "rechazado"
    monto = Decimal(str(info.get("monto", "0")))
    moneda = str(info.get("moneda") or MONEDA_SENA)
    metadata = info.get("metadata") or {}
    metadata = {str(k): str(v) for k, v in metadata.items()}

    pago = await repo_pagos.obtener_por_mp(session, mp_payment_id, para_actualizar=True)
    if pago is not None and pago.estado != "pendiente":
        await session.rollback()
        return "duplicado"
    if pago is None and metadata.get("oferta_espera_id"):
        # C-14: el pago porta la oferta de lista de espera (reclamo
        # atómico + reembolso; la DB/GiST mandan ante concurrencia).
        return await _procesar_aviso_oferta(
            session,
            mp_payment_id=mp_payment_id,
            estado_mp=estado_mp,
            monto=monto,
            moneda=moneda,
            oferta_id=str(metadata["oferta_espera_id"]),
            client=client,
            ip=ip,
        )
    if pago is not None:
        # Reclamo por estado (el `FOR UPDATE` serializa: el segundo ve el
        # estado ya mutado y cae en `duplicado` sin doble efecto).
        pago.estado = objetivo
        pago.webhook_recibido_at = ahora_utc()
        await session.flush()
    else:
        turno = await resolver_turno_para_aviso(session, metadata, monto)
        if turno is None:
            await repo_auditoria.registrar_auditoria(
                session,
                accion="pago_sin_turno",
                entidad="pago",
                entidad_id=None,
                diff={
                    "mp_payment_id": mp_payment_id,
                    "monto": str(monto),
                    "moneda": moneda,
                },
                usuario_id=None,
                ip=ip,
            )
            await session.commit()
            logger.warning("aviso sin turno resoluble, a conciliar manual")
            return "sin_turno"
        # El link ya había creado el pendiente (flujo GET→pago): se reclama
        # por estado (el `FOR UPDATE` + filtro `pendiente` serializa: el
        # segundo encuentra la fila ya mutada —o inserta en conflicto— y
        # cae en `duplicado` sin doble efecto).
        previo_pendiente = await repo_pagos.pendiente_por_turno(
            session, turno.id, para_actualizar=True
        )
        if previo_pendiente is not None:
            previo_pendiente.mp_payment_id = mp_payment_id
            previo_pendiente.webhook_recibido_at = ahora_utc()
            previo_pendiente.estado = objetivo
            pago = previo_pendiente
            try:
                await session.flush()
            except IntegrityError:
                # Un insertador concurrente commiteó el mismo mp id entre
                # el lock y el flush: rollback + duplicado (MP reintenta).
                await session.rollback()
                return "duplicado"
        else:
            pago = await _insertar_pago(
                session,
                paciente_id=turno.paciente_id,
                turno_id=turno.id,
                monto=monto,
                moneda=moneda,
                mp_payment_id=mp_payment_id,
                objetivo=objetivo,
            )
            if pago is None:
                return "duplicado"

    assert pago.turno_id is not None
    if objetivo == "acreditado":
        await _aplicar_acreditacion(session, pago=pago, turno_id=pago.turno_id, ip=ip)
    else:
        await repo_auditoria.registrar_auditoria(
            session,
            accion="pago_rechazado",
            entidad="pago",
            entidad_id=str(pago.id),
            diff={
                "pago_id": str(pago.id),
                "turno_id": str(pago.turno_id),
                "monto": str(pago.monto),
                "moneda": pago.moneda,
                "estado": "rechazado",
                "mp_payment_id": mp_payment_id,
            },
            usuario_id=None,
            ip=ip,
        )
    await session.commit()
    logger.info(
        "aviso aplicado",
        extra={
            "pago_id": str(pago.id),
            "turno_id": str(pago.turno_id),
            "monto": str(pago.monto),
            "estado": objetivo,
            "mp_payment_id": mp_payment_id,
        },
    )
    return objetivo


async def _aplicar_acreditacion(
    session: AsyncSession,
    *,
    pago: Pago,
    turno_id: UUID,
    ip: str | None,
) -> None:
    """Turno `reservado→confirmado` + evento caja + comprobante (atomico).

    El evento `pago_acreditado` (payload v1) es la interfaz hacia la
    conciliación de C-09; sin tabla `MovimientoCaja` aquí (design §7).
    """
    stmt = select(Turno).where(Turno.id == turno_id).with_for_update()
    turno = (await session.execute(stmt)).scalar_one_or_none()
    if turno is not None and turno.estado == "reservado":
        turno.estado = "confirmado"
        await repo_auditoria.registrar_auditoria(
            session,
            accion="turno_confirmado",
            entidad="turno",
            entidad_id=str(turno.id),
            diff={
                "estado_anterior": "reservado",
                "estado_nuevo": "confirmado",
                "canal": "webhook_mp",
            },
            usuario_id=None,
            ip=ip,
        )
    await repo_auditoria.registrar_auditoria(
        session,
        accion="pago_acreditado",
        entidad="pago",
        entidad_id=str(pago.id),
        diff={
            "v": 1,
            "pago_id": str(pago.id),
            "turno_id": str(pago.turno_id),
            "monto": str(pago.monto),
            "moneda": pago.moneda,
            "metodo": METODO_SENA,
            "mp_payment_id": pago.mp_payment_id,
        },
        usuario_id=None,
        ip=ip,
    )
    await session.flush()
    await encolar_comprobante(session, turno_id=turno_id, monto=Decimal(pago.monto))
