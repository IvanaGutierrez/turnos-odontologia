"""Plantillas mínimas + fallback email/SMS C-06 (R6 primero).

Variables permitidas (design decisión 6, Ley 25.326): solo
`{nombre_pila?, fecha, hora, sede, link_gestion}` — jamás DNI, teléfono,
historia clínica, motivo clínico ni token crudo. El destino se referencia
como `sha256(e164)[:12]` en logs, diffs y responses.

Cascada de fallback (design decisión 5, RN-NO-04): WhatsApp → email
SMTP (`SMTP_URL`) → SMS gateway (`SMS_GATEWAY_KEY`). Este módulo registra
los intentos sin PII; en este change no se abre conexión real (el piloto
opera con `WA_DRY_RUN` + receptores ficticios R0) — las URLs/keys quedan
reservadas por env para el cableado real (R7).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from app.core.logger import get_logger
from app.core.settings import settings

logger = get_logger(__name__)

# Claves utility aprobadas (cualquier otro tipo → veto 422, RN-NO-01).
# C-14 suma `oferta_lista_espera` (4.º tipo: hueco liberado a la espera).
TIPOS_UTILITY: tuple[str, ...] = (
    "confirmacion",
    "recordatorio_24h",
    "aviso_3h",
    "oferta_lista_espera",
)

# Únicas variables de plantilla (R6: nada clínico ni identificatorio).
VARIABLES_PERMITIDAS: frozenset[str] = frozenset(
    {"nombre_pila", "fecha", "hora", "sede", "link_gestion"}
)


def huella_destino(e164: str) -> str:
    """`sha256(tel)[:12]`: única referencia al destinatario (R6)."""
    return hashlib.sha256(e164.encode("utf-8")).hexdigest()[:12]


def plantilla_para(tipo: str) -> str:
    """Nombre de plantilla utility por tipo (viaja por env, design riesgo 1)."""
    if tipo == "confirmacion":
        return settings.wa_template_confirm
    if tipo == "recordatorio_24h":
        return settings.wa_template_24h
    if tipo == "aviso_3h":
        return settings.wa_template_3h
    if tipo == "oferta_lista_espera":
        return settings.wa_template_oferta
    raise ValueError(f"tipo de aviso fuera de scope: {tipo}")


def construir_variables(
    *,
    fecha: str,
    hora: str,
    sede: str,
    link_gestion: str,
    nombre_pila: str | None = None,
) -> dict[str, str]:
    """Variables mínimas de plantilla (R6: solo lo permitido)."""
    variables: dict[str, str] = {
        "fecha": fecha,
        "hora": hora,
        "sede": sede,
        "link_gestion": link_gestion,
    }
    if nombre_pila:
        variables["nombre_pila"] = nombre_pila.split()[0][:40]
    return {k: v for k, v in variables.items() if k in VARIABLES_PERMITIDAS}


def hash_payload(plantilla: str, variables: dict[str, str]) -> str:
    """sha256 del payload (trazabilidad sin PII en `aviso_envio`)."""
    crudo = json.dumps({"plantilla": plantilla, "variables": variables}, sort_keys=True)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()


def fecha_hora_corta(inicio: datetime) -> tuple[str, str]:
    """`(fecha, hora)` cortas AR para la plantilla (`dd/mm/aaaa`, `hh:mm`)."""
    return inicio.strftime("%d/%m/%Y"), inicio.strftime("%H:%M")


class RegistroFallback:
    """Receptores email/SMS de la cascada (sin red en este change).

    Registra cada intento con solo hashes (R6, auditable en tests);
    retorna un id ficticio de proveedor por canal.
    """

    def __init__(self) -> None:
        self.emails: list[dict[str, str]] = []
        self.sms: list[dict[str, str]] = []

    def reiniciar(self) -> None:
        self.emails.clear()
        self.sms.clear()

    def enviar_email(self, *, destino_hash: str, asunto: str) -> str:
        prov_id = f"email-ficticio-{len(self.emails) + 1:04d}"
        self.emails.append({"destino": destino_hash, "proveedor_id": prov_id})
        logger.info(
            "fallback email registrado",
            extra={"destino": destino_hash, "asunto": asunto},
        )
        return prov_id

    def enviar_sms(self, *, destino_hash: str) -> str:
        prov_id = f"sms-ficticio-{len(self.sms) + 1:04d}"
        self.sms.append({"destino": destino_hash, "proveedor_id": prov_id})
        logger.info("fallback sms registrado", extra={"destino": destino_hash})
        return prov_id


registro_fallback = RegistroFallback()
