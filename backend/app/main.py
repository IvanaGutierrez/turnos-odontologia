"""App FastAPI (C-02 GREEN: auth JWT + RBAC + auditoría; deuda C-01 saldada).

`POST /api/v1/turnos` exige JWT válido (shape 201/409/422 intacto).
Errores HTTP con clave `detalle` (contrato de specs); sin PII (R6).
"""

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import (
    EntidadNoEncontradaError,
    FueraDeTerminoError,
    SenaPendienteError,
    SlotOcupadoError,
    SobreturnoNoPermitidoError,
    TipoAvisoNoPermitidoError,
    TransicionInvalidaError,
    ValidacionARError,
    VentanaAgendaError,
    entidad_no_encontrada_handler,
    fuera_de_termino_handler,
    sena_pendiente_handler,
    slot_ocupado_handler,
    sobreturno_no_permitido_handler,
    tipo_aviso_no_permitido_handler,
    transicion_invalida_handler,
    validacion_ar_handler,
    ventana_agenda_handler,
)
from app.core.redis_client import crear_redis_para_app
from app.core.settings import settings
from app.routers.afiliaciones import router as afiliaciones_router
from app.routers.agenda import router as agenda_router
from app.routers.auditoria import router as auditoria_router
from app.routers.auth import router as auth_router
from app.routers.autogestion import router as autogestion_router
from app.routers.caja import router as caja_router
from app.routers.config_agenda import router as config_agenda_router
from app.routers.disponibilidad import router as disponibilidad_router
from app.routers.fichas import router as fichas_router
from app.routers.lista_espera import router as lista_espera_router
from app.routers.mp_webhook import router as mp_webhook_router
from app.routers.obras_sociales import router as obras_sociales_router
from app.routers.pacientes import router as pacientes_router
from app.routers.pagar import router as pagar_router
from app.routers.presupuestos import planes_router
from app.routers.presupuestos import router as presupuestos_router
from app.routers.rbac import router as rbac_router
from app.routers.reportes import router as reportes_router
from app.routers.turnos import router as turnos_router
from app.routers.turnos_publicos import router as turnos_publicos_router
from app.routers.usuarios import router as usuarios_router
from app.routers.whatsapp_webhook import router as whatsapp_webhook_router

api_router = APIRouter(prefix=settings.api_v1_prefix)
api_router.include_router(auth_router)
api_router.include_router(rbac_router)
api_router.include_router(usuarios_router)
api_router.include_router(auditoria_router)
api_router.include_router(reportes_router)
api_router.include_router(turnos_router)
api_router.include_router(agenda_router)
api_router.include_router(config_agenda_router)
api_router.include_router(disponibilidad_router)
api_router.include_router(turnos_publicos_router)
api_router.include_router(autogestion_router)
api_router.include_router(caja_router)
api_router.include_router(fichas_router)
api_router.include_router(presupuestos_router)
api_router.include_router(planes_router)
api_router.include_router(pacientes_router)
api_router.include_router(obras_sociales_router)
api_router.include_router(afiliaciones_router)
api_router.include_router(lista_espera_router)


@api_router.get("/health", summary="Salud del API")
def health() -> dict[str, str]:
    return {"estado": "ok"}


async def validacion_request_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 sanitizado: sin eco de `input`/`ctx` (R6 — DNI/tel nunca en responses)."""
    errores = [
        {
            "campo": ".".join(str(p) for p in item.get("loc", ())),
            "mensaje": item.get("msg", ""),
            "tipo": item.get("type", ""),
        }
        for item in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "problema": "validacion",
            "detalle": "La solicitud contiene datos inválidos.",
            "errores": errores,
        },
    )


async def http_error_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """401/403/429 con clave `detalle` (contrato C-02; genéricos, sin PII)."""
    detalle = exc.detail if isinstance(exc.detail, str) else "Error."
    return JSONResponse(status_code=exc.status_code, content={"detalle": detalle})


def create_app() -> FastAPI:
    app = FastAPI(
        title="Turnos Odontología (AR)",
        version="0.2.0",
        description="Agenda odontológica con auth JWT + RBAC (C-02).",
    )
    app.add_exception_handler(SlotOcupadoError, slot_ocupado_handler)  # type: ignore[arg-type]
    app.add_exception_handler(EntidadNoEncontradaError, entidad_no_encontrada_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ValidacionARError, validacion_ar_handler)  # type: ignore[arg-type]
    app.add_exception_handler(VentanaAgendaError, ventana_agenda_handler)  # type: ignore[arg-type]
    app.add_exception_handler(TransicionInvalidaError, transicion_invalida_handler)  # type: ignore[arg-type]
    app.add_exception_handler(SobreturnoNoPermitidoError, sobreturno_no_permitido_handler)  # type: ignore[arg-type]
    app.add_exception_handler(FueraDeTerminoError, fuera_de_termino_handler)  # type: ignore[arg-type]
    app.add_exception_handler(SenaPendienteError, sena_pendiente_handler)  # type: ignore[arg-type]
    app.add_exception_handler(TipoAvisoNoPermitidoError, tipo_aviso_no_permitido_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validacion_request_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_error_handler)  # type: ignore[arg-type]
    app.include_router(api_router)
    # Webhook fuera de `/api/v1` y sin JWT (verificación HMAC propia, C-06).
    app.include_router(whatsapp_webhook_router)
    # Cobro de seña C-08 (link público + webhook MP verificado, sin JWT).
    app.include_router(pagar_router)
    app.include_router(mp_webhook_router)
    # Redis por app: real en prod, falso aislado en tests (capa de abstracción).
    app.state.redis = crear_redis_para_app()
    # Warmup de rutas (C-05): FastAPI 0.142 materializa los dependants de
    # forma diferida en el primer request que los toca. Bajo `freeze_time`
    # (tests de cancelación) `datetime` es `FakeDatetime` y pydantic no puede
    # generar el schema de los `Query` temporales (`agenda`, `disponibilidad`)
    # → `FastAPIError`. Generar el OpenAPI aquí (reloj real) deja todo el
    # caché de rutas construido; los requests congelados lo reutilizan.
    app.openapi()
    return app


app = create_app()
