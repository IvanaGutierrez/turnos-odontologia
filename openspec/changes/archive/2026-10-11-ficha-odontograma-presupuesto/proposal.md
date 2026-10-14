# Proposal — C-07 `ficha-odontograma-presupuesto`

## Why

La atención clínica (Flujo 3, US-020) hoy no existe en la API: tras el check-in (`presente`, C-04) el odontólogo no puede registrar ficha/HCE, odontograma FDI ni presupuestos/planes, y la recepción no tiene cómo entregar el link de seña de un plan (C-08). Sin este change, el camino FASE 1 queda trunco y la HCE viviría en papel, violando trazabilidad de Ley 26.529 (RN-CL-01/04). Este change corre en paralelo a C-05 (GATE 4) y solo depende de C-02 (auth/RBAC/auditoría) y C-04 (check-in + matriz).

## What Changes

- Modelos + **migración Alembic 008** (`008_ficha_clinica`, `down_revision = "007_avisos_programacion"` — 001–007 ya ocupadas, verificado en `backend/alembic/versions/`): `ficha` (anamnesis jsonb cifrada, firma profesional), `odontograma_entry` (pieza_fdi 11–48, catálogo de estados versionado ~18), `evolucion`, `presupuesto`/`presupuesto_item`/`plan_tratamiento` (etapas jsonb, estados `borrador→aprobado→pagado`), más tabla `catalogo_odontograma_estado` (código + versión + descripción).
- Gate de consentimiento (RN-CL-01, Ley 26.529): `POST /api/v1/fichas` sin `paciente.consentimiento_hc` registrado → `422`; con consentimiento → `201` + firmante (odontólogo autenticado).
- RBAC fino (RN-CL-04, matriz 03): recepción edita solo contacto del paciente; cualquier escritura clínica con rol recepción → `403` + auditoría; odontólogo CRUD clínico sobre sus pacientes; admin solo lectura de auditoría.
- Endpoints: `POST /api/v1/fichas`, `GET/PATCH /api/v1/fichas/:id`, `POST /api/v1/fichas/:id/odontograma` (batch por pieza, upsert por pieza), `POST /api/v1/fichas/:id/evoluciones`, `POST /api/v1/presupuestos` (nace de hallazgos del odontograma), `POST /api/v1/presupuestos/:id/firma` (firma del paciente, RN-CL-03: obligatoria antes de plan con seña), transiciones de estado `borrador→aprobado→pagado` (vía C-08 para el pago), `GET /api/v1/pacientes/:id/exportacion` (Ley 25.326).
- Cifrado en reposo de HCE (anamnesis/evolución) con clave por env + rotación documentada; anamnesis/HC jamás en logs, errores, diffs ni responses (R6); toda edición clínica registra firmante (usuario + fecha) sin exponer contenido.
- Tests planeados (se ejecutan en apply): HCE sin consentimiento → 422; recepción editando clínica → 403 (y editando contacto → 200); odontólogo edita → 200 + auditoría con firmante; batch válido/inválido (pieza fuera de 11–48 → 422, estado fuera de catálogo → 422); presupuesto desde hallazgos; plan con seña sin firma → 422; exportación completa; transiciones válidas/inválidas.

## Capabilities

### New Capabilities

- `clinica/ficha-odontograma-presupuesto`: ficha clínica/HCE con consentimiento obligatorio, odontograma FDI por pieza con catálogo versionado, evoluciones firmadas, presupuestos nacidos de hallazgos con firma del paciente y planes por etapas — cifrado en reposo, RBAC clínico por rol y exportación Ley 25.326.

### Modified Capabilities

_(ninguna — `agenda/*`, `notificaciones/*` y `auth/*` no cambian sus REQUIREMENTS: este change solo lee `paciente.consentimiento_hc` (C-01), `turno.presente` (C-04) como disparador de Flujo 3, la matriz/RBAC y `sanitizar_diff` (C-02), y produce `presupuesto.sena_requerida` que C-08 consumirá; no altera sus shapes ni máquinas de estados)_

## Impact

- Nuevo: `models/clinica.py` (5 tablas + catálogo), migración `008_ficha_clinica`, `schemas/clinica.py`, `repositories/clinica.py`, `services/ficha.py` + `services/presupuesto.py`, routers `fichas`/`odontograma`/`evoluciones`/`presupuestos`/`exportacion`, settings `HCE_CIFRADO_KEY` (+ anterior para rotación) solo por env (R7), `.env.example` extendido, seed clínico demo.
- Reusa sin modificar: exclusión GiST C-01 (R3 N/A — no se toca agenda), JWT + `puede()`/matriz + `AuditoriaLog`/`sanitizar_diff` C-02 (nuevas acciones `ficha_creada|ficha_editada|odontograma_actualizado|evolucion_agregada|presupuesto_*|firma_paciente|datos_exportados`, sin PII), `consentimiento_hc` C-01, check-in C-04, Postgres real + Redis/pattern C-02 según se necesite (R8).
- No-objetivos explícitos: cobro/acreditación MP (C-08 consume `sena_requerida`), validación OS (C-13), periodontograma e IA en radiografías (v2, fuera de roadmap), firma electrónica avanzada con tercero (la firma es registro firma+fecha trazable, RN-CL-03).
