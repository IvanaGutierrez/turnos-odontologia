"""Fixtures compartidas C-01 + C-02 (TDD: todo dato sintético, R0).

C-02 (task 1.8): fixtures aisladas con self-cleanup contra Postgres/Redis
de test, usuario sintético con hash Argon2id real y helper de login.
Cada `create_app()` recibe su `FakeRedis` propio (aislamiento por test).
"""

import os
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from app import seed_demo
from app.core.db import get_session
from app.core.security import hashear_password
from app.core.settings import settings
from app.main import create_app
from app.models.auditoria import AuditoriaLog
from app.models.aviso_envio import AvisoEnvio
from app.models.disponibilidad import (
    Bloqueo,
    ClaveIdempotencia,
    HorarioProfesional,
    VerificacionPublica,
)
from app.models.entidades import Paciente, Turno, Usuario
from app.models.pago import Pago
from app.models.sesiones import SesionRefresh
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

BA_ASUNCION = ZoneInfo("America/Argentina/Buenos_Aires")

# IDs demo fijos (sintéticos; GREEN: los crea seed_demo en turnos_test).
ID_PROFESIONAL_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
ID_PROFESIONAL_B = uuid.UUID("22222222-2222-4222-8222-222222222222")
ID_SILLON_S1 = uuid.UUID("33333333-3333-4333-8333-333333333333")
ID_SILLON_S2 = uuid.UUID("44444444-4444-4444-8444-444444444444")
ID_PRESTACION_LIMPIEZA_45 = uuid.UUID("55555555-5555-4555-8555-555555555555")
ID_PRESTACION_CONSULTA_30 = uuid.UUID("66666666-6666-4666-8666-666666666666")
ID_PACIENTE_DEMO = uuid.UUID("77777777-7777-4777-8777-777777777777")

TURNOS_URL = "/api/v1/turnos"

# PII 100 % ficticia para el test de sanitización (R0 + R6).
DNI_FICTICIO = "90123456"
TEL_FICTICIO = "+54 9 11 5000-0001"


def inicio_demo(hora: int = 10, minuto: int = 0) -> datetime:
    return datetime(2026, 11, 3, hora, minuto, tzinfo=BA_ASUNCION)


def payload_turno(
    inicio: datetime,
    profesional_id: uuid.UUID = ID_PROFESIONAL_A,
    sillon_id: uuid.UUID | None = ID_SILLON_S1,
    prestacion_id: uuid.UUID = ID_PRESTACION_LIMPIEZA_45,
    **extras: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "paciente_id": str(ID_PACIENTE_DEMO),
        "profesional_id": str(profesional_id),
        "sillon_id": str(sillon_id) if sillon_id else None,
        "prestacion_id": str(prestacion_id),
        "inicio": inicio.isoformat(),
    }
    payload.update(extras)
    return payload


def payload_paciente_ficticio() -> dict[str, object]:
    return {
        "nombre": "Paciente Ficticia Demo",
        "dni": DNI_FICTICIO,
        "telefono": TEL_FICTICIO,
        "consentimiento_hc": True,
    }


@pytest.fixture()
def app():
    application = create_app()
    application.dependency_overrides[get_session] = _sesion_prueba
    yield application
    application.dependency_overrides.clear()


TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://turnos:turnos@localhost:5432/turnos_test",
)

# NullPool: cada test corre en su propio event loop (Windows/pytest-asyncio
# con loop por función); reusar conexiones entre loops rompe asyncpg.
_test_engine = create_async_engine(
    TEST_DATABASE_URL,
    poolclass=NullPool,
)

