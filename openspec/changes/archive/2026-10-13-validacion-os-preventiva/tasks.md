# Tasks — C-13 `validacion-os-preventiva`

> Governance ALTO (dinero + PII sensible + decisión pre-atención) — fase PROPOSE: este archivo es el plan. Ninguna tarea se ejecuta sin aprobación explícita del usuario (`apply`). Orden TDD estricto: RED → GREEN → TRIANGULATE → REFACTOR. Datos 100 % sintéticos/ficticios: afiliados y nomencladores inventados, jamás reales (R0); hints en todo Python público (R1); capas (`models/` vs `schemas/` vs `repositories/` vs `services/` vs `routers/`, todo schema vía migración 012) (R2); solapamientos intactos (R3 N/A); cada comportamiento con test en verde pytest, cov ≥ 80 % en el módulo nuevo (R5); nro. de afiliado/DNI/teléfono/HC jamás en logs/errores/responses/`diff`s (R6); sin secretos (sin credenciales OS en v1, solo env) (R7); stack fijo (R8). Standards: fastapi (endpoint validar + CRUD afiliaciones), sqlalchemy (jsonb nomenclador versionado, GIN), testing-patterns (AAA, fixtures de nomenclador), supabase (índices jsonb/GIN).

## 1. Tests en ROJO (TDD — antes de producción)

- [x] 1.1 Escribir `tests/integration/test_validacion_os.py` (afiliado válido + práctica cubierta → `cubre` con detalle y versión; tope agotado/frecuencia excedida → `parcial` con copago; no afiliado/fuera de nomenclador → `no_cubre` + `deriva_particular=true` y turno intacto; validar nunca muta el estado del turno) y verificar que FALLA en rojo.
- [x] 1.2 Escribir `tests/integration/test_afiliaciones_crud.py` (alta `201` con nro. enmascarado en lecturas; duplicada vigente → `409`; vigencia inválida → `422`; afiliación ajena al validar → `422`; odontólogo/sin JWT → `403`/`401` + `acceso_denegado`; baja lógica) y verificar que FALLA en rojo.
- [x] 1.3 Escribir `tests/integration/test_validacion_os_privacidad.py` (barrido: ningún response/`diff`/log contiene nro. de afiliado, DNI, teléfono ni HCE — PII sintética marcada; eventos `validacion_os_registrada|afiliacion_creada|afiliacion_actualizada` consultables por admin; cambio de versión de nomenclador no altera validaciones congeladas) y verificar que FALLA en rojo.
- [x] 1.4 Fijar fixtures/`conftest.py` (2 OS ficticias con nomenclador/topes jsonb versionados, afiliaciones sintéticas vigentes/vencidas, turnos `reservado` sobre prestaciones del catálogo demo, Postgres real, markers `integration`) y verificar `pytest --collect-only` lista 1.1–1.3 sin ejecutarlos.

## 2. Modelos + migración 012 (GREEN esquema)

- [x] 2.1 Implementar modelos `ObraSocial` (nomenclador/topes `jsonb` + `nomenclador_version`), `AfiliacionOS` (paciente, OS, vigencia, baja lógica), `ValidacionCobertura` (turno, afiliación, versión congelada, resultado, detalle `jsonb`) en `models/` (solo ORM — R2) y verificar `mypy` limpio. ✅ GREEN parte 2: `app/models/obra_social.py` espejo 012; `mypy app` limpio (89 archivos).
- [x] 2.2 Escribir y aplicar migración **012** (`obra_social`, `afiliacion_os`, `validacion_cobertura` + GIN + FKs + unicidad afiliación vigente; `downgrade` completo) y verificar `alembic history` head = 012 y `downgrade -1/upgrade +1` sin pérdida.

## 3. Servicio + endpoints (GREEN comportamiento)

- [x] 3.1 Implementar servicio `validacion_os.py` + schemas (matching en 3 pasos con cortocircuito y motivos, topes/frecuencias contra historial local, `detalle` con fuente y versión, nro. de afiliado enmascarado, eventos vía `sanitizar_diff`) y verificar tests 1.1 en verde. ✅ GREEN: 5/5 `test_validacion_os.py` + TRIANGULATE (`test_validacion_os_triangulacion.py`: ajena→422, OS inactiva→422, PATCH, lista enmascarada); fix documentado en 1.1-parcial (Arrange sembraba el consumo que sus comentarios describían).
- [x] 3.2 Implementar routers `obras_sociales` (`POST /validar`) + `afiliaciones` (CRUD, recursos matriz `obras_sociales|afiliaciones`, errores genéricos `403/404/422` sin PII) + registro en `main.py`, y verificar tests 1.1–1.3 en verde. ✅ GREEN: 12/12 parte-1 + 4 triangulación = 16/16.
- [x] 3.3 Pasar `ruff`/`black`, `mypy` limpio, `pytest --cov --cov-fail-under=80` (módulo nuevo) en verde con regresión C-05/C-07/C-11 intacta (máquina de turnos, presupuestos, auditoría) y cero red real. ✅ GREEN: ruff/black limpios en archivos del change; `mypy app` 89 archivos sin issues; cov módulo nuevo 87.5 % (≥80); regresión completa 284/284 en verde.

## 4. Verificación integral (solo checks, sin código nuevo)

- [x] 4.1 Suite completa backend en verde, `openspec validate --change validacion-os-preventiva` y `openspec status --change validacion-os-preventiva` en verde antes de pedir `/opsx:archive`. ✅ GREEN: suite 284/284 (58 integration + unit, PG 5439); `validate` = "Change 'validacion-os-preventiva' is valid"; `status` = 4/4 artefactos completos. Listo para `/opsx:archive` (NO commitear/pushear sin pedido).
