"""Logger estructurado con sanitización de PII (R6, Ley 25.326 minimización).

Nunca se loguean DNI, teléfonos ni historia clínica en claro.
"""

import logging
import re
from typing import Any

# E.164 AR (+54...) y secuencias de 7-8 dígitos (posible DNI).
_PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\+54[\d\s\-.]{6,18}"),
    re.compile(r"(?<!\d)\d{7,8}(?!\d)"),
)


def sanitize(message: str) -> str:
    """Reemplaza posibles PII por marcador (función pura, testeable)."""
    redacted = message
    for pattern in _PII_PATTERNS:
        redacted = pattern.sub("[PII-REDACTED]", redacted)
    return redacted


class PiiRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = sanitize(str(record.msg))
        if record.args:
            record.args = tuple(
                sanitize(str(a)) if isinstance(a, str) else a
                for a in record.args  # type: ignore[union-attr]
            )
        return True


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not any(isinstance(f, PiiRedactingFilter) for f in logger.filters):
        logger.addFilter(PiiRedactingFilter())
    return logger


def extra_sanitizado(extra: dict[str, Any]) -> dict[str, Any]:
    """Sanitiza un dict de contexto antes de loguearlo (claves sensibles fuera)."""
    omitidas = {"dni", "telefono", "historia_clinica", "hc"}
    return {k: ("[PII-REDACTED]" if k in omitidas else v) for k, v in extra.items()}
