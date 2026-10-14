"""Unitario del sanitizador de auditoría (C-02 task 2.3, R6).

`sanitizar_diff()` purga por denylist en cualquier nivel de anidado:
jamás DNI, teléfonos, HC, hashes ni tokens en `AuditoriaLog`.
"""

from app.repositories.auditoria import sanitizar_diff


def test_sanitizar_diff_purga_pii_y_secretos() -> None:
    diff = {
        "email": "recepcion.ficticia@consultorio.example",
        "dni": "90123456",
        "telefono": "+54 9 11 5000-0001",
        "password_hash": "$argon2id$secreto",
        "refresh_token": "jwt-secreto",
        "anamnesis": "texto clínico ficticio",
    }
    limpio = sanitizar_diff(diff)
    assert limpio["email"] == "recepcion.ficticia@consultorio.example"
    for clave in ("dni", "telefono", "password_hash", "refresh_token", "anamnesis"):
        assert limpio[clave] == "[REDACTED]"
    plano = str(limpio)
    assert "90123456" not in plano
    assert "jwt-secreto" not in plano


def test_sanitizar_diff_recursivo_y_case_insensitive() -> None:
    diff = {
        "turno": {"DNI": "90123456", "canal": "mostrador"},
        "lista": [{"Token": "x"}],
    }
    limpio = sanitizar_diff(diff)
    assert limpio["turno"]["DNI"] == "[REDACTED]"
    assert limpio["turno"]["canal"] == "mostrador"
    assert limpio["lista"] == [{"Token": "[REDACTED]"}]


def test_sanitizar_diff_conserva_ids_y_horarios() -> None:
    diff = {
        "profesional_id": "11111111-1111-4111-8111-111111111111",
        "inicio": "2026-11-03T10:00:00-03:00",
        "estado": "reservado",
    }
    assert sanitizar_diff(diff) == diff
