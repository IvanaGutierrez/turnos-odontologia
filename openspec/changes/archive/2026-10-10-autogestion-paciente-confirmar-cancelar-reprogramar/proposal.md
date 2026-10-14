# Proposal — C-05 `autogestion-paciente-confirmar-cancelar-reprogramar`

## Why

El paciente hoy no puede autogestionar su turno sin llamar: verlo, confirmarlo, cancelarlo o reprogramarlo exige pasar por recepción. Este change abre la autogestión con el `token_publico` (US-003), cerrando el camino crítico del MVP antes de los recordatorios WhatsApp (C-06).

## What Changes

- `GET /api/v1/turnos/publicos/:token` — ver turno propio con campos mínimos (sin login).
- `POST /api/v1/turnos/publicos/:token/confirmar` — `reservado→confirmado` (idempotente; con seña pendiente → 422 + `url_pago`).
- `POST /api/v1/turnos/publicos/:token/cancelar` — `reservado|confirmado→cancelado` si respeta `CANCEL_MIN_HOURS` (default 12 h); fuera de término → 422 con política del consultorio.
- `POST /api/v1/turnos/publicos/:token/reprogramar` — reutiliza validación de slots y enlace de C-04 (original → `reprogramado`, nuevo conserva `token_publico`); destino ocupado → 409 + alternativos sin mutar.
- `POST /api/v1/turnos/<id>/rotar-token` (protegido, staff) — genera nuevo `token_publico` e invalida el anterior ante sospecha de fuga (RN-PU-02).
- Máquina de estados consolidada: `reservado|confirmado|presente|atendido|cancelado|ausente|reprogramado`; el alias transitorio `en_sala` se elimina (`presente` canónico, diferido desde C-04).
- Migración 005 mínima: columnas de cancelación + consolidación del check de estados (ver design decisión 2).

## Capabilities

### New Capabilities

- `agenda/autogestion-paciente`: autogestión del turno con token público sin login — ver-propio minimizado, confirmar/cancelar con antelación/reprogramar por enlace, rotación de token por staff, máquina de estados consolidada y 404 idéntico anti-enumeración.

### Modified Capabilities

_(ninguna — `agenda/crear-turno`, `agenda/reserva-publica` y `agenda/agenda-recepcion` no cambian sus REQUIREMENTS: este change reutiliza el shape `201`/`409`/`422`, el enlace de reprogramación RN-AG-07 y la normalización `en_sala→presente` ya especificados; la eliminación física de `en_sala` no altera el comportamiento observable contratado)_

## Impact

- Nuevo: router público `turnos_autogestion` (sin JWT, con rate limit por IP como C-03) + endpoint protegido de rotación; servicio `autogestion` (ver/confirmar/cancelar/reprogramar/rotar); schemas públicos minimizados; settings `CANCEL_MIN_HOURS=12`, `CANCEL_POLICY_TEXT`; migración 005.
- Reusa sin modificar: exclusión GiST C-01 (última línea, R3), pre-chequeo + `409` con alternativos mismo shape, validación de slots C-03/C-04, auditoría C-02 (`turno_confirmado`, `turno_cancelado`, `turno_reprogramado`, `token_rotado`, sin PII), sanitización R6.
- No-objetivos explícitos: recordatorios/confirmación WhatsApp (C-06/C-12), cobro de seña MP (C-08 — aquí solo se respeta `requiere_sena` sin cobrar), ficha/odontograma (C-07), frontend (C-10).
