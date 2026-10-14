# Design — C-13 `validacion-os-preventiva`

## Context

Ver `proposal.md` (Why/What). Estado actual verificado por lectura de `app/` y `alembic history`: no existe ningún modelo, tabla, router ni servicio de OS (la palabra no aparece en `models/`, `routers/` ni `main.py`); `Turno` (con `prestacion_id`), `Paciente`, `Presupuesto` C-07 y `AuditoriaLog` + `sanitizar_diff()` C-02/C-11 existen y se reusan sin cambios. Migraciones `001–011` ocupan todos los slots (`alembic history`: head `011_caja_cierre_diario`); la "Migración 007" que cita CHANGES.md corresponde a `007_avisos_programacion` (C-06) — el número correcto para este change es **012**. Restricciones: R0 sintético (afiliados y nomencladores ficticios, jamás reales); R1 hints; R2 capas + Alembic; R3 N/A (no toca solapamientos); R5 TDD; R6 crítico (nro. de afiliado = PII); R7 env; R8 stack fijo.

## Goals / Non-Goals

**Goals:**

- Validación preventiva por turno contra nomenclador local versionado, con derivación a particular con presupuesto (US-050, RN-OS-01/02).
- Trazabilidad: cada validación congela la versión de nomenclador usada; auditoría sin PII.

**Non-Goals:**

- Conectores con webservices de OS (IN-01: nomenclador local; el spike SU-02 vive fuera de este change); liquidaciones RN-OS-03 con export PDF (change futuro); UI OS; ARCA (v2).

## Decisions

1. **Migración 012 (verificado, no 007).** `alembic history` muestra `001→…→011` encadenados con head en `011_caja_cierre_diario`; CHANGES.md arrastra el número viejo. 012 crea `obra_social`, `afiliacion_os`, `validacion_cobertura` + índice GIN sobre `nomenclador` + FKs + unicidad (afiliación vigente duplicada). Alternativa descartada: renumerar o reutilizar 007 — rompería la cadena Alembic.
2. **Nomenclador LOCAL versionado en `jsonb`, no webservices (IN-01/SU-02).** Cada `ObraSocial` guarda `nomenclador_version` + `nomenclador jsonb` (mapa código→{cubre, copago, frecuencia}) + `topes jsonb`; la carga es manual/staff (seed o CRUD interno) y la validación es una función pura sobre datos locales. El spike con 2–3 OS grandes (semana 1 v1.5) decide conectores futuros; si es inviable, el registro manual simple ya es este change. Alternativa descartada: llamar a webservices OS en este change — sin spike previo es riesgo SU-02 sin red.
3. **Matching afiliado en 3 pasos con cortocircuito.** (a) afiliación vigente del paciente para esa OS (por `afiliacion_id` explícito + chequeo `paciente_id` del turno, `vigencia_desde/hasta` contra fecha del turno); (b) lookup de la prestación en el nomenclador vigente (por `prestacion_id`/código); (c) topes/frecuencias contra historial de validaciones previas del afiliado. Cada paso fallido mapea a un motivo (`sin_afiliacion_vigente|fuera_de_nomenclador|tope_agotado|frecuencia_excedida`) y al resultado (`no_cubre` para a/b, `parcial` para c). Alternativa descartada: un solo query monolítico — los motivos son el detalle que evita el débito.
4. **Topes/frecuencias contra historial propio, no contra la OS.** El consumo acumulado se calcula desde `ValidacionCobertura` previas del afiliado (mismo período), no desde sistemas externos. Es aproximado por diseño y el `detalle` lo declara (`fuente: historial_local`). Alternativa descartada: asumir consumo cero — mentiría `cubre` donde corresponde `parcial`.
5. **Derivación sin mutar: `no_cubre` propone, no impone.** Validar nunca cambia el estado del turno; la respuesta trae `deriva_particular=true` y el staff crea el `Presupuesto` por el flujo C-07 existente (sin cambios) antes de confirmar. La confirmación posterior sigue siendo decisión humana (recepción/odontólogo). Alternativa descartada: auto-generar el presupuesto al validar — crea deuda comercial sin consentimiento del paciente.
6. **RBAC: validar ≠ padronar.** `obras_sociales:validar → {admin, recepcion, odontologo}` (el odontólogo necesita saber cobertura antes de atender); `afiliaciones → {admin, recepcion}` (padrón administrativo; el odontólogo no edita afiliaciones). Nro. de afiliado enmascarado (últimos 4) en lecturas, jamás en logs/errores/`diff`. Alternativa descartada: validar solo recepción — frenaría al odontólogo en consultorio.
7. **Testing (plan, se ejecuta en apply — R5).** pytest sobre Postgres real con fixtures de nomenclador ficticio (2 OS sintéticas, prestaciones del catálogo demo): cubre/parcial/no_cubre exactos; `no_cubre` → respuesta con `deriva_particular` y turno intacto; tope/frecuencia límite; duplicada vigente → `409`; afiliación ajena → `422`; sin permiso → `403` + `acceso_denegado`; barrido PII (nro. afiliado/DNI/teléfono marcados) en responses, `diff`s y logs; versionado (nueva versión no altera validaciones congeladas). Cobertura ≥ 80 % en el módulo nuevo.

## Risks / Trade-offs

- [Riesgo] Nomenclador local desactualizado vs OS real → Mitigación: `nomenclador_version` + fecha de carga visibles en cada validación; el `detalle` declara la fuente; proceso manual de actualización documentado en el spec.
- [Riesgo] Fuga de nro. de afiliado (PII) → Mitigación: enmascarado en lecturas + allowlist en `diff`/responses + test de barrido con PII marcada.
- [Riesgo] Topes aproximados (historial local incompleto) → Mitigación: `parcial` conservador ante duda + `detalle` con la fuente; nunca `cubre` silencioso con consumo incierto.
- [Trade-off] Sin webservices OS: la validación es preventiva-informativa, no autorización de la OS. Se acepta (IN-01 lo prevé); el valor es evitar el 80 % de débitos por nomenclador/topes, no el 100 %.

## Migration Plan

Migración 012 adelante-atrás (`upgrade` crea 3 tablas + índices; `downgrade` las elimina — sin datos reales que migrar). Deploy: solo backend + `.env.example` sin secretos nuevos (sin credenciales OS en v1). Rollback: revert del change + `alembic downgrade -1` (ningún change previo depende de estas tablas).

## Open Questions

Ninguna que cambie specs, enfoque o tasks — el spike SU-02 y RN-OS-03/liquidaciones quedan explícitamente fuera (proposal No-objetivos).
