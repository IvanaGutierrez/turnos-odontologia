# Tasks — C-01 `crear-turno-evitando-solapamientos-profesional-sillon-box`

> Governance CRITICO — fase PROPOSE: este archivo es el plan. Ninguna tarea se ejecuta sin aprobación explícita del usuario (`apply`). Orden TDD estricto: RED → GREEN → TRIANGULATE → REFACTOR. Todo dato de prueba sintético (R0).

## 1. Tests en ROJO primero (TDD — antes de cualquier código de producción)

- [x] 1.1 Escribir `tests/integration/test_turno_concurrente_mismo_profesional_409.py` (`test_crear_turno_profesional_solapado_concurrente_uno_gana`) con doble POST simultáneo y verificar que FALLA en rojo (sin código: error de colección/import).
- [x] 1.2 Escribir `tests/integration/test_turno_concurrente_mismo_sillon_409.py` (`test_crear_turno_sillon_solapado_concurrente_uno_gana`) y verificar que FALLA en rojo.
- [x] 1.3 Escribir `tests/integration/test_turno_fin_calculado_desde_prestacion.py` (`test_crear_turno_valido_calcula_fin`, `test_crear_turno_fin_libre_sin_motivo_se_ignora`, `test_crear_turno_adyacente_permitido`) y verificar que FALLAN en rojo.
- [x] 1.4 Escribir `tests/integration/test_turno_validacion_ar_422.py` (`test_crear_turno_dni_invalido_422`, `test_crear_turno_telefono_no_e164_422`) con datos sintéticos y verificar que FALLAN en rojo.
- [x] 1.5 Escribir `tests/integration/test_turno_error_sin_pii.py` (`test_colision_409_no_expone_dni_telefono`) y verificar que FALLA en rojo.
- [x] 1.6 Fijar `conftest.py` por nivel (unit/integration), markers (`integration`, `slow`), fixtures aisladas con self-cleanup contra Postgres de test y verificar `pytest --collect-only` lista los 8+ tests sin ejecutarlos.

## 2. Scaffolding fundacional

- [x] 2.1 Crear `backend/app/main.py` (FastAPI, routers `/api/v1`, OpenAPI completo) + `core/` (settings por env, logger estructurado sin PII, exceptions + handlers) con type hints (R1) y verificar `uvicorn` levanta y `GET /docs` responde.
- [x] 2.2 Crear `docker-compose.yml` (api + postgres 15+ con `btree_gist` + redis 7 + worker mínimo) + `.env.example` (sin secretos, solo placeholders — R7) y verificar `docker compose config` es válido. [PARCIAL 2026-10-07: archivos existen; `docker compose config` NO validado por falta de Docker en el entorno — deuda explícita.]
- [x] 2.3 Inicializar Alembic (async) + `core/db.py` (async engine, `async_sessionmaker`, pooling, sesión por dependencia) y verificar `alembic current` responde sin error.

## 3. Modelos + migración 001 (GREEN mínimo para los tests 1.1–1.4)

- [x] 3.1 Implementar modelos SQLAlchemy 2.0 (`Mapped[]`/`mapped_column`): `Usuario`, `Paciente`, `Profesional`, `Sillon`, `Prestacion`, `Turno` (incl. `token_publico` único, `timestamptz`, estados) en capas `models/` separadas de `schemas/` (R1, R2) y verificar `mypy` limpio en `models/`.
- [x] 3.2 Escribir migración 001 (tablas + `EXCLUDE USING gist` por profesional y por sillón con cota `'[)'` + predicado de estados activos + `btree_gist`) solo vía Alembic (R2, R3) y verificar `alembic upgrade head` + `downgrade -1` + re-`upgrade` sin error.
- [x] 3.3 Implementar `repositories/` (genérico + por entidad, eager loading) + `services/crear_turno.py` (`fin` calculado, chequeo previo de solapamiento, cálculo de alternativos) + `schemas/` Pydantic (DNI AR, E.164 AR, `from_attributes=True`) y verificar los tests 1.3 y 1.4 pasan en verde.
- [x] 3.4 Implementar `POST /api/v1/turnos` (201 + 409 con `problema` + `slots_alternativos` + 422) con mapeo de `ExclusionViolation` → 409 en el handler global (la DB manda) y verificar los tests 1.1, 1.2 y 1.5 pasan en verde (TRIANGULATE: ≥2 casos por comportamiento ya cubiertos en 1.1–1.5).

## 4. Seed demo + endurecimiento

- [x] 4.1 Implementar `seed_demo.py` idempotente (1 admin, sede "Consultorio" + sillón, 6 prestaciones con duraciones, profesional/paciente `demo`, todo sintético — R0) y verificar doble ejecución no duplica registros (spec: semilla demo).
- [x] 4.2 Pasar `ruff`/`black`, `mypy` limpio total, `pytest --cov --cov-fail-under=80` en verde y verificar cobertura ≥80 % en el dominio agenda.
- [x] 4.3 Registrar deuda explícita hacia C-02 (hook `get_current_user`, sin RLS) como comentario + nota en design y verificar `grep -r "C-02"` encuentra el marcador en código y docs.

## 5. Verificación integral (solo checks, sin código nuevo)

- [x] 5.1 Ejecutar suite completa en verde + `openspec validate --change crear-turno-evitando-solapamientos-profesional-sillon-box` y verificar ambos en verde antes de pedir `/opsx:archive`.
