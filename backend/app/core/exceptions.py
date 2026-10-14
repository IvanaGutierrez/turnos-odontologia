"""Excepciones de dominio + handlers globales (respuestas consistentes, sin PII).

El shape 409 es `{problema, detalle, slots_alternativos}` donde `detalle`
nunca incluye DNI/teléfonos/HC del turno existente (R6).
"""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.logger import get_logger

logger = get_logger(__name__)


class SlotOcupadoError(Exception):
    def __init__(self, problema: str, slots_alternativos: list[dict[str, str]]) -> None:
        super().__init__(problema)
        self.problema = problema
        self.slots_alternativos = slots_alternativos


class EntidadNoEncontradaError(Exception):
    def __init__(self, entidad: str) -> None:
        super().__init__(entidad)
        self.entidad = entidad


class ValidacionARError(Exception):
    def __init__(self, campo: str) -> None:
        super().__init__(campo)
        self.campo = campo


class VentanaAgendaError(ValueError):
    """Ventana de grilla inválida o mayor al máximo (→ 422 genérico, R6)."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


class TransicionInvalidaError(Exception):
    """Transición fuera de la máquina C-04 (→ 422, estado intacto)."""

    def __init__(self, transicion: str, estado_actual: str) -> None:
        super().__init__(transicion)
        self.transicion = transicion
        self.estado_actual = estado_actual


class SobreturnoNoPermitidoError(Exception):
    """Rol sin permiso fino de sobreturno (→ 403 genérico + auditoría)."""


class FueraDeTerminoError(Exception):
    """Cancelación sin antelación mínima (→ 422 + política, sin mutar).

    Lleva las horas restantes para que el handler las exponga junto al
    texto del consultorio (`CANCEL_POLICY_TEXT`).
    """

    def __init__(self, horas_restantes: float) -> None:
        super().__init__("fuera_de_termino")
        self.horas_restantes = horas_restantes


class SenaPendienteError(Exception):
    """Confirmar bloqueado por seña sin acreditar (→ 422 + `url_pago`, C-08).

    El cobro real es C-08; aquí no se crea `Pago` ni se muta el turno.
    """

    def __init__(self, url_pago: str) -> None:
        super().__init__("sena_pendiente")
        self.url_pago = url_pago


class TipoAvisoNoPermitidoError(ValueError):
    """Aviso fuera de los 3 utility (marketing exige opt-in aparte → 422).

    C-06 solo emite `confirmacion|recordatorio_24h|aviso_3h` (RN-NO-01);
    cualquier otro tipo se rechaza sin encolar ni llamar al proveedor.
    """


async def slot_ocupado_handler(request: Request, exc: SlotOcupadoError) -> JSONResponse:
    logger.warning("slot ocupado", extra={"problema": exc.problema})
    return JSONResponse(
        status_code=409,
        content={
            "problema": exc.problema,
            "detalle": "El slot solicitado está ocupado; se ofrecen alternativas.",
            "slots_alternativos": exc.slots_alternativos,
        },
    )


async def entidad_no_encontrada_handler(
    request: Request, exc: EntidadNoEncontradaError
) -> JSONResponse:
    return JSONResponse(
        status_code=404, content={"problema": "no_encontrado", "entidad": exc.entidad}
    )


async def validacion_ar_handler(
    request: Request, exc: ValidacionARError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"problema": "validacion_ar", "campo": exc.campo},
    )


async def ventana_agenda_handler(
    request: Request, exc: VentanaAgendaError
) -> JSONResponse:
    """422 genérico: sin revelar turnos, horarios ni bloqueos (R6)."""
    logger.warning("ventana de agenda inválida")
    return JSONResponse(
        status_code=422,
        content={
            "problema": "ventana_invalida",
            "detalle": "La ventana solicitada es inválida.",
        },
    )


async def transicion_invalida_handler(
    request: Request, exc: TransicionInvalidaError
) -> JSONResponse:
    logger.warning("transición inválida", extra={"transicion": exc.transicion})
    return JSONResponse(
        status_code=422,
        content={
            "problema": "transicion_invalida",
            "detalle": "El turno no admite esa operación en su estado actual.",
        },
    )


async def sobreturno_no_permitido_handler(
    request: Request, exc: SobreturnoNoPermitidoError
) -> JSONResponse:
    """403 genérico: jamás enumera qué roles sí podrían (R6)."""
    logger.warning("sobreturno denegado")
    return JSONResponse(status_code=403, content={"detalle": "Sin permiso."})


async def fuera_de_termino_handler(
    request: Request, exc: FueraDeTerminoError
) -> JSONResponse:
    """422 con la política del consultorio (lee env directo, sin ciclos)."""
    import os

    from app.core.settings import settings

    logger.warning("cancelación fuera de término")
    return JSONResponse(
        status_code=422,
        content={
            "problema": "fuera_de_termino",
            "detalle": "El turno ya no admite cancelación en término.",
            "horas_restantes": exc.horas_restantes,
            "politica": os.environ.get(
                "CANCEL_POLICY_TEXT", settings.cancel_policy_text
            ),
        },
    )


async def sena_pendiente_handler(
    request: Request, exc: SenaPendienteError
) -> JSONResponse:
    """422 con link opaco de pago (RN-PA-02): sin mutar, sin crear `Pago`."""
    logger.warning("confirmación bloqueada por seña pendiente")
    return JSONResponse(
        status_code=422,
        content={
            "problema": "sena_pendiente",
            "detalle": "La prestación exige seña; confirmá el pago para confirmar el turno.",
            "url_pago": exc.url_pago,
        },
    )


async def tipo_aviso_no_permitido_handler(
    request: Request, exc: TipoAvisoNoPermitidoError
) -> JSONResponse:
    """422 ante marketing/otros tipos fuera de los 3 utility (RN-NO-01, R6)."""
    logger.warning("tipo de aviso vetado")
    return JSONResponse(
        status_code=422,
        content={
            "problema": "tipo_no_permitido",
            "detalle": "Solo se admiten avisos utility de turno.",
        },
    )


def detalle_error_seguro(exc: BaseException) -> dict[str, Any]:
    """Convierte una excepción a dict sin exponer atributos sensibles."""
    return {"problema": "error_interno", "tipo": type(exc).__name__}
