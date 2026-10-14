# Tasks — C-08 `sena-mercadopago-webhook`

> Governance CRITICO (dinero real) — fase PROPOSE: este archivo es el plan. Ninguna tarea se ejecuta sin aprobación explícita del usuario (`apply`). Orden TDD estricto: RED → GREEN → TRIANGULATE → REFACTOR. Todo dato sintético, Fake MP / sandbox, jamás red real ni credenciales reales (R0); type hints siempre (R1); capas (`models/` vs `schemas/` vs `repositories/` vs `services/` vs `infrastructure/mercadopago/`) + Alembic solo para `pago` + columnas de seña (R2); agenda/GiST intacta (R3 N/A — no se tocan turnos salvo transición `reservado→confirmado` ya válida); cada comportamiento con test en verde (R5, `FakeMercadoPagoClient`, cov ≥80); sin PII del pagador en logs/errores (R6); secretos solo env + fail-fast (R7); stack fijo (R8).

## 1. Tests en ROJO primero (TDD — antes de cualquier código de producción)

- [x] 1.1 Escribir `tests/integration/test_mp_preferencia.py` (token opaco válido → `200` con `init_point` + `ARS` + `metadata.turno_id`; monto fijo gana a porcentaje; `%` sobre `precio_base`; seña sin monto → `422` sin preferencia; token inválido → `404` idéntico; segundo GET reutiliza el pendiente sin duplicar) y verificar que FALLA en rojo (router/modelo aún no existen).
- [x] 1.2 Escribir `tests/integration/test_mp_webhook_firma.py` (aviso válido verificado acredita —ver 1.3—; firma ausente/inválida/cuerpo alterado/`x-request-id` distinto → `401` genérico sin mutar pagos/turnos, sin auditar contenido, sin PII en logs) y verificar que FALLA en rojo.
- [x] 1.3 Escribir `tests/integration/test_mp_acreditacion.py` (`FakeMercadoPagoClient` pago aprobado → pago `acreditado` + turno `confirmado` + evento `pago_acreditado` + comprobante WA encolado; aviso duplicado mismo `mp_payment_id` secuencial y concurrente → `200` sin doble efecto; estado confirmado contra el Fake, no solo desde el cuerpo) y verificar que FALLA en rojo.
- [x] 1.4 Escribir `tests/integration/test_mp_rechazo.py` (pago rechazado → `rechazado` visible en `GET /pagar/:token` + reintento con mismo link sin segundo pendiente; turno sigue `reservado`; confirmar sigue `422 sena_pendiente` hasta acreditar — regresión C-05; MP caído → turno `reservado` + aviso a recepción) y verificar que FALLA en rojo.
- [x] 1.5 Fijar fixtures/`conftest.py` (`FakeMercadoPagoClient` con pagos programables aprobado/rechazado/duplicado, `MP_CLIENT=fake`, montos ARS sintéticos, pagador ficticio `pagador-sintetico`, Postgres real de test, markers `integration`) y verificar `pytest --collect-only` lista los tests 1.1–1.4 sin ejecutarlos.

## 2. Modelo + migración 009 + settings/env (GREEN mínimo para los tests 1.1–1.4)

- [x] 2.1 Crear modelo `Pago` en `models/` (estados `pendiente|acreditado|rechazado|reembolsado`, `moneda` CHECK `ARS`, UNIQUEs `mp_payment_id`/`mp_preference_id`, `webhook_recibido_at`) + columnas `Prestacion.sena_monto_fijo` / `sena_porcentaje` (CHECK 0–100), type hints (R1), separado de `schemas/` (R2), y verificar `mypy` limpio en `models/`.
- [x] 2.2 Escribir migración Alembic **009** `pago_senia_mp` (tabla `pago` + índices + checks + columnas de seña, sin tocar GiST ni tablas de agenda/C-06/C-07) y verificar `alembic upgrade head` + `downgrade -1` + re-`upgrade` sin error, con head `008→009` y regresión C-01 intacta (doble reserva concurrente sigue → `409`).
- [x] 2.3 Extender `settings.py` + `.env.example` (`MP_ACCESS_TOKEN`/`MP_WEBHOOK_SECRET` sin default + fail-fast si `MP_CLIENT=http`, `MP_CLIENT`, `MP_TIMEOUT_S`, `MP_PUBLIC_KEY?`, `SENA_*` — solo placeholders no reales, R7) y verificar la app levanta con `.env.example` como base y falla en arranque con `MP_CLIENT=http` sin secretos.

## 3. Infra MP + preferencia + GET /pagar/:token (GREEN de punta a punta, con sus docs)

- [x] 3.1 Implementar `infrastructure/mercadopago/` (protocolo `MercadoPagoClient`, `HttpMercadoPagoClient` prod con timeout + `FakeMercadoPagoClient` tests con resultados programables, constructor de preferencia con `metadata={turno_id, presupuesto_id?}` + `currency_id='ARS'`, sanitización R6) y verificar los tests 1.1 pasan en verde.
- [x] 3.2 Implementar servicio `pagos.py` (cálculo fijo-gana-a-% + `422` de configuración, upsert de UN pendiente por turno, creación/reutilización de preferencia, reintento tras rechazo sin duplicar pendiente) + `GET /pagar/:token` (verifica token opaco C-03, rate limit público RN-PU-03, expone `estado_pago` sin PII) y verificar tests 1.1 + rama rechazo/reintento de 1.4 en verde.
- [x] 3.3 Documentar los contratos nuevos en docstrings/schemas (forma de `init_point`, reglas de monto, estados del pago, claves de idempotencia) y verificar que la lectura de los schemas permite operar los pagos sin mirar el código.

## 4. Webhook verificado + acreditación + caja WA + seed (GREEN con sus docs)

- [x] 4.1 Implementar router `POST /webhooks/mercadopago` fuera de `/api/v1` (sin JWT, verificación `x-signature` obligatoria vía `compare_digest`, schemas Pydantic estrictos, confirmación de estado contra MP, transacción pago→turno→evento caja→comprobante, duplicado → `200` idempotente, upsert desde `metadata` si el pendiente no existe) y verificar los tests 1.2–1.3 pasan en verde.
- [x] 4.2 Registrar eventos de auditoría (`pago_creado|pago_acreditado|pago_rechazado` con solo `{pago_id, turno_id, monto, estado, mp_payment_id}`, evento `pago_acreditado` con payload v1 para conciliación C-09, reuso de `sanitizar_diff`, verificación de que ningún log contiene email/tarjeta/DNI/teléfono/tokens) + encolado de comprobante WA vía C-06 (degradación documentada: WA caído no revierte la acreditación) y verificar búsqueda por `turno_id` en 1.3–1.4.
- [x] 4.3 Extender `seed_demo.py` (1 prestación con seña sintética + 1 pago `acreditado` demo con `mp_payment_id` ficticio `demo-*`, idempotente) y verificar doble ejecución no duplica registros.

## 5. Verificación integral (solo checks, sin código nuevo)

- [x] 5.1 Pasar `ruff`/`black`, `mypy` limpio total, `pytest --cov --cov-fail-under=80` en verde y verificar cobertura ≥80 % en el dominio nuevo, con regresión C-01…C-07 intacta (standards fastapi/sqlalchemy/testing-patterns/supabase; Postgres real + Fake MP; cero llamadas de red real).
- [x] 5.2 Ejecutar suite completa en verde + `openspec validate --change sena-mercadopago-webhook` y `openspec status --change sena-mercadopago-webhook`, y verificar ambos en verde antes de pedir `/opsx:archive` (usar la forma posicional o `--change` que acepte cada subcomando).
