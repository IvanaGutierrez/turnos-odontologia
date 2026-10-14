# Tasks — C-05 `autogestion-paciente-confirmar-cancelar-reprogramar`

> Governance MEDIO — fase PROPOSE: este archivo es el plan. Ninguna tarea se ejecuta sin aprobación explícita del usuario (`apply`). Orden TDD estricto: RED → GREEN → TRIANGULATE → REFACTOR. Todo dato sintético (R0); type hints siempre (R1); capas + Alembic con migración 005 (R2); GiST manda en el camino normal (R3); cada comportamiento con test en verde (R5); anti-enumeración + minimización Ley 25.326 (R6); env sin secretos (R7); stack fijo (R8).

## 1. Tests en ROJO primero (TDD — antes de cualquier código de producción)

- [x] 1.1 Escribir `tests/integration/test_autogestion_ver.py` (ver con token válido devuelve campos mínimos sin PII; token inválido/malformado/rotado → 404 byte-idéntico en cuerpo; respuestas y logs sin DNI/teléfono/HC/token) con fixtures sintéticas y verificar que FALLA en rojo (endpoints aún no existen).
- [x] 1.2 Escribir `tests/integration/test_autogestion_confirmar.py` (reservado→confirmado + `turno_confirmado`; duplicado idempotente 200 con una sola auditoría incluso concurrente; seña pendiente → 422 + `url_pago` sin mutar; terminal → 422; token inválido → 404 idéntico) y verificar que FALLA en rojo.
- [x] 1.3 Escribir `tests/integration/test_autogestion_cancelar.py` con freezegun (en término → cancelado + slot liberado reutilizable; fuera de término → 422 con `CANCEL_POLICY_TEXT`; duplicado idempotente; `motivo_cancelacion`/`cancelado_at` persistidos) y verificar que FALLA en rojo.
- [x] 1.4 Escribir `tests/integration/test_autogestion_reprogramar.py` (a slot libre conserva token + original `reprogramado` con enlace; a ocupado → 409 + alternativos mismo shape C-01 sin mutar; origen terminal → 422) y verificar que FALLA en rojo.
- [x] 1.5 Escribir `tests/integration/test_autogestion_rotacion.py` (staff rota → viejo 404 idéntico + nuevo 200 + `token_rotado`; sin permiso → 403 + `acceso_denegado`; transición inválida ej. atender reservado → 422; rate limit público → 429 con `Retry-After`) y verificar que FALLA en rojo.
- [x] 1.6 Fijar fixtures/`conftest.py` (Postgres real de test — GiST parcial e índice parcial no existen en SQLite —, reloj freezegun en `America/Argentina/Buenos_Aires`, fakeredis para rate limit, markers `integration`) y verificar `pytest --collect-only` lista los tests 1.1–1.5 sin ejecutarlos.

## 2. Modelos + migración 005 (GREEN mínimo para los tests 1.1–1.5)

- [x] 2.1 Extender modelo `Turno` (`motivo_cancelacion`, `cancelado_at`, eliminar `en_sala` de `ESTADOS_TURNO` manteniendo `presente` canónico) en `models/` con type hints (R1), separado de `schemas/` (R2), y verificar `mypy` limpio en `models/`.
- [x] 2.2 Escribir migración 005 vía Alembic (columnas anulables + backfill `en_sala→presente` + reescritura de `ck_turno_estado` sin `en_sala`, GiST e índice parcial intactos) y verificar `alembic upgrade head` + `downgrade -1` + re-`upgrade` sin error y GiST normal-normal intacta (doble reserva concurrente sigue → 409).
- [x] 2.3 Extender `repositories/` (búsqueda por `token_publico` solo entre estados activos para el 200, `SELECT ... FOR UPDATE` para confirmar/cancelar en carrera) con type hints y verificar `mypy` + `ruff` limpios en el dominio autogestión.

## 3. Ver/confirmar/cancelar por token (GREEN de punta a punta, con sus docs)

- [x] 3.1 Implementar servicio de autogestión ver/confirmar (resolución por token con 404 idéntico, schema público minimizado, confirmar idempotente + guarda de seña `requiere_sena` sin crear `Pago`, auditorías sin PII) + `GET /:token` y `POST /:token/confirmar` sin JWT con rate limit por IP, y verificar los tests 1.1–1.2 pasan en verde.
- [x] 3.2 Implementar servicio de cancelar (reloj inyectable, `CANCEL_MIN_HOURS` + `CANCEL_POLICY_TEXT`, idempotencia del duplicado, `turno_cancelado` sin PII) + `POST /:token/cancelar` y verificar los tests 1.3 pasan en verde.
- [x] 3.3 Documentar los contratos nuevos en docstrings/schemas (campos mínimos del ver-propio, forma del 404 idéntico, política de antelación, guarda de seña) y verificar que la lectura de los schemas permite usar la autogestión sin mirar el código.

## 4. Reprogramar por token + rotación staff + env + seed (GREEN con sus docs)

- [x] 4.1 Implementar `POST /:token/reprogramar` delegando en `reprogramar_turno` de C-04 (resolución por token + guarda de origen, mismo `409` + alternativos, enlace y token conservado) y verificar los tests 1.4 pasan en verde.
- [x] 4.2 Implementar `POST /api/v1/turnos/<id>/rotar-token` protegido (`require_role("turnos")`, `403` + `acceso_denegado` sin permiso, `token_rotado` sin PII, endpoints públicos sin rotación implícita) y verificar el bloque de rotación/transiciones/rate-limit de 1.5 pasa en verde.
- [x] 4.3 Extender `.env.example` + `settings.py` (`CANCEL_MIN_HOURS=12`, `CANCEL_POLICY_TEXT` sin valores reales, R7) y verificar la app levanta con `.env.example` como base.
- [x] 4.4 Extender `seed_demo.py` (1 turno ficticio `reservado` con token `demo-...` marcado `demo`, idempotente) y verificar doble ejecución no duplica registros.

## 5. Verificación integral (solo checks, sin código nuevo)

- [x] 5.1 Pasar `ruff`/`black`, `mypy` limpio total, `pytest --cov --cov-fail-under=80` en verde y verificar cobertura ≥80 % en el dominio nuevo, con regresión C-01…C-04 intacta (standards fastapi/sqlalchemy/testing-patterns/supabase; Postgres real + freezegun + fakeredis).
- [x] 5.2 Ejecutar suite completa en verde + `openspec validate --change autogestion-paciente-confirmar-cancelar-reprogramar` y `openspec status --change autogestion-paciente-confirmar-cancelar-reprogramar`, y verificar ambos en verde antes de pedir `/opsx:archive` (nota: el CLI usa el nombre posicional o `--change` según subcomando; usar la forma que acepte cada uno).
