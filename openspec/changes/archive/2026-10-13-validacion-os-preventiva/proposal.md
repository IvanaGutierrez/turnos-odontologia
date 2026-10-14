# Proposal — C-13 `validacion-os-preventiva`

## Why

La clínica atiende pacientes con obra social sin saber si la práctica está cubierta: el débito llega semanas después, cuando ya no hay forma de cobrar. Este change agrega la validación preventiva antes de confirmar el turno (US-050, RN-OS-01/02) como diferenciador v1.5, sobre el camino crítico ya estable (C-05). Governance ALTO: toca dinero (derivación a particular con presupuesto), PII sensible (nro. de afiliado) y decisiones clínicas-administrativas previas a la atención.

## What Changes

- Modelos nuevos: `ObraSocial` (nomenclador + topes en `jsonb` versionados), `AfiliacionOS` (paciente ↔ OS con vigencia) y `ValidacionCobertura` (resultado por turno); migración **012** (la 007 que cita CHANGES.md ya existe — verificado `alembic history`: head `011_caja_cierre_diario`).
- `POST /api/v1/obras-sociales/validar` (por turno, solo staff): cruza afiliación vigente + nomenclador local + topes/frecuencias → `cubre|parcial|no_cubre` con detalle; si `no_cubre` → deriva a flujo particular con presupuesto (C-07) antes de confirmar.
- CRUD afiliaciones (`GET/POST /api/v1/afiliaciones`, `GET/PATCH/DELETE /api/v1/afiliaciones/:id`, solo staff); sin login de OS en v1 (actor externo, IN-01: validación contra nomenclador LOCAL cargado, no contra webservices de las OS).
- Nomenclador versionado por OS: cambiar la versión no invalida validaciones previas (cada `ValidacionCobertura` congela la versión usada).
- Auditoría: eventos `validacion_os_registrada|afiliacion_creada|afiliacion_actualizada` sin PII (R6 — jamás nro. de afiliado/DNI en `diff`/logs/responses).
- Tests planeados (se ejecutan en apply, datos sintéticos — R0).

## Capabilities

### New Capabilities

- `obras-sociales/validacion-cobertura`: validación preventiva por turno contra nomenclador local versionado con resultado `cubre|parcial|no_cubre`, detalle y derivación a particular con presupuesto.
- `obras-sociales/afiliaciones`: CRUD de afiliaciones paciente ↔ obra social con vigencia, solo staff.

### Modified Capabilities

- `auditoria/registro-acciones`: se agregan los eventos `validacion_os_registrada|afiliacion_creada|afiliacion_actualizada` a la lista obligatoria, con la misma minimización R6 (sin nro. de afiliado/DNI en el `diff`).

## Impact

- Nuevo: modelos `ObraSocial|AfiliacionOS|ValidacionCobertura` + migración 012 (tablas + índices GIN sobre nomenclador + FKs), servicio `validacion_os.py` + schemas, router `obras_sociales` (+ `afiliaciones`), recursos matriz `obras_sociales|afiliaciones`, eventos de auditoría nuevos (mismo shape C-02/C-11).
- Reusa sin modificar: `Turno`/`Paciente`/`Prestacion` como entradas de la validación, flujo `Presupuesto` C-07 para la derivación a particular (el presupuesto nace por el camino existente, sin cambios), `sanitizar_diff()` + `registrar_auditoria()` para los eventos, `require_role`/matriz (se extienden, no se redefinen).
- No-objetivos explícitos: login/integración con webservices de las OS (IN-01 — cae a nomenclador local; el spike SU-02 con 2–3 OS grandes en semana 1 de v1.5 decide si algún día hay conector, fuera de este change), liquidaciones por OS y período con export PDF (RN-OS-03 — change futuro), facturación ARCA (v2), frontend OS (este change es backend; la UI llega con C-10-extensión o change dedicado).
