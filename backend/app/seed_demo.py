"""Semilla demo 100 % sintética e idempotente (R0).

Crea el consultorio ficticio mínimo: 1 admin, sede "Consultorio" + 2
sillones demo, 6 prestaciones con duraciones, 2 profesionales y 1 paciente
demo. Los IDs fijos coinciden con `tests/conftest.py` (el seed los
materializa en la DB de test). Re-ejecutar no duplica registros.

Sintético siempre: DNIs del rango de ejemplo `90xxxxxx`, teléfonos del
rango ficticio `+54 9 11 5000-xxxx`, nombres marcados `demo`.
"""

from __future__ import annotations

import asyncio
import os
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hashear_password
from app.models.disponibilidad import Bloqueo, HorarioProfesional
from app.models.entidades import Paciente, Prestacion, Profesional, Sillon, Usuario

# IDs canónicos (idénticos a tests/conftest.py — no cambiar sin ambos lados).
ID_PROFESIONAL_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
ID_PROFESIONAL_B = uuid.UUID("22222222-2222-4222-8222-222222222222")
ID_SILLON_S1 = uuid.UUID("33333333-3333-4333-8333-333333333333")
ID_SILLON_S2 = uuid.UUID("44444444-4444-4444-8444-444444444444")
ID_PRESTACION_LIMPIEZA_45 = uuid.UUID("55555555-5555-4555-8555-555555555555")
ID_PRESTACION_CONSULTA_30 = uuid.UUID("66666666-6666-4666-8666-666666666666")
ID_PACIENTE_DEMO = uuid.UUID("77777777-7777-4777-8777-777777777777")

# C-04: turnos demo con IDs fijos (idempotencia por PK; fecha 2026-12-01 a
# propósito fuera de las ventanas de fixtures de la suite — ningún test
# cuenta turnos absolutos ese día ni filtra esa ventana).
ID_TURNO_DEMO_1 = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
ID_TURNO_DEMO_2 = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2")
ID_SOBRETURNO_DEMO = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3")

EMAIL_ADMIN_DEMO = "admin.demo@consultorio.example"

# (nombre, duracion_min); las dos primeras con ID fijo (las usan los tests).
PRESTACIONES_DEMO: tuple[tuple[str, int, uuid.UUID | None], ...] = (
    ("Limpieza", 45, ID_PRESTACION_LIMPIEZA_45),
    ("Consulta", 30, ID_PRESTACION_CONSULTA_30),
    ("Endodoncia", 60, None),
    ("Extracción", 45, None),
    ("Control Ortodoncia", 30, None),
    ("Urgencia", 20, None),
)


