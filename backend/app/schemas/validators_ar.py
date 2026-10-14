"""Validadores AR: DNI (7–8 dígitos) y teléfono E.164 AR (+54…)."""

import re

_DNI_AR: re.Pattern[str] = re.compile(r"^\d{7,8}$")
# E.164 AR: +54 + [9 móvil] + área (2-4 dígitos) + número (6-8 dígitos
# admitiendo un separador interno, ej. "+54 9 11 5000-0001").
_TEL_AR: re.Pattern[str] = re.compile(r"^\+54\s?9?\s?\d{2,4}(?:[\s\-]?\d{2,4}){1,3}$")


def validar_dni_ar(dni: str) -> str:
    """Valida DNI argentino; retorna el valor normalizado o lanza ValueError."""
    normalizado = dni.strip().replace(".", "")
    if not _DNI_AR.match(normalizado):
        raise ValueError("DNI argentino inválido: debe tener 7 u 8 dígitos")
    return normalizado


def validar_telefono_ar(telefono: str) -> str:
    """Valida teléfono E.164 AR; retorna el valor o lanza ValueError."""
    normalizado = telefono.strip()
    if not _TEL_AR.match(normalizado):
        raise ValueError("Teléfono inválido: debe ser E.164 AR (+54…)")
    return normalizado