TestSession = async_sessionmaker(
    _test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def _sesion_prueba() -> AsyncGenerator[AsyncSession, None]:
    async with TestSession() as sesion:
        yield sesion


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _cerrar_motor() -> AsyncGenerator[None, None]:
    yield
    await _test_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _usar_redis_falso() -> None:
    """C-03 (task 1.5): la suite siempre usa `fakeredis` (hermética, sin red).

    `create_app()` lee `settings.usar_redis_falso` en cada llamada, así que
    fijarlo aquí (antes de cualquier fixture `app`) aísla los contadores
    de rate limit por app sin depender del env del runner.
    """
    settings.usar_redis_falso = True


@pytest_asyncio.fixture(autouse=True)
async def _aislar_turnos() -> AsyncGenerator[None, None]:
    """Seed idempotente antes + limpieza total después (aislamiento C-02).

    Purga turnos/pacientes nuevos + sesiones y auditoría huérfanas: ningún
    test ve filas de otro (los asserts de conteo son deterministas).
    C-03: también purga las tablas de agenda pública (idempotencia,
    verificación, horarios, bloqueos) antes y después.
    """
    async with TestSession() as sesion:
        await seed_demo.seed(sesion)
        await _purgar_agenda_publica(sesion)
        await _purgar_clinica(sesion)
        await _purgar_caja(sesion)
        await _purgar_pagos(sesion)
        await _purgar_os(sesion)
        await _purgar_lista_espera(sesion)
        await sesion.commit()
    yield
    async with TestSession() as sesion:
        await _purgar_agenda_publica(sesion)
        await _purgar_clinica(sesion)
        await _purgar_caja(sesion)
        await _purgar_pagos(sesion)
        await _purgar_os(sesion)
        await _purgar_lista_espera(sesion)
        await sesion.execute(delete(AvisoEnvio))
        await sesion.execute(delete(Turno))
        await sesion.execute(delete(Paciente).where(Paciente.id != ID_PACIENTE_DEMO))
        await sesion.execute(delete(SesionRefresh))
        await sesion.execute(delete(AuditoriaLog))
        await sesion.commit()


async def _purgar_agenda_publica(sesion: AsyncSession) -> None:
    """Limpia las tablas C-03 (orden: sin dependencias entre sí)."""
    await sesion.execute(delete(VerificacionPublica))
    await sesion.execute(delete(ClaveIdempotencia))
    await sesion.execute(delete(Bloqueo))
    await sesion.execute(delete(HorarioProfesional))


async def _purgar_caja(sesion: AsyncSession) -> None:
    """Limpia las tablas C-09 en orden hijo→padre (vía SQL, sin modelos).

    Los modelos `MovimientoCaja`/`CierreDiario` llegan en la parte 2
    (GREEN); la purga usa SQL directo contra la migración 011 para
    aislar los tests RED (precedente `_purgar_clinica` C-07).
    """
    await sesion.execute(text("DELETE FROM movimiento_caja"))
    await sesion.execute(text("DELETE FROM cierre_diario"))


async def _purgar_pagos(sesion: AsyncSession) -> None:
    """Limpia la tabla C-08 `pago` vía SQL (el modelo llega en GREEN).

    Pre-fase: restos de una corrida interrumpida. Post-fase: antes del
    `delete(Turno)` (el FK es `SET NULL`, el orden igual es explícito).
    """
    await sesion.execute(text("DELETE FROM pago"))


async def _purgar_clinica(sesion: AsyncSession) -> None:
    """Limpia las tablas C-07 en orden hijo→padre (vía SQL, sin modelos).

    Los modelos `clinica.py` llegan en la parte 2 (GREEN); la purga usa
    SQL directo contra la migración 008 para aislar los tests RED.
    """
    await sesion.execute(text("DELETE FROM plan_tratamiento"))
    await sesion.execute(text("DELETE FROM presupuesto_item"))
    await sesion.execute(text("DELETE FROM presupuesto"))
    await sesion.execute(text("DELETE FROM evolucion"))
    await sesion.execute(text("DELETE FROM odontograma_entry"))
    await sesion.execute(text("DELETE FROM ficha"))
    # Versiones de catálogo simuladas por los tests (v1 es seed de la 008).
    await sesion.execute(
        text("DELETE FROM catalogo_odontograma_estado WHERE version > 1")
    )


@pytest_asyncio.fixture()
async def cliente(app) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


# --- Helpers C-02 (task 1.8): usuario sintético + login (R0, Argon2id) ---

LOGIN_URL = "/api/v1/auth/login"

# Credencial compartida para los tests de agenda C-01 (todos sintéticos).
EMAIL_AGENDA_FICTICIO = "agenda.ficticia@consultorio.example"
PASSWORD_AGENDA_FICTICIA = "Ficticia-Agenda-1234-no-real"


async def crear_usuario_ficticio(
    email: str, password: str, rol: str = "recepcion"
) -> None:
    """Inserta un usuario interno sintético con hash Argon2id real.

    Idempotente: purga restos previos del mismo email (una corrida
    interrumpida no debe romper la siguiente).
    """
    async with TestSession() as sesion:
        await sesion.execute(delete(Usuario).where(Usuario.email == email))
        sesion.add(
            Usuario(
                email=email,
                password_hash=hashear_password(password),
                rol=rol,
                activo=True,
            )
        )
        await sesion.commit()


async def eliminar_usuario_ficticio(email: str) -> None:
    """Self-cleanup (la cascada purga sus sesiones; auditoría la purga `_aislar`)."""
    async with TestSession() as sesion:
        await sesion.execute(delete(Usuario).where(Usuario.email == email))
        await sesion.commit()


async def obtener_access(cliente: AsyncClient, email: str, password: str) -> str:
    """Login contra la app de test; retorna el access token (o falla)."""
    login = await cliente.post(LOGIN_URL, json={"email": email, "password": password})
    assert login.status_code == 200
    return str(login.json()["access_token"])


@pytest_asyncio.fixture()
async def cliente_autenticado(
    cliente: AsyncClient,
) -> AsyncGenerator[AsyncClient, None]:
    """Cliente con JWT de recepción (para la suite C-01, hoy protegida)."""
    await crear_usuario_ficticio(EMAIL_AGENDA_FICTICIO, PASSWORD_AGENDA_FICTICIA)
    cliente.headers["Authorization"] = (
        f"Bearer {await obtener_access(cliente, EMAIL_AGENDA_FICTICIO, PASSWORD_AGENDA_FICTICIA)}"
    )
    yield cliente
    cliente.headers.pop("Authorization", None)
    await eliminar_usuario_ficticio(EMAIL_AGENDA_FICTICIO)


# --- C-06 recordatorios WhatsApp (parte 1 RED; Fake inyectable, R0/R5/R6) ---

# Teléfonos 100 % sintéticos con el prefijo reservado de la KB (R0).
# En asserts/logs solo aparece `hash_destino(tel)` (R6, Ley 25.326).
TEL_WA_FICTICIO_1 = "+54 9 11 15-000-0001"
TEL_WA_FICTICIO_2 = "+54 9 11 15-000-0002"
TEL_WA_FICTICIO_3 = "+54 9 11 15-000-0003"


def hash_destino(e164: str) -> str:
    """`sha256(tel)[:12]`: única referencia al destinatario (R6)."""
    return sha256(e164.encode("utf-8")).hexdigest()[:12]


class FakeWaError(Exception):
    """Fallo programable del Fake (5xx/timeout → reintenta; 4xx → fallido)."""

    def __init__(self, mensaje: str, estado_http: int = 500) -> None:
        super().__init__(mensaje)
        self.estado_http = estado_http


class FakeWhatsAppTransport:
    """Doble de `WhatsAppTransport` solo para tests (R5: jamás red real).

    `fallos`: pasos programables por envío (`5xx`/`timeout`/`4xx`/`ok`);
    agotada la lista responde ok. Registra `llamadas` (solo hashes, R6)
    para los asserts de exactamente-una-vez. La parte 2 (GREEN) inyecta
    este Fake al scheduler/worker vía `WA_TRANSPORT=fake`.
    """

    def __init__(self, fallos: list[str] | None = None) -> None:
        self._fallos: list[str] = list(fallos or [])
        self.llamadas: list[dict[str, object]] = []
        self._seq: int = 0

    @property
    def fallos_restantes(self) -> int:
        return len(self._fallos)

    async def enviar(
        self, *, destino_hash: str, plantilla: str, variables: dict[str, str]
    ) -> str:
        """Un intento de envío; retorna `proveedor_msg_id` ficticio o falla."""
        modo = self._fallos.pop(0) if self._fallos else "ok"
        self._seq += 1
        if modo == "ok":
            proveedor_id = f"wamid.ficticio-{self._seq:04d}"
            self.llamadas.append(
                {
                    "destino_hash": destino_hash,
                    "plantilla": plantilla,
                    "proveedor_msg_id": proveedor_id,
                    # C-14: variables registradas para asserts 1-a-1 (R6:
                    # solo slot propio del destinatario, jamás otros).
                    "variables": variables,
                }
            )
            return proveedor_id
        if modo == "4xx":
            raise FakeWaError("numero_invalido_ficticio", 400)
        raise FakeWaError(f"fallo_transitorio_ficticio_{modo}", 504)


@pytest.fixture()
def transporte_fake() -> FakeWhatsAppTransport:
    """Fake sano (cero fallos): cada `enviar` retorna `wamid.ficticio-NNNN`."""
    return FakeWhatsAppTransport()


# --- C-07 ficha clínica (parte 1 RED; fixtures 100 % sintéticas, R0) ---

# Usuarios internos ficticios por rol (idempotentes vía crear_usuario_ficticio).
PASSWORD_HC_FICTICIA = "Ficticia-HC-1234-no-real"
EMAIL_ADMIN_HC = "admin.hc.ficticio@consultorio.example"
EMAIL_ODONTOLOGO_HC = "odontologo.hc.ficticio@consultorio.example"
EMAIL_ODONTOLOGO_HC_2 = "odontologo.hc.dos.ficticio@consultorio.example"
EMAIL_RECEPCION_HC = "recepcion.hc.ficticia@consultorio.example"
EMAILS_HC = (
    EMAIL_ADMIN_HC,
    EMAIL_ODONTOLOGO_HC,
    EMAIL_ODONTOLOGO_HC_2,
    EMAIL_RECEPCION_HC,
)

# Pacientes ficticios: DNIs/teléfonos sintéticos con prefijo reservado (R0).
DNI_HC_SIN_CONSENTIMIENTO = "88200101"
DNI_HC_CON_CONSENTIMIENTO = "88200102"
TEL_HC_FICTICIO = "+54 9 11 5000-0007"
TEL_HC_FICTICIO_NUEVO = "+54 9 11 5000-0008"

FICHAS_URL = "/api/v1/fichas"
PRESUPUESTOS_URL = "/api/v1/presupuestos"
PLANES_URL = "/api/v1/planes"


def clave_hce_prueba() -> str:
    """Clave de cifrado HCE solo desde env del proceso (R7).

    Falla con `skip` si falta: ningún secreto vive en archivos ni en el
    repo; el runner la exporta (`HCE_CIFRADO_KEY` ficticia de 32+ bytes).
    """
    clave = os.environ.get("HCE_CIFRADO_KEY", "")
    if len(clave) < 32:
        pytest.skip("HCE_CIFRADO_KEY de 32+ bytes requerida en env (R7)")
    return clave


async def crear_paciente_hc(
    *,
    nombre: str,
    dni: str,
    telefono: str = TEL_HC_FICTICIO,
    consentimiento: bool = False,
) -> uuid.UUID:
    """Paciente ficticio directo en DB (el canal de pacientes es de la parte 2)."""
    async with TestSession() as sesion:
        await sesion.execute(delete(Paciente).where(Paciente.dni == dni))
        paciente = Paciente(
            nombre=nombre,
            dni=dni,
            telefono=telefono,
            consentimiento_hc=consentimiento,
        )
        sesion.add(paciente)
        await sesion.commit()
        return paciente.id


async def contar_filas_clinicas(tabla: str) -> int:
    """Conteo directo (la API clínica aún no existe en RED)."""
    async with TestSession() as sesion:
        return int(
            await sesion.scalar(text(f"SELECT count(*) FROM {tabla}")) or 0
        )


async def jwt_para(cliente: AsyncClient, email: str) -> str:
    """Access token del usuario ficticio pedido (ya creado por `usuarios_hc`)."""
    return await obtener_access(cliente, email, PASSWORD_HC_FICTICIA)


@pytest_asyncio.fixture()
async def usuarios_hc() -> AsyncGenerator[None, None]:
    """Admin + 2 odontólogos + recepción ficticios; self-cleanup en RED."""
    await crear_usuario_ficticio(EMAIL_ADMIN_HC, PASSWORD_HC_FICTICIA, "admin")
    await crear_usuario_ficticio(
        EMAIL_ODONTOLOGO_HC, PASSWORD_HC_FICTICIA, "odontologo"
    )
    await crear_usuario_ficticio(
        EMAIL_ODONTOLOGO_HC_2, PASSWORD_HC_FICTICIA, "odontologo"
    )
    await crear_usuario_ficticio(
        EMAIL_RECEPCION_HC, PASSWORD_HC_FICTICIA, "recepcion"
    )
    yield
    for email in EMAILS_HC:
        await eliminar_usuario_ficticio(email)


# --- C-08 seña Mercado Pago (parte 1 RED; Fake inyectable, R0/R5/R6/R7) ---

# Pagador 100 % ficticio: viaja en los avisos de prueba para demostrar que
# jamás se loguea ni se devuelve (R6, Ley 25.326). R0: dominio reservado.
PAGADOR_EMAIL_FICTICIO = "pagador.sintetico@ejemplo.local"
PAGADOR_TEL_FICTICIO = "+54 9 11 5000-0099"
PAGADOR_DNI_FICTICIO = "90900999"

# Montos ARS sintéticos (R0): señas de juguete, nunca cifras reales.
MONTO_SENA_FIJO_FICTICIO = Decimal("5000.00")
MONTO_PRECIO_BASE_FICTICIO = Decimal("20000.00")
PORCENTAJE_SENA_FICTICIO = Decimal("10.00")  # 10 % de 20000 = 2000

# Secreto de firma MP solo de test (R7): el runner puede pisarlo vía env
# (`MP_WEBHOOK_SECRET`); jamás sale de la firma HMAC ni de este módulo.
SECRETO_MP_FICTICIO_POR_DEFECTO = "secreto-mp-webhook-ficticio-no-real-32b"


def secreto_mp_prueba() -> str:
    """Secreto con el que la app verificará `x-signature` en este runner.

    Lee el `MP_WEBHOOK_SECRET` de la app si ya existe (GREEN, settings 2.3);
    en RED cae al placeholder/eventual env (igual alcanza: el router aún
    no existe y todo falla con `404`).
    """
    try:
        from app.core.settings import settings as _ajustes

        valor = getattr(_ajustes, "mp_webhook_secret", None)
        if valor:
            return str(valor)
    except (ImportError, AttributeError):
        pass
    return os.environ.get("MP_WEBHOOK_SECRET", SECRETO_MP_FICTICIO_POR_DEFECTO)


class FakeMPError(Exception):
    """Fallo programable del Fake MP (caída/transitorio → degradar, R5)."""

    def __init__(self, mensaje: str, estado_http: int = 503) -> None:
        super().__init__(mensaje)
        self.estado_http = estado_http


class FakeMercadoPagoClient:
    """Doble de `MercadoPagoClient` solo para tests (R5: jamás red real).

    Contrato que la parte 2 (GREEN) debe honrar (`MP_CLIENT=fake` inyecta
    ESTA instancia vía `dependency_overrides`: los tests programan pagos
    y la app debe consultarlos en vez de creerle al cuerpo del aviso):
    - `programar_pago(mp_payment_id, estado, monto)`: fija lo que
      `obtener_pago` devolverá (`aprobado`|`rechazado`|`pendiente`).
    - `crear_preferencia(*, monto, moneda, metadata)` → dict con `id` e
      `init_point` ficticios (registra `llamadas` para asserts de reuso).
    - `obtener_pago(mp_payment_id)` → dict o `None` (desconocido).
    - `programar_caida()` → desde entonces todo raise `FakeMPError`.
    Montos ARS sintéticos; el pagador ficticio jamás se persiste (R0/R6).
    """

    def __init__(self) -> None:
        self._pagos: dict[str, dict[str, Any]] = {}
        self._caido = False
        self.llamadas: list[dict[str, Any]] = []
        self._seq = 0

    def programar_pago(
        self,
        mp_payment_id: str,
        estado: str = "aprobado",
        monto: Decimal = MONTO_SENA_FIJO_FICTICIO,
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Fija lo que `obtener_pago` devolverá (C-14: `metadata` porta
        `oferta_espera_id`; los callers previos siguen intactos)."""
        self._pagos[mp_payment_id] = {
            "id": mp_payment_id,
            "estado": estado,
            "monto": monto,
            "moneda": "ARS",
            "metadata": dict(metadata or {}),
        }

    def programar_caida(self) -> None:
        self._caido = True

    async def crear_preferencia(
        self,
        *,
        monto: Decimal,
        moneda: str,
        metadata: dict[str, str],
    ) -> dict[str, Any]:
        if self._caido:
            raise FakeMPError("mp_caido_ficticio", 503)
        self._seq += 1
        preferencia = {
            "id": f"pref-ficticia-{self._seq:04d}",
            "init_point": f"https://link-ficticio-mp.ejemplo.local/{self._seq:04d}",
            "monto": monto,
            "moneda": moneda,
            "metadata": dict(metadata),
        }
        self.llamadas.append({"operacion": "crear_preferencia", **preferencia})
        return preferencia

    async def obtener_pago(self, mp_payment_id: str) -> dict[str, Any] | None:
        if self._caido:
            raise FakeMPError("mp_caido_ficticio", 503)
        self.llamadas.append(
            {"operacion": "obtener_pago", "mp_payment_id": mp_payment_id}
        )
        pago = self._pagos.get(mp_payment_id)
        return dict(pago) if pago is not None else None


@pytest.fixture()
def mp_fake() -> FakeMercadoPagoClient:
    """Fake MP sano por test (sin pagos programados ni caídas)."""
    return FakeMercadoPagoClient()


def inyectar_mp_fake(app: Any, fake: FakeMercadoPagoClient) -> None:
    """Expone el Fake programable a la app (seam que GREEN debe honrar).

    Contrato para la parte 2: con `MP_CLIENT=fake` los routers/servicios
    de cobro prefieren `app.state.mp_fake` cuando existe (es la instancia
    que cada test programa). En RED no hay lector → no-op y los endpoints
    responden `404` (rojo genuino).
    """
    app.state.mp_fake = fake


def firmar_aviso_mp(
    *, secreto: str, mp_payment_id: str, request_id: str, ts: str
) -> str:
    """Cabecera `x-signature` MP: `ts=...,v1=HMAC-SHA256(secreto, base)`."""
    import hashlib
    import hmac

    base = f"id:{mp_payment_id};request-id:{request_id};ts:{ts};"
    v1 = hmac.new(secreto.encode("utf-8"), base.encode("utf-8"), hashlib.sha256)
    return f"ts={ts},v1={v1.hexdigest()}"


def cuerpo_aviso_mp(
    mp_payment_id: str,
    *,
    email_pagador: str = PAGADOR_EMAIL_FICTICIO,
    telefono_pagador: str = PAGADOR_TEL_FICTICIO,
    dni_pagador: str = PAGADOR_DNI_FICTICIO,
) -> dict[str, Any]:
    """Aviso `payment` sintético (la PII solo prueba que jamás se loguea)."""
    return {
        "type": "payment",
        "data": {"id": mp_payment_id},
        "pagador": {
            "email": email_pagador,
            "telefono": telefono_pagador,
            "dni": dni_pagador,
        },
    }


def extraer_token_pago(turno_id: uuid.UUID, token_publico: str) -> tuple[str, str]:
    """`(token, firma)` del link opaco C-03 para `GET /pagar/:token`.

    Parsea `url_pago_para` (única fuente del formato): el path final es el
    `:token` y `?firma=` su firma HMAC. GREEN debe aceptar ese par.
    """
    from app.services.reserva_publica import url_pago_para

    url = url_pago_para(turno_id, token_publico)
    ruta, _, query = url.partition("?")
    token = ruta.rsplit("/", 1)[-1]
    firma = query.split("=", 1)[1]
    return token, firma


# --- C-09 caja y cierre diario (parte 1 RED; fixtures 100 % sintéticas, R0) ---

# Montos ARS de juguete para la conciliacion (R0: nunca cifras reales).
MONTO_CAJA_MP_DECLARADO = Decimal("10000.00")
MONTO_CAJA_MP_ACREDITADO = Decimal("8000.00")
MONTO_CAJA_CUADRADO = Decimal("8000.00")


async def crear_pago_acreditado_ficticio(
    *,
    monto: Decimal,
    fecha_operativa: datetime,
    mp_payment_id: str,
) -> uuid.UUID:
    """Pago `acreditado` sintético directo en DB (fuente de conciliación).

    La fecha operativa del cierre se lee de `webhook_recibido_at`
    (mediodía UTC = mañana ART, mismo día calendario — supuesto que la
    parte 2 GREEN honra en `caja.py`). Self-cleanup vía `_purgar_pagos`.
    """
    async with TestSession() as sesion:
        pago = Pago(
            paciente_id=None,
            turno_id=None,
            presupuesto_id=None,
            monto=monto,
            moneda="ARS",
            metodo="mercadopago",
            estado="acreditado",
            mp_payment_id=mp_payment_id,
            mp_preference_id=f"pref-ficticia-{mp_payment_id}",
            webhook_recibido_at=fecha_operativa,
        )
        sesion.add(pago)
        await sesion.commit()
        return pago.id


# --- C-13 validación OS preventiva (parte 1 RED; fixtures 100 % sintéticas, R0) ---

# Dos OS 100 % ficticias con nomenclador/topes jsonb versionados (R0: jamás
# nombres, códigos ni coberturas reales; el catálogo demo aporta las
# prestaciones `Limpieza`/`Consulta` como códigos sintéticos).
OS_FICTICIA_ANDINA = "Obra Social Ficticia Andina"
OS_FICTICIA_AUSTRAL = "Prepaga Ficticia Austral"
CODIGO_OS_ANDINA = "OS-ANDINA-FICT"
CODIGO_OS_AUSTRAL = "PREP-AUSTRAL-FICT"

# Nros. de afiliado 100 % sintéticos (R0/R6: en API solo últimos 4; en
# tests son sondas de PII que jamás deben aparecer en responses/diffs/logs).
NRO_AFILIADO_FICTICIO_1 = "AF-FICT-0001-XXXX-1234"
NRO_AFILIADO_FICTICIO_2 = "AF-FICT-0002-XXXX-5678"
NRO_AFILIADO_FICTICIO_3 = "AF-FICT-0003-XXXX-9012"

DNI_OS_FICTICIO_1 = "88300101"
DNI_OS_FICTICIO_2 = "88300102"
TEL_OS_FICTICIO = "+54 9 11 5000-0031"


def nomenclador_andino_v1() -> dict[str, object]:
    """Nomenclador ficticio v1: `limpieza` cubre, `consulta` fuera."""
    return {
        "limpieza": {"cubre": True, "copago": 0, "frecuencia": "2-anual"},
        "endodoncia": {"cubre": True, "copago": 1500, "frecuencia": "1-anual"},
    }


def topes_andinos_v1() -> dict[str, object]:
    """Topes ficticios v1 (montos de juguete, R0)."""
    return {"monto_anual": 50000, "cantidad_limpieza_anual": 2}


async def _purgar_os(sesion: AsyncSession) -> None:
    """Limpia las tablas C-13 en orden hijo→padre (vía SQL, sin modelos).

    Los modelos `obra_social.py` llegan en la parte 2 (GREEN); la purga
    usa SQL directo contra la migración 012 para aislar los tests RED
    (precedente `_purgar_clinica` C-07).
    """
    await sesion.execute(text("DELETE FROM validacion_cobertura"))
    await sesion.execute(text("DELETE FROM afiliacion_os"))
    await sesion.execute(text("DELETE FROM obra_social"))


# --- C-14 lista de espera inteligente (parte 1 RED; 100 % sintético, R0) ---

LISTA_ESPERA_URL = "/api/v1/lista-espera"

# Pacientes ficticios extra (el demo vive en `ID_PACIENTE_DEMO`): DNIs y
# teléfonos sintéticos con prefijo reservado; en asserts son sondas de
# PII que jamás deben aparecer fuera de su propio slot (R0/R6).
DNI_ESPERA_FICTICIO_1 = "88400101"
DNI_ESPERA_FICTICIO_2 = "88400102"
DNI_ESPERA_FICTICIO_3 = "88400103"
DNI_ESPERA_FICTICIO_4 = "88400104"
TEL_ESPERA_FICTICIO_1 = "+54 9 11 5000-0041"
TEL_ESPERA_FICTICIO_2 = "+54 9 11 5000-0042"
TEL_ESPERA_FICTICIO_3 = "+54 9 11 5000-0043"


async def _purgar_lista_espera(sesion: AsyncSession) -> None:
    """Limpia las tablas C-14 en orden hijo→padre (vía SQL, sin modelos).

    Los modelos llegan en la parte 2 (GREEN); la purga usa SQL directo
    contra la migración 013 para aislar los tests RED (precedente
    `_purgar_clinica` C-07). Sin FK hacia `turno` (snapshot): el orden
    contra `delete(Turno)` es libre.
    """
    await sesion.execute(text("DELETE FROM oferta_espera"))
    await sesion.execute(text("DELETE FROM lista_espera"))


async def crear_paciente_espera(
    *,
    nombre: str,
    dni: str,
    telefono: str,
    sin_whatsapp: bool = False,
) -> uuid.UUID:
    """Paciente ficticio directo en DB (el alta de espera es staff, C-14).

    Idempotente por `dni` (una corrida interrumpida no rompe la
    siguiente); self-cleanup vía `_aislar_turnos` + `_purgar_lista_espera`.
    """
    async with TestSession() as sesion:
        await sesion.execute(delete(Paciente).where(Paciente.dni == dni))
        paciente = Paciente(
            nombre=nombre,
            dni=dni,
            telefono=telefono,
            consentimiento_hc=False,
            sin_whatsapp=sin_whatsapp,
        )
        sesion.add(paciente)
        await sesion.commit()
        return paciente.id


async def crear_obra_social_ficticia(
    *,
    nombre: str = OS_FICTICIA_ANDINA,
    codigo: str = CODIGO_OS_ANDINA,
    version: int = 1,
) -> uuid.UUID:
    """OS ficticia directa en DB (el CRUD de OS es interno en v1)."""
    import json

    async with TestSession() as sesion:
        os_id = uuid.uuid4()
        await sesion.execute(
            text(
                "INSERT INTO obra_social "
                "(id, nombre, codigo, activa, nomenclador_version, "
                "nomenclador, topes) "
                "VALUES (:id, :nombre, :codigo, TRUE, :version, "
                "CAST(:nomenclador AS JSONB), CAST(:topes AS JSONB)) "
                "ON CONFLICT (codigo) DO UPDATE SET nombre = EXCLUDED.nombre"
            ),
            {
                "id": os_id,
                "nombre": nombre,
                "codigo": codigo,
                "version": version,
                "nomenclador": json.dumps(nomenclador_andino_v1()),
                "topes": json.dumps(topes_andinos_v1()),
            },
        )
        await sesion.commit()
        fila = (
            await sesion.execute(
                text("SELECT id FROM obra_social WHERE codigo = :codigo"),
                {"codigo": codigo},
            )
        ).scalar_one()
        assert isinstance(fila, uuid.UUID)
        return fila


async def crear_afiliacion_ficticia(
    *,
    paciente_id: uuid.UUID,
    obra_social_id: uuid.UUID,
    nro: str = NRO_AFILIADO_FICTICIO_1,
) -> uuid.UUID:
    """Afiliación vigente ficticia directa en DB (self-cleanup vía `_purgar_os`)."""
    from datetime import date

    async with TestSession() as sesion:
        afiliacion_id = uuid.uuid4()
        await sesion.execute(
            text(
                "INSERT INTO afiliacion_os "
                "(id, paciente_id, obra_social_id, nro_afiliado, "
                "vigencia_desde, vigencia_hasta, vigente) "
                "VALUES (:id, :paciente, :os, :nro, :desde, NULL, TRUE)"
            ),
            {
                "id": afiliacion_id,
                "paciente": paciente_id,
                "os": obra_social_id,
                "nro": nro,
                "desde": date(2026, 1, 1),
            },
        )
        await sesion.commit()
        return afiliacion_id
