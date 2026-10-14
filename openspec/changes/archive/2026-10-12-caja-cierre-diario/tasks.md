# Tasks — C-09 `caja-cierre-diario`

> Governance ALTO (dinero + bloqueo operativo) — fase PROPOSE: este archivo es el plan. Ninguna tarea se ejecuta sin aprobación explícita del usuario (`apply`). Orden TDD estricto: RED → GREEN → TRIANGULATE → REFACTOR. Todo dato sintético (montos ARS y usuarios ficticios — R0); type hints siempre (R1); capas (`models/` vs `schemas/` vs `repositories/` vs `services/` vs `routers/`) + Alembic solo para `movimiento_caja`/`cierre_diario` (R2); agenda/GiST y `pago` intactos — C-08 solo lectura (R3 N/A); cada comportamiento con test en verde: doble cierre, día cerrado, reapertura (R5, AAA, cov ≥80); montos/usuarios sin PII y conceptos sanitizados en logs (R6); `CAJA_TZ` solo env (R7); stack fijo (R8).

## 1. Tests en ROJO primero (TDD — antes de cualquier código de producción)

- [x] 1.1 Escribir `tests/integration/test_caja_movimientos.py` (ingreso/egreso por cada método → `201` + evento `movimiento_registrado`; método inválido/monto ≤0/concepto vacío → `422` sin efectos; sin JWT → `401`; odontólogo → `403`) y verificar que FALLA en rojo (router/modelos aún no existen).
- [x] 1.2 Escribir `tests/integration/test_caja_cierre.py` (cierre con MP declarado == acreditado → `cuadrado`; declarado ≠ acreditado → `con_diferencia` con `diferencia` exacta; doble cierre secuencial y concurrente mismo día/sede → `409` con UN renglón y UN evento; `GET` movimientos/cierre del día) y verificar que FALLA en rojo.
- [x] 1.3 Escribir `tests/integration/test_caja_bloqueo_reapertura.py` (movimiento en día cerrado → `422` sin efectos; movimiento en día abierto → `201`; reapertura admin con motivo → `200` + `abierto` + evento + movimiento posterior `201`; reapertura recepción/odontólogo → `403` + `reapertura_denegada` + sigue `cerrado`; reapertura de día abierto → `422`; cierre inexistente → `404`) y verificar que FALLA en rojo.
- [x] 1.4 Fijar fixtures/`conftest.py` (usuarios sintéticos admin/recepción/odontólogo, pagos `acreditado` ficticios por día/sede, montos ARS de prueba, Postgres real de test, markers `integration`) y verificar `pytest --collect-only` lista los tests 1.1–1.3 sin ejecutarlos.

## 2. Modelos + migración 011 + settings/env (GREEN mínimo para los tests 1.1–1.3)

- [x] 2.1 Crear modelos `MovimientoCaja` y `CierreDiario` en `models/` (checks de tipo/método/estado/monto, `UNIQUE(fecha, sede)` en cierre, índices `(fecha, sede)`, `pago_id` FK opcional, type hints — R1, separados de `schemas/` — R2) y verificar `mypy` limpio en `models/`.
- [x] 2.2 Escribir migración Alembic **011** `caja_cierre_diario` (`down_revision = "010_pago_comprobante"`, ambas tablas + checks + índices + UNIQUE, sin tocar agenda/`pago`/avisos) y verificar `alembic upgrade head` + `downgrade -1` + re-`upgrade` sin error, con head `010→011` y regresión C-01/C-08 intacta (doble reserva → `409`, acreditación → turno `confirmado`).
- [x] 2.3 Extender `settings.py` + `.env.example` (`CAJA_TZ` default `America/Argentina_Buenos_Aires`, solo env — R7) y recursos `caja`/`reapertura_caja` en la matriz RBAC (sin tocar recursos existentes) y verificar la app levanta y un JWT odontólogo recibe `403` en `/api/v1/caja*`.

## 3. Movimientos + consultas (GREEN de punta a punta, con sus docs)

- [x] 3.1 Implementar servicio `caja.py` — registro de movimiento (validación de método/monto/concepto, `usuario_id` del JWT, `pago_id` único por ingreso, bloqueo transaccional `FOR UPDATE` contra cierre `cerrado → 422 dia_cerrado`, sanitización del concepto — R6) y verificar los tests 1.1 pasan en verde.
- [x] 3.2 Implementar router `caja` (`POST /movimientos → 201`, `GET /movimientos?fecha&sede`, schemas Pydantic estrictos con `concepto` 1–280, errores con clave `detalle` sin PII) y verificar tests 1.1 + rama día-abierto de 1.3 en verde.
- [x] 3.3 Documentar los contratos nuevos en docstrings/schemas (catálogo de métodos, forma del movimiento, regla de día cerrado) y verificar que la lectura de los schemas permite operar la caja sin mirar el código.

## 4. Cierre + conciliación + reapertura (GREEN con sus docs)

- [x] 4.1 Implementar cierre en `caja.py` + `POST /cierre` (snapshot por método, `acreditado_mp` desde `pago` solo lectura, `diferencia`, `cuadrado|con_diferencia`, `IntegrityError→409`, `GET /cierre?fecha&sede`) y verificar los tests 1.2 pasan en verde.
- [x] 4.2 Implementar `POST /reapertura` (`require_admin()`, motivo obligatorio, `cerrado→abierto` + `reaperturas+1`, eventos `cierre_reabierto`/`reapertura_denegada`, `404`/`422` según estado) + eventos de auditoría (`movimiento_registrado|cierre_creado|cierre_reabierto|reapertura_denegada` con solo IDs/montos/estados vía `sanitizar_diff`, verificación de que ningún log contiene concepto crudo ni PII) y verificar los tests 1.3 pasan en verde.
- [x] 4.3 Extender `seed_demo.py` (2–3 movimientos sintéticos + 1 cierre `abierto` demo del día, idempotente) y verificar doble ejecución no duplica registros.

## 5. Verificación integral (solo checks, sin código nuevo)

- [x] 5.1 Pasar `ruff`/`black`, `mypy` limpio total, `pytest --cov --cov-fail-under=80` en verde y verificar cobertura ≥80 % en el dominio nuevo, con regresión C-01…C-08 intacta (standards fastapi/sqlalchemy/testing-patterns/supabase; Postgres real; cero llamadas de red real).
- [x] 5.2 Ejecutar suite completa en verde + `openspec validate --change caja-cierre-diario` y `openspec status --change caja-cierre-diario`, y verificar ambos en verde antes de pedir `/opsx:archive` (usar la forma posicional o `--change` que acepte cada subcomando).