async def seed(session: AsyncSession) -> None:
    """Inserta lo faltante; todo lookup es por PK o unique → idempotente."""
    admin = (
        await session.execute(select(Usuario).where(Usuario.email == EMAIL_ADMIN_DEMO))
    ).scalar_one_or_none()
    if admin is None:
        # C-02 (design plan de migración): hash Argon2id generado al sembrar
        # (R0: credencial ficticia a rotar en el primer login real; el valor
        # puede fijarse vía `SEED_DEMO_PASSWORD`, nunca en código — R7).
        demo_password = os.environ.get(
            "SEED_DEMO_PASSWORD", "Demo-Ficticia-No-Real-0000"
        )
        session.add(
            Usuario(
                email=EMAIL_ADMIN_DEMO,
                password_hash=hashear_password(demo_password),
                rol="admin",
                activo=True,
            )
        )

    for sid, nombre in (
        (ID_SILLON_S1, "Sillón Demo 1"),
        (ID_SILLON_S2, "Sillón Demo 2"),
    ):
        if await session.get(Sillon, sid) is None:
            session.add(Sillon(id=sid, nombre=nombre, sede="Consultorio", activo=True))

    for pid, nombre, matricula in (
        (ID_PROFESIONAL_A, "Profesional Demo A", "DEMO-MAT-A-001"),
        (ID_PROFESIONAL_B, "Profesional Demo B", "DEMO-MAT-B-002"),
    ):
        if await session.get(Profesional, pid) is None:
            session.add(
                Profesional(id=pid, nombre=nombre, matricula=matricula, activo=True)
            )

    for nombre, duracion, fid in PRESTACIONES_DEMO:
        existente = None
        if fid is not None:
            existente = await session.get(Prestacion, fid)
        else:
            existente = (
                await session.execute(
                    select(Prestacion).where(Prestacion.nombre == nombre)
                )
            ).scalar_one_or_none()
        if existente is None:
            session.add(
                Prestacion(
                    id=fid if fid is not None else uuid.uuid4(),
                    nombre=nombre,
                    duracion_min=duracion,
                )
            )

    if await session.get(Paciente, ID_PACIENTE_DEMO) is None:
        session.add(
            Paciente(
                id=ID_PACIENTE_DEMO,
                nombre="Paciente Demo Ficticia",
                dni="90876543",
                telefono="+54 9 11 5000-0002",
                consentimiento_hc=True,
            )
        )

    # C-03: 1 horario semanal + 1 bloqueo ficticios marcados `demo`
    # (idempotente por lookup; C-04 definirá recurrencias ricas).
    await _seed_agenda_demo(session)

    # C-04: 2 turnos + 1 sobreturno ficticios marcados `demo` (idempotente).
    await _seed_turnos_demo(session)

    # C-05: 1 turno `reservado` con token conocido para la autogestión demo.
    await _seed_autogestion_demo(session)

    # C-06: 1 turno `confirmado` con sus 3 avisos demo (idempotente).
    await _seed_avisos_demo(session)

    # C-07: 1 paciente ficticio con consentimiento + ficha demo + odontograma
    # de 3 piezas + presupuesto `borrador` demo (todo marcado `demo`, R0).
    await _seed_clinica_demo(session)

    # C-08: seña sintética en "Endodoncia" + 1 pago `acreditado` demo
    # (idempotente por lookups; no altera conteos de la regresión).
    await _seed_sena_demo(session)

    # C-09: 2–3 movimientos sintéticos + 1 cierre `abierto` demo del día
    # (idempotente por fecha/sede; la suite los purga antes de cada test).
    await _seed_caja_demo(session)

    # C-12: 1 turno `reservado` demo para la conversación WA + 1 evento
    # conversacional de ejemplo auditado marcado `demo` (idempotente).
    await _seed_conversacion_demo(session)

    await session.commit()


async def _seed_agenda_demo(session: AsyncSession) -> None:
    """Horario semanal demo (lunes 8–13) + bloqueo demo puntual (R0)."""
    from datetime import date, time
    from zoneinfo import ZoneInfo

    ba = ZoneInfo("America/Argentina/Buenos_Aires")
    horario_demo = (
        await session.execute(
            select(HorarioProfesional).where(
                HorarioProfesional.profesional_id == ID_PROFESIONAL_A,
                HorarioProfesional.dia_semana == 0,
                HorarioProfesional.hora_inicio == time(8, 0),
                HorarioProfesional.hora_fin == time(13, 0),
            )
        )
    ).scalar_one_or_none()
    if horario_demo is None:
        session.add(
            HorarioProfesional(
                profesional_id=ID_PROFESIONAL_A,
                dia_semana=0,
                hora_inicio=time(8, 0),
                hora_fin=time(13, 0),
                vigente_desde=None,
                vigente_hasta=None,
                activo=True,
            )
        )

    dia_demo = date(2026, 12, 25)
    ya = (
        await session.execute(
            select(Bloqueo).where(
                Bloqueo.profesional_id == ID_PROFESIONAL_A,
                Bloqueo.motivo == "Feriado demo ficticio",
            )
        )
    ).scalar_one_or_none()
    if ya is None:
        from datetime import datetime as _dt
        from datetime import timedelta as _td

        inicio_demo = _dt(dia_demo.year, dia_demo.month, dia_demo.day, tzinfo=ba)
        session.add(
            Bloqueo(
                profesional_id=ID_PROFESIONAL_A,
                sillon_id=None,
                desde=inicio_demo,
                hasta=inicio_demo + _td(days=1),
                motivo="Feriado demo ficticio",
                creado_por=None,
            )
        )


