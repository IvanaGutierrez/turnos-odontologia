"""Autogestión del paciente por token C-05 (spec `agenda/autogestion-paciente`).

Ver-propio minimizado + confirmar/cancelar/reprogramar por `token_publico`
sin JWT + rotación staff. R6: resolución en una sola query por token (sin
ramas que delaten existencia), 404 byte-idéntico, diffs solo con
IDs/horarios/estados (`sanitizar_diff`), token solo en path nunca en query.
R3: reprogramar delega en el núcleo de C-04 (pre-chequeo + GiST mandan).
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    EntidadNoEncontradaError,
    FueraDeTerminoError,
    SenaPendienteError,
    TransicionInvalidaError,
)
from app.core.logger import get_logger
from app.core.settings import settings
from app.models.entidades import ESTADOS_INACTIVOS, Turno
from app.repositories import agenda as repo
from app.repositories import auditoria as repo_auditoria
from app.services.agenda import REPROGRAMABLE_DESDE, reprogramar_turno
from app.services.avisos import tras_cancelar, tras_confirmar
from app.services.reserva_publica import url_pago_para

logger = get_logger(__name__)

# Cuerpo 404 único (byte-idéntico exista o no el token, R6 anti-enumeración).
NO_ENCONTRADO: dict[str, str] = {
    "problema": "no_encontrado",
    "detalle": "El recurso solicitado no existe.",
}

DETALLE_RATELIMIT = "Demasiados intentos. Reintentá más tarde."

# Máquina consolidada C-05 (sin `en_sala`: migración 005 lo hizo `presente`).
CONFIRMABLE_DESDE: frozenset[str] = frozenset({"reservado"})
CANCELABLE_DESDE: frozenset[str] = frozenset({"reservado", "confirmado"})

SEDE_POR_DEFECTO = "Consultorio"


def min_horas_cancelacion() -> int:
    """Antelación mínima en horas (`CANCEL_MIN_HOURS`, default 12, por env)."""
    try:
        return int(os.environ.get("CANCEL_MIN_HOURS", str(settings.cancel_min_hours)))
    except ValueError:
        return settings.cancel_min_hours


def texto_politica() -> str:
    """Texto del consultorio ante cancelación fuera de término (por env)."""
    return os.environ.get("CANCEL_POLICY_TEXT", settings.cancel_policy_text)


def ahora_utc() -> datetime:
    """Reloj inyectable (los tests lo congelan con freezegun; prod: UTC)."""
    return datetime.now(timezone.utc)


async def chequear_rate_ip(redis: Any, ip: str | None) -> tuple[int, int | None] | None:
    """Rate por IP en endpoints públicos (mismo esquema INCR+EXPIRE de C-03).

    `(429, espera)` si se excede `RATE_PUBLIC_IP_MAX/WINDOW`, `None` si pasa.
    Topes legibles por env en cada llamada (piloto sin cambiar código,
    patrón C-03). Sin Redis (caída) → fail-open: la DB manda (C-02/C-03).
    """
    if redis is None:
        return None
    try:
        tope = _entero_env("RATE_PUBLIC_IP_MAX", settings.rate_public_ip_max)
        ventana = _entero_env(
            "RATE_PUBLIC_IP_WINDOW_S", settings.rate_public_ip_window_s
        )
        clave = f"rl:autogestion:ip:{ip or 'desconocida'}"
        conteo = await redis.incr(clave)
        if conteo == 1:
            await redis.expire(clave, ventana)
        if int(conteo) > tope:
            ttl = await redis.ttl(clave)
            espera = ttl if isinstance(ttl, int) and ttl > 0 else ventana
            return 429, espera
    except Exception:  # noqa: BLE001 — fail-open intencional (la DB manda).
        logger.warning("redis no disponible, degradando", extra={"op": "rate"})
        return None
    return None


def _entero_env(nombre: str, base: int) -> int:
    """Tope legible por env en cada llamada (piloto sin cambiar código)."""
    try:
        return int(os.environ.get(nombre, str(base)))
    except ValueError:
        return base


async def resolver_por_token(
    session: AsyncSession, token: str, *, para_actualizar: bool = False
) -> Turno | None:
    """Turno del token en UNA query (R6: sin ramas que delaten existencia).

    Tras una reprogramación el token vive en dos filas: se elige la no
    inactiva (el turno vigente); si todas son inactivas, la primera (para
    responder idempotente/`422` en vez de `404` mentiroso).
    """
    filas = await repo.listar_turnos_por_token(
        session, token, para_actualizar=para_actualizar
    )
    if not filas:
        return None
    for fila in filas:
        if fila.estado not in ESTADOS_INACTIVOS:
            return fila
    return filas[0]


def ver_propio(
    turno: Turno, *, ahora: datetime, estado_pago: str | None = None
) -> dict[str, Any]:
    """Campos mínimos del turno propio (Ley 25.326: jamás PII ni el token).

    `estado_pago` expone el cobro sin PII (`pendiente|acreditado|
    rechazado`, `None` si no hay pago) para mostrar "pago rechazado,
    reintentá" con el mismo link (C-08).
    """
    min_horas = min_horas_cancelacion()
    en_termino = (turno.inicio - ahora) >= timedelta(hours=min_horas)
    cuerpo: dict[str, Any] = {
        "estado": turno.estado,
        "inicio": turno.inicio.isoformat(),
        "fin": turno.fin.isoformat(),
        "prestacion_nombre": turno.prestacion.nombre,
        "profesional_nombre": turno.profesional.nombre,
        "sede": turno.sillon.sede if turno.sillon is not None else SEDE_POR_DEFECTO,
        "puede_cancelar_en_termino": bool(
            turno.estado in CANCELABLE_DESDE and en_termino
        ),
        "horas_limite": min_horas,
        "estado_pago": estado_pago,
    }
    if bool(turno.prestacion.requiere_sena):
        cuerpo["url_pago"] = url_pago_para(turno.id, str(turno.token_publico))
    return cuerpo


async def ver_por_token(
    session: AsyncSession, token: str, *, ahora: datetime
) -> dict[str, Any] | None:
    """`None` si el token no existe (el router responde el 404 idéntico)."""
    from app.repositories import pagos as repo_pagos

    turno = await resolver_por_token(session, token)
    if turno is None:
        return None
    estado_pago = await repo_pagos.ultimo_por_turno(session, turno.id)
    return ver_propio(
        turno,
        ahora=ahora,
        estado_pago=estado_pago.estado if estado_pago is not None else None,
    )


async def confirmar_por_token(
    session: AsyncSession, token: str, *, ip: str | None
) -> dict[str, Any] | None:
    """`reservado→confirmado` idempotente + guarda de seña (RN-PA-02).

    `confirmado` repetido (incluso concurrente: `FOR UPDATE` serializa) →
    `200` sin re-auditar. Seña pendiente (sin `pago acreditado` C-08) →
    `SenaPendienteError` (`422` + `url_pago`, sin mutar ni crear `Pago`).
    Terminal → `422` sin mutar.
    """
    from app.repositories import pagos as repo_pagos

    turno = await resolver_por_token(session, token, para_actualizar=True)
    if turno is None:
        return None
    if turno.estado == "confirmado":
        estado_pago = await repo_pagos.ultimo_por_turno(session, turno.id)
        return ver_propio(
            turno,
            ahora=ahora_utc(),
            estado_pago=estado_pago.estado if estado_pago is not None else None,
        )
    if turno.estado not in CONFIRMABLE_DESDE:
        raise TransicionInvalidaError("confirmar", turno.estado)
    if bool(turno.prestacion.requiere_sena):
        acreditado = await repo_pagos.acreditado_por_turno(session, turno.id)
        if acreditado is None:
            raise SenaPendienteError(url_pago_para(turno.id, str(turno.token_publico)))
    turno.estado = "confirmado"
    await session.commit()
    await session.refresh(turno)
    await repo_auditoria.registrar_auditoria(
        session,
        accion="turno_confirmado",
        entidad="turno",
        entidad_id=str(turno.id),
        diff={
            "estado_anterior": "reservado",
            "estado_nuevo": "confirmado",
            "canal": "online",
        },
        usuario_id=None,
        ip=ip,
    )
    await session.commit()
    # C-06: programa confirmación + 24 h + 3 h (fresco: el commit expiró).
    fresco = await resolver_por_token(session, token)
    assert fresco is not None
    await tras_confirmar(session, fresco)
    await session.refresh(fresco)
    logger.info("turno confirmado por token", extra={"estado": fresco.estado})
    estado_pago = await repo_pagos.ultimo_por_turno(session, fresco.id)
    return ver_propio(
        fresco,
        ahora=ahora_utc(),
        estado_pago=estado_pago.estado if estado_pago is not None else None,
    )


async def cancelar_por_token(
    session: AsyncSession,
    token: str,
    *,
    motivo: str | None,
    ahora: datetime,
    ip: str | None,
) -> dict[str, Any] | None:
    """`reservado|confirmado→cancelado` en término; idempotente si `cancelado`.

    En término persiste `motivo_cancelacion?` + `cancelado_at`, audita
    `turno_cancelado` sin PII y libera el slot (`cancelado` es inactivo para
    GiST). Fuera de término → `FueraDeTerminoError` (`422` + política).
    """
    turno = await resolver_por_token(session, token, para_actualizar=True)
    if turno is None:
        return None
    # C-06: tras una reprogramación el token puede resolver al original
    # `reprogramado`; se sigue la cadena al turno vigente (idempotente).
    for _ in range(10):
        if turno.estado != "reprogramado":
            break
        hijo = await repo.obtener_hijo_reprogramado(session, turno.id)
        if hijo is None:
            break
        turno = hijo
    if turno.estado == "cancelado":
        return ver_propio(turno, ahora=ahora)
    if turno.estado not in CANCELABLE_DESDE:
        raise TransicionInvalidaError("cancelar", turno.estado)
    min_horas = min_horas_cancelacion()
    restante = turno.inicio - ahora
    if restante < timedelta(hours=min_horas):
        horas = max(restante.total_seconds() / 3600, 0.0)
        raise FueraDeTerminoError(horas_restantes=round(horas, 2))
    anterior = turno.estado
    turno.estado = "cancelado"
    turno.motivo_cancelacion = motivo.strip() if motivo and motivo.strip() else None
    turno.cancelado_at = ahora
    turno_id: UUID = turno.id
    await session.commit()
    await session.refresh(turno)
    await repo_auditoria.registrar_auditoria(
        session,
        accion="turno_cancelado",
        entidad="turno",
        entidad_id=str(turno.id),
        diff={
            "estado_anterior": anterior,
            "estado_nuevo": "cancelado",
            "canal": "online",
        },
        usuario_id=None,
        ip=ip,
    )
    await session.commit()
    await session.refresh(turno)
    # C-06: cancela pendientes (idempotente; el turno queda `cancelado`).
    await tras_cancelar(session, turno_id=turno_id, motivo="turno_cancelado")
    await session.refresh(turno)
    # C-14: el hueco liberado se publica a la lista de espera (scoring +
    # blast top-N; sin elegibles no crea nada ni envía nada).
    await _publicar_hueco_en_espera(session, turno)
    await session.refresh(turno)
    logger.info("turno cancelado por token", extra={"estado": turno.estado})
    return ver_propio(turno, ahora=ahora)


async def _publicar_hueco_en_espera(session: AsyncSession, turno: Turno) -> None:
    """Publica el slot cancelado a la espera (best-effort, jamás revierte).

    El turno ya está `cancelado` y commiteado: si la espera falla, el
    hueco simplemente queda libre (fail-open; la cancelación manda).
    """
    try:
        from app.infrastructure.whatsapp.transporte import obtener_transporte
        from app.services import lista_espera as svc_espera

        await svc_espera.ofertar_hueco_liberado(
            session,
            {
                "hueco_origen_id": turno.id,
                "profesional_id": turno.profesional_id,
                "sillon_id": turno.sillon_id,
                "prestacion_id": turno.prestacion_id,
                "inicio": turno.inicio,
                "fin": turno.fin,
            },
            obtener_transporte(),
        )
        await session.commit()
    except Exception:  # noqa: BLE001 — la cancelación ya es efectiva.
        await session.rollback()
        logger.warning("hueco no publicado en espera, queda libre")


async def reprogramar_por_token(
    session: AsyncSession,
    token: str,
    *,
    nuevo_inicio: datetime,
    ip: str | None,
) -> Turno | None:
    """Reprogramación pública: mismo núcleo C-04 + enlace, token conservado.

    Delega en `reprogramar_turno` (pre-chequeo + GiST + `409` idéntico sin
    mutar) y suma auditoría `turno_reprogramado` sobre el ORIGINAL (el
    núcleo audita sobre el nuevo): ambas sin PII.
    """
    turno = await resolver_por_token(session, token)
    if turno is None:
        return None
    if turno.estado not in REPROGRAMABLE_DESDE:
        raise TransicionInvalidaError("reprogramar", turno.estado)
    original_id: UUID = turno.id
    inicio_anterior = turno.inicio.isoformat()
    nuevo = await reprogramar_turno(
        session,
        original_id,
        nuevo_inicio=nuevo_inicio,
        usuario_id=None,
        ip=ip,
    )
    await repo_auditoria.registrar_auditoria(
        session,
        accion="turno_reprogramado",
        entidad="turno",
        entidad_id=str(original_id),
        diff={
            "turno_nuevo_id": str(nuevo.id),
            "inicio_anterior": inicio_anterior,
            "inicio_nuevo": nuevo.inicio.isoformat(),
            "estado_original": "reprogramado",
            "canal": "online",
        },
        usuario_id=None,
        ip=ip,
    )
    await session.commit()
    await session.refresh(nuevo)
    return nuevo


async def rotar_token(
    session: AsyncSession,
    turno_id: UUID,
    *,
    usuario_id: UUID | None,
    ip: str | None,
) -> Turno:
    """Rotación staff: token nuevo, anterior inerte, `token_rotado` sin PII.

    El índice parcial (`WHERE estado NOT IN (inactivos)`) hace que el token
    viejo no resuelva a nada: los endpoints públicos responden el 404
    idéntico sin código extra. El `diff` jamás lleva tokens (R6).
    """
    turno = await repo.obtener_turno_por_id(session, turno_id)
    if turno is None:
        raise EntidadNoEncontradaError("turno")
    turno.token_publico = secrets.token_urlsafe(32)
    await session.commit()
    await session.refresh(turno)
    await repo_auditoria.registrar_auditoria(
        session,
        accion="token_rotado",
        entidad="turno",
        entidad_id=str(turno.id),
        diff={"estado": turno.estado, "canal": "staff"},
        usuario_id=usuario_id,
        ip=ip,
    )
    await session.commit()
    await session.refresh(turno)
    logger.info("token rotado", extra={"estado": turno.estado})
    return turno
