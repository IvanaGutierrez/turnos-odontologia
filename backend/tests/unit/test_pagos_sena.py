"""C-08 unitario: cálculo de seña, metadata y normalización (R1/R5).

Puros y deterministas (sin DB ni red): fijo gana a %, % sobre base,
sin config → error visible, metadata con/sin presupuesto y el
vocabulario MP↔dominio (desconocido → pendiente, nunca acredita).
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.infrastructure.mercadopago.client import normalizar_estado
from app.models.entidades import Prestacion
from app.services.pagos import (
    SenaSinConfigurarError,
    calcular_sena_monto,
    metadata_para,
)


def _prestacion(
    *,
    fijo: Decimal | None = None,
    base: Decimal | None = None,
    porcentaje: Decimal | None = None,
) -> Prestacion:
    return Prestacion(
        nombre=f"Prestación Ficticia {uuid4()}",
        duracion_min=45,
        requiere_sena=True,
        precio_base=base,
        sena_monto_fijo=fijo,
        sena_porcentaje=porcentaje,
    )


def test_fijo_gana_a_porcentaje() -> None:
    prestacion = _prestacion(
        fijo=Decimal("5000.00"),
        base=Decimal("20000.00"),
        porcentaje=Decimal("10.00"),
    )
    assert calcular_sena_monto(prestacion) == Decimal("5000.00")


def test_porcentaje_sobre_base() -> None:
    prestacion = _prestacion(base=Decimal("20000.00"), porcentaje=Decimal("10.00"))
    assert calcular_sena_monto(prestacion) == Decimal("2000.00")


def test_sin_config_lanza_error_visible() -> None:
    with pytest.raises(SenaSinConfigurarError):
        calcular_sena_monto(_prestacion())


def test_sin_base_con_porcentaje_lanza_error_visible() -> None:
    with pytest.raises(SenaSinConfigurarError):
        calcular_sena_monto(_prestacion(porcentaje=Decimal("10.00")))


def test_metadata_con_y_sin_presupuesto() -> None:
    turno_id = uuid4()
    assert metadata_para(turno_id) == {"turno_id": str(turno_id)}
    presupuesto_id = uuid4()
    assert metadata_para(turno_id, presupuesto_id) == {
        "turno_id": str(turno_id),
        "presupuesto_id": str(presupuesto_id),
    }


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("aprobado", "aprobado"),
        ("approved", "aprobado"),
        ("rechazado", "rechazado"),
        ("rejected", "rechazado"),
        ("cancelled", "rechazado"),
        ("pendiente", "pendiente"),
        ("in_process", "pendiente"),
        ("raro-ficticio", "pendiente"),
        ("", "pendiente"),
    ],
)
def test_normalizar_estado_nunca_acredita_por_defecto(
    crudo: str, esperado: str
) -> None:
    assert normalizar_estado(crudo) == esperado