async def _seed_turnos_demo(session: AsyncSession) -> None:
    """2 turnos + 1 sobreturno ficticios para la grilla demo (R0, C-04).

    Idempotente por PK fija; `motivo_override="demo"` los marca como
    semilla (nunca datos reales). Profesional B + Sillón 2 el 2026-12-01:
    fuera de toda ventana de fixtures (la suite cuenta turnos absolutos
    solo sobre el profesional A y ventanas de noviembre).
    """
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from zoneinfo import ZoneInfo

    from app.models.entidades import Turno

    ba = ZoneInfo("America/Argentina/Buenos_Aires")
    base = _dt(2026, 12, 1, tzinfo=ba)

    demo: tuple[tuple[uuid.UUID, _dt, int, bool, str | None, str], ...] = (
        (ID_TURNO_DEMO_1, base.replace(hour=9), 45, False, None, "mostrador"),
        (ID_TURNO_DEMO_2, base.replace(hour=11), 30, False, None, "recepcion"),
        (
            ID_SOBRETURNO_DEMO,
            base.replace(hour=10),
            30,
            True,
            "Demanda espontánea demo ficticia",
            "recepcion",
        ),
    )
    prestacion_por_duracion = {
        45: ID_PRESTACION_LIMPIEZA_45,
        30: ID_PRESTACION_CONSULTA_30,
    }
    for i, (tid, inicio, minutos, es_sobreturno, motivo, canal) in enumerate(demo):
        if await session.get(Turno, tid) is not None:
            continue
        session.add(
            Turno(
                id=tid,
                paciente_id=ID_PACIENTE_DEMO,
                profesional_id=ID_PROFESIONAL_B,
                sillon_id=ID_SILLON_S2,
                prestacion_id=prestacion_por_duracion[minutos],
                inicio=inicio,
                fin=inicio + _td(minutes=minutos),
                estado="reservado",
                canal=canal,
                token_publico=f"demo-token-c04-{i + 1:02d}-ficticio-no-real",
                motivo_override="demo",
                sobreturno=es_sobreturno,
                motivo_sobreturno=motivo,
            )
        )


ID_TURNO_AUTOGESTION_DEMO = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1")
TOKEN_AUTOGESTION_DEMO = "demo-token-c05-autogestion-ficticia-no-real"


async def _seed_autogestion_demo(session: AsyncSession) -> None:
    """1 turno `reservado` con token conocido (C-05, R0, idempotente).

    Sirve para ejercitar la autogestión en dev (`GET /turnos/publicos/:token`
    y sus POST) sin datos reales: PK fija + lookup por token (doble
    ejecución no duplica). Profesional B + Sillón 2 el 2026-12-02: fuera de
    toda ventana de fixtures y de los conteos absolutos de la suite (que
    miran al profesional A, patrón de los seeds C-04).
    """
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from zoneinfo import ZoneInfo

    from sqlalchemy import select as _select

    from app.models.entidades import Turno

    ba = ZoneInfo("America/Argentina/Buenos_Aires")
    if await session.get(Turno, ID_TURNO_AUTOGESTION_DEMO) is not None:
        return
    ya = (
        await session.execute(
            _select(Turno).where(Turno.token_publico == TOKEN_AUTOGESTION_DEMO)
        )
    ).scalar_one_or_none()
    if ya is not None:
        return
    inicio = _dt(2026, 12, 2, 10, 0, tzinfo=ba)
    session.add(
        Turno(
            id=ID_TURNO_AUTOGESTION_DEMO,
            paciente_id=ID_PACIENTE_DEMO,
            profesional_id=ID_PROFESIONAL_B,
            sillon_id=ID_SILLON_S2,
            prestacion_id=ID_PRESTACION_LIMPIEZA_45,
            inicio=inicio,
            fin=inicio + _td(minutes=45),
            estado="reservado",
            canal="online",
            token_publico=TOKEN_AUTOGESTION_DEMO,
            motivo_override="demo",
        )
    )


ID_TURNO_AVISOS_DEMO = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc1")
TOKEN_AVISOS_DEMO = "demo-token-c06-avisos-ficticio-no-real"

# C-07 clínica demo (IDs fijos, R0 ficticio, idempotente por PK).
# Reusa el paciente demo (ficticio con consentimiento) para no romper el
# conteo `total_pacientes == 1` de `test_seed_demo_idempotente` (C-01).
ID_FICHA_DEMO = uuid.UUID("dddddddd-dddd-4ddd-8ddd-dddddddddd02")
ID_PRESUPUESTO_DEMO = uuid.UUID("dddddddd-dddd-4ddd-8ddd-dddddddddd03")


