"""Cifrado HCE app-level C-07 (Fernet sobre AES, `clave_id` por fila, R6/R7).

La clave vigente (`HCE_CIFRADO_KEY`, 32+ bytes, solo env) deriva una clave
Fernet vía `SHA256(raw)` → `urlsafe_b64encode` (cualquier string de 32+
bytes sirve; jamás se persiste el raw). `HCE_CIFRADO_KEY_ANTERIOR`
(opcional) abre ventana de gracia en lectura durante la rotación.

Runbook de rotación (design §Decisión 2):
1. Desplegar con ambas claves (`HCE_CIFRADO_KEY_ANTERIOR` = vieja,
   `HCE_CIFRADO_KEY` = nueva); `clave_id` nuevo = `hce-v1` (la lectura
   prueba vigente y luego anterior).
2. Re-cifrar en background por lotes (leer con anterior → escribir con
   vigente, actualizar `clave_id`); backup cifrado antes de rotar.
3. Retirar la anterior cuando cero filas queden con el `clave_id` viejo.

El plaintext jamás sale del servicio: los schemas de lectura devuelven
minimizado (o descifrado solo a tratante en exportación); jamás en logs.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.settings import settings

CLAVE_ID_VIGENTE = "hce-v1"


def _fernet_para(clave_raw: str) -> Fernet:
    """Deriva un Fernet válido desde cualquier string de 32+ bytes (R7)."""
    digest = hashlib.sha256(clave_raw.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def clave_id_vigente() -> str:
    """`clave_id` para toda fila nueva (rotación lo conserva hasta v2)."""
    return CLAVE_ID_VIGENTE


def cifrar(texto: str | None) -> bytes | None:
    """Cifra al escribir (servicio clínico); `None` → `None` (sin HCE)."""
    if texto is None:
        return None
    return _fernet_para(settings.hce_cifrado_key).encrypt(texto.encode("utf-8"))


def descifrar(datos: bytes | bytearray | memoryview | None) -> str | None:
    """Descifra solo para titular/tratante; prueba vigente y luego anterior.

    `None` → `None`. Si ninguna clave abre el token, propaga `InvalidToken`
    (el llamador responde 500 genérico sin exponer contenido, R6).
    """
    if datos is None:
        return None
    token = bytes(datos)
    try:
        return _fernet_para(settings.hce_cifrado_key).decrypt(token).decode("utf-8")
    except InvalidToken:
        anterior = settings.hce_cifrado_key_anterior
        if anterior:
            return _fernet_para(anterior).decrypt(token).decode("utf-8")
        raise