async def _seed_avisos_demo(session: AsyncSession) -> None:
    """1 turno `confirmado` con 3 avisos demo (C-06, R0, idempotente).

    Doble ejecución no duplica (lookups por PK + `UNIQUE` de avisos).
    Profesional B + Sillón 2 el 2026-12-03: fuera de toda ventana de
    fixtures de la suite.
    """
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from zoneinfo import ZoneInfo

    from sqlalchemy import select as _select

    from app.models.aviso_envio import AvisoEnvio
    from app.models.entidades import Turno

    ba = ZoneInfo("America/Argentina/Buenos_Aires")
    if await session.get(Turno, ID_TURNO_AVISOS_DEMO) is None:
        ya = (
            await session.execute(
                _select(Turno).where(Turno.token_publico == TOKEN_AVISOS_DEMO)
            )
        ).scalar_one_or_none()
        if ya is None:
            inicio = _dt(2026, 12, 3, 10, 0, tzinfo=ba)
            session.add(
                Turno(
                    id=ID_TURNO_AVISOS_DEMO,
                    paciente_id=ID_PACIENTE_DEMO,
                    profesional_id=ID_PROFESIONAL_B,
                    sillon_id=ID_SILLON_S2,
                    prestacion_id=ID_PRESTACION_LIMPIEZA_45,
                    inicio=inicio,
                    fin=inicio + _td(minutes=45),
                    estado="confirmado",
                    canal="mostrador",
                    token_publico=TOKEN_AVISOS_DEMO,
                    motivo_override="demo",
                )
            )
            await session.flush()
    demo_avisos: tuple[tuple[str, str, str | None], ...] = (
        ("confirmacion", "enviado", "wamid.demo-c06-0001"),
        ("recordatorio_24h", "enviado", "wamid.demo-c06-0002"),
        ("aviso_3h", "fallback", None),
    )
    for tipo, estado, proveedor_id in demo_avisos:
        ya_aviso = (
            await session.execute(
                _select(AvisoEnvio).where(
                    AvisoEnvio.turno_id == ID_TURNO_AVISOS_DEMO,
                    AvisoEnvio.tipo_aviso == tipo,
                )
            )
        ).scalar_one_or_none()
        if ya_aviso is None:
            session.add(
                AvisoEnvio(
                    turno_id=ID_TURNO_AVISOS_DEMO,
                    tipo_aviso=tipo,
                    estado=estado,
                    intentos=1,
                    proveedor_msg_id=proveedor_id,
                    programado_para=_dt(2026, 12, 3, 10, 0, tzinfo=ba),
                    enviado_en=(
                        _dt(2026, 12, 3, 10, 0, tzinfo=ba)
                        if estado == "enviado"
                        else None
                    ),
                )
            )


async def main() -> None:
    """Entry point: `python -m app.seed_demo` (solo dev/demo, jamás prod)."""
    from app.core.db import async_session_factory

    async with async_session_factory() as session:
        await seed(session)


async def _seed_clinica_demo(session: AsyncSession) -> None:
    """Ficha demo + odontograma 3 piezas + presupuesto `borrador` (C-07, R0).

    Reusa el paciente demo (ficticio con consentimiento) para no romper el
    conteo `total_pacientes == 1` de la regresión C-01. Idempotente por PK
    fija; doble ejecución no duplica (lookups por PK). Sin anamnesis
    cifrada (evita requerir `HCE_CIFRADO_KEY` en el seed) y sin firma (el
    flujo de firma lo ejercita la suite, no el seed).
    """
    from datetime import datetime as _dt
    from datetime import timezone as _tz
    from decimal import Decimal as _Dec

    from sqlalchemy import select as _select

    from app.models.clinica import (
        Ficha,
        OdontogramaEntry,
        Presupuesto,
        PresupuestoItem,
    )

    if await session.get(Paciente, ID_PACIENTE_DEMO) is None:
        raise AssertionError("seed clínico sin paciente demo base (orden de seed)")
    if await session.get(Ficha, ID_FICHA_DEMO) is None:
        session.add(
            Ficha(
                id=ID_FICHA_DEMO,
                paciente_id=ID_PACIENTE_DEMO,
                profesional_id=ID_PROFESIONAL_A,
                anamnesis_cifrada=None,
                firmante_usuario_id=None,
                firmado_en=None,
                consentimiento_en=_dt.now(_tz.utc),
                clave_id="hce-v1",
            )
        )
        await session.flush()
    demo_piezas: tuple[tuple[int, str, str | None], ...] = (
        (11, "sano", None),
        (16, "cariado", None),
        (36, "obturado", "oclusal"),
    )
    for pieza, codigo, cara in demo_piezas:
        ya = (
            await session.execute(
                _select(OdontogramaEntry).where(
                    OdontogramaEntry.ficha_id == ID_FICHA_DEMO,
                    OdontogramaEntry.pieza_fdi == pieza,
                    OdontogramaEntry.cara.is_not_distinct_from(cara),
                )
            )
        ).scalar_one_or_none()
        if ya is None:
            session.add(
                OdontogramaEntry(
                    ficha_id=ID_FICHA_DEMO,
                    pieza_fdi=pieza,
                    estado_codigo=codigo,
                    catalogo_version=1,
                    cara=cara,
                )
            )
    if await session.get(Presupuesto, ID_PRESUPUESTO_DEMO) is None:
        session.add(
            Presupuesto(
                id=ID_PRESUPUESTO_DEMO,
                ficha_id=ID_FICHA_DEMO,
                estado="borrador",
                total=_Dec("23000.00"),
                moneda="ARS",
                sena_requerida=_Dec(0),
                version=1,
            )
        )
        await session.flush()
        session.add(
            PresupuestoItem(
                presupuesto_id=ID_PRESUPUESTO_DEMO,
                pieza_fdi=16,
                estado_codigo="cariado",
                cantidad=1,
                precio_unitario=_Dec("15000.00"),
            )
        )
        session.add(
            PresupuestoItem(
                presupuesto_id=ID_PRESUPUESTO_DEMO,
                pieza_fdi=36,
                estado_codigo="obturado",
                cantidad=1,
                precio_unitario=_Dec("8000.00"),
            )
        )


# C-09 caja demo (fecha fija fuera de las ventanas de fixtures C-09,
# que usan días 10–22 de diciembre; R0 ficticio, idempotente).
FECHA_CAJA_DEMO_ISO = "2026-12-01"


async def _seed_caja_demo(session: AsyncSession) -> None:
    """2 movimientos + 1 cierre `abierto` demo (C-09, R0, idempotente).

    Doble ejecución no duplica (lookup por `fecha,sede`; el cierre demo
    queda `abierto` para ejercitar el arqueo sin bloquear movimientos).
    Montos de juguete, conceptos ficticios (nunca PII real).
    """
    from datetime import date as _date
    from datetime import datetime as _dt
    from datetime import timezone as _tz
    from decimal import Decimal as _Dec

    from sqlalchemy import select as _select

    from app.models.caja import CierreDiario, MovimientoCaja

    dia = _date(2026, 12, 1)
    ya_mov = (
        await session.execute(
            _select(MovimientoCaja.id).where(
                MovimientoCaja.fecha == dia,
                MovimientoCaja.sede == "Consultorio",
            )
        )
    ).first()
    if ya_mov is None:
        session.add(
            MovimientoCaja(
                fecha=dia,
                sede="Consultorio",
                tipo="ingreso",
                concepto="Cobro demo ficticio en efectivo",
                monto=_Dec("2500.00"),
                metodo="efectivo",
                usuario_id=None,
                pago_id=None,
                origen="manual",
            )
        )
        session.add(
            MovimientoCaja(
                fecha=dia,
                sede="Consultorio",
                tipo="ingreso",
                concepto="Cobro demo ficticio con tarjeta",
                monto=_Dec("8000.00"),
                metodo="tarjeta",
                usuario_id=None,
                pago_id=None,
                origen="manual",
            )
        )
        await session.flush()
    ya_cierre = (
        await session.execute(
            _select(CierreDiario.id).where(
                CierreDiario.fecha == dia,
                CierreDiario.sede == "Consultorio",
            )
        )
    ).first()
    if ya_cierre is None:
        session.add(
            CierreDiario(
                fecha=dia,
                sede="Consultorio",
                total_efectivo=_Dec("2500.00"),
                total_transferencia=_Dec(0),
                total_tarjeta=_Dec("8000.00"),
                total_mp=_Dec(0),
                total_egresos=_Dec(0),
                acreditado_mp=_Dec(0),
                diferencia=_Dec(0),
                estado="abierto",
                cerrado_por=None,
                cerrado_at=_dt.now(_tz.utc),
                reaperturas=0,
            )
        )
        await session.flush()


if __name__ == "__main__":
    asyncio.run(main())


# C-08 seña demo (IDs fijos, R0 ficticio, idempotente por lookups).
# Reusa "Endodoncia" del catálogo (UPDATE, sin alterar el conteo == 6 de
# la regresión) y el turno demo-1 para el pago `acreditado` demo.
MP_PAGO_DEMO_ID = "demo-mp-pago-0001"


async def _seed_sena_demo(session: AsyncSession) -> None:
    """Prestación con seña sintética + pago `acreditado` demo (C-08, R0).

    Doble ejecución no duplica (lookup por nombre + por `mp_payment_id`
    ficticio `demo-*`). Montos de juguete, jamás cifras reales.
    """
    from datetime import datetime as _dt
    from datetime import timezone as _tz
    from decimal import Decimal as _Dec

    from sqlalchemy import select as _select

    from app.models.pago import Pago

    endodoncia = (
        await session.execute(
            _select(Prestacion).where(Prestacion.nombre == "Endodoncia")
        )
    ).scalar_one_or_none()
    if endodoncia is not None:
        endodoncia.requiere_sena = True
        endodoncia.precio_base = _Dec("20000.00")
        endodoncia.sena_monto_fijo = _Dec("5000.00")
        await session.flush()

    from app.models.entidades import Turno

    ya_pago = (
        await session.execute(
            _select(Pago).where(Pago.mp_payment_id == MP_PAGO_DEMO_ID)
        )
    ).scalar_one_or_none()
    if ya_pago is None and await session.get(Turno, ID_TURNO_DEMO_1) is not None:
        session.add(
            Pago(
                paciente_id=ID_PACIENTE_DEMO,
                turno_id=ID_TURNO_DEMO_1,
                monto=_Dec("5000.00"),
                moneda="ARS",
                metodo="mercadopago",
                estado="acreditado",
                mp_payment_id=MP_PAGO_DEMO_ID,
                webhook_recibido_at=_dt.now(_tz.utc),
            )
        )


# C-12 conversación demo (IDs fijos, R0 ficticio, idempotente por PK).
# Reusa el paciente demo (sin crear pacientes nuevos: la regresión exige
# `total_pacientes == 1`) y el profesional B + sillón 2 el 2026-12-04,
# fuera de toda ventana de fixtures de la suite.
ID_TURNO_CONV_DEMO = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee1")
TOKEN_CONV_DEMO = "demo-token-c12-conv-ficticio-no-real"


async def _seed_conversacion_demo(session: AsyncSession) -> None:
    """1 turno `reservado` + 1 conversación de ejemplo auditada (C-12, R0).

    Doble ejecución no duplica (lookups por PK + por acción/entidad).
    El turno reusa el teléfono del paciente demo como remitente sintético;
    la auditoría es `conv_propuesta_slots` demo en entidad `conversacion`
    (sin PII: solo hash ficticio y `wa_message_id` demo).
    """
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from hashlib import sha256 as _sha
    from zoneinfo import ZoneInfo as _ZI

    from sqlalchemy import select as _select

    from app.models.auditoria import AuditoriaLog
    from app.models.entidades import Turno

    ba = _ZI("America/Argentina/Buenos_Aires")
    if await session.get(Turno, ID_TURNO_CONV_DEMO) is None:
        ya = (
            await session.execute(
                _select(Turno).where(Turno.token_publico == TOKEN_CONV_DEMO)
            )
        ).scalar_one_or_none()
        if ya is None:
            inicio = _dt(2026, 12, 4, 10, 0, tzinfo=ba)
            session.add(
                Turno(
                    id=ID_TURNO_CONV_DEMO,
                    paciente_id=ID_PACIENTE_DEMO,
                    profesional_id=ID_PROFESIONAL_B,
                    sillon_id=ID_SILLON_S2,
                    prestacion_id=ID_PRESTACION_LIMPIEZA_45,
                    inicio=inicio,
                    fin=inicio + _td(minutes=45),
                    estado="reservado",
                    canal="whatsapp",
                    token_publico=TOKEN_CONV_DEMO,
                    motivo_override="demo",
                )
            )
            await session.flush()
    demo_hash = _sha(b"+54 9 11 5000-0002").hexdigest()[:12]
    ya_conv = (
        await session.execute(
            _select(AuditoriaLog).where(
                AuditoriaLog.accion == "conv_propuesta_slots",
                AuditoriaLog.entidad == "conversacion",
                AuditoriaLog.entidad_id == str(ID_TURNO_CONV_DEMO),
            )
        )
    ).scalar_one_or_none()
    if ya_conv is None:
        session.add(
            AuditoriaLog(
                accion="conv_propuesta_slots",
                entidad="conversacion",
                entidad_id=str(ID_TURNO_CONV_DEMO),
                diff={
                    "remitente": demo_hash,
                    "wa_message_id": "wamid.demo-c12-0001",
                    "opciones": 3,
                    "demo": True,
                },
            )
        )
