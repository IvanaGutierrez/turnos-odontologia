# Design — C-04 `agenda-dia-semana-recepcion`

## Context

Ver `proposal.md` (Why/What). Estado actual: C-01 archivada (GiST anti-solape por profesional/sillón con cota `[)`, `POST /api/v1/turnos` protegido, shape `409` + alternativos, `fin` calculado, R6), C-02 archivada (JWT/RBAC con `require_role`, matriz `turnos`/`configuracion_agenda`/`agenda_propia`, auditoría con `sanitizar_diff`, deny-by-default), C-03 archivada (modelos `HorarioProfesional`/`Bloqueo`, cálculo de slots, routers públicos separados). Divergencia detectada: el código usa estado `en_sala` (`entidades.py`, migración 001) mientras la KB/US-004 hablan de `presente` (check-in). No existe `GET /api/v1/agenda`, ni transiciones confirmar/reprogramar/check-in, ni flag de sobreturno, ni CRUD de config. Restricciones: R0 sintético, R1 hints, R2 capas + Alembic, R3 GiST intacta para el camino normal, R5 TDD, R6 sin PII, R7 env, R8 stack.

## Goals / Non-Goals

**Goals:**

- Grilla día/semana agregada y performante (una query por rango + índices, `EXPLAIN` sin seq-scan en volumen día/semana).
- Transiciones de recepción con máquina mínima y auditoría sin PII.
- Sobreturno como excepción explícita, con permiso y traza, sin debilitar el camino normal.
- Config agenda con RBAC estricto según matriz.

**Non-Goals:**

- Cancelación con antelación, autogestión con token y máquina completa de estados → C-05 (aquí cualquier intento de cancelar por estos endpoints responde `422`/`404` hacia el futuro contrato; la cancelación NO se implementa).
- Recordatorios/WhatsApp (C-06), clínica (C-07), cobros (C-08), frontend (C-10).
- Recurrencias ricas de calendario (feriados rotativos complejos): se reutiliza `HorarioProfesional` + `Bloqueo` de C-03 sin extender el modelo.

## Decisions

1. **Sobreturno convive con el GiST como excepción explícita a nivel aplicación, sin debilitar el camino normal (R3).** Migración 004 agrega `turno.sobreturno BOOL NOT NULL DEFAULT FALSE`, `motivo_sobreturno TEXT NULL` (check: si `sobreturno` entonces motivo no vacío) y `reprogramado_de_id UUID NULL → turno.id`. Las dos exclusiones GiST de C-01 extienden su predicado `WHERE` a `estado NOT IN (inactivos) AND (sobreturno IS NOT TRUE)`. Efecto: normal-vs-normal sigue vetado por la DB exactamente igual que antes (la DB manda); sobreturno-vs-cualquiera solo entra por el endpoint dedicado `POST /api/v1/turnos/sobreturno` con `require_role` recepcion/admin + `motivo_sobreturno` obligatorio + `sobreturno_creado` auditado (quién/cuándo/por qué). El pre-chequeo aplicativo de turnos normales SÍ cuenta sobreturnos como ocupantes (reusa `existe_solape_*` extendido con flag), de modo que un normal nunca pisa silenciosamente un sobreturno: recibe `409` + alternativos. Alternativa descartada: atrapar `ExclusionViolation` y "promocionarla" a sobreturno — enmascara colisiones normales como excepciones y rompe R3. Alternativa descartada: tabla separada de sobreturnos — duplica queries de grilla y rompe la agregación día/semana.
2. **Estado `presente` como canónico de check-in; `en_sala` queda como alias transitorio.** Migración 004 amplía `ck_turno_estado` con `'presente'` sin eliminar `'en_sala'` (compat con datos C-01). El servicio de check-in escribe siempre `presente`; el schema de lectura normaliza `en_sala → presente` con nota de deprecación. La consolidación/eliminación de `en_sala` se difiere a C-05 (dueña de la máquina completa), evitando una migración destructiva en este change. Transiciones C-04: `reservado→confirmado→presente→atendido`; `reservado|confirmado→reprogramado` (vía reprogramar, no directo); `cancelado|ausente` no se escriben aquí (solo los lee la grilla). Alternativa descartada: renombrar la columna/valor con backfill en 004 — riesgo innecesario para un alias de un solo estado.
3. **Reprogramación por enlace, no por mutación (RN-AG-07).** `POST /api/v1/turnos/<id>/reprogramar {nuevo_inicio}` valida slot destino con el mismo pre-chequeo + exclusión (destino ocupado → `409` + alternativos, sin mutar nada); en éxito: original → `reprogramado` (entra en `ESTADOS_INACTIVOS`, libera el recurso físicamente) y nuevo turno con mismo `token_publico`, mismo `paciente/profesional/prestacion` (sillón revalidado), `canal` heredado, `reprogramado_de_id=<original>` y `motivo_override` opcional. Auditoría `turno_reprogramado` con ambos IDs y horarios, sin PII. El `token_publico` duplicado entre original inactivo y nuevo activo exige relajar su unicidad a unicidad parcial (índice único `WHERE estado NOT IN (inactivos)` o tabla de redirección); 004 implementa el índice parcial — documentado aquí para que el apply no improvise.
4. **Grilla agregada en una query por rango (standard fastapi + sqlalchemy + supabase).** `repositories/agenda.py` suma `listar_turnos_rango(desde, hasta, profesional_id?, sillon_id?)` con un solo `SELECT ... WHERE inicio < hasta AND fin > desde AND estado NOT IN (inactivos + todos los visibles según filtro)` + `ORDER BY inicio`, apoyado en índices existentes `(profesional_id, inicio)`, `(sillon_id, inicio)` más índice nuevo `(inicio, fin)` de 004. Sin N+1: joins con `selectinload` de profesional/sillón/prestación/paciente-nombre en la misma ronda. `vista=dia` = ventana del día AR (`America/Argentina/Buenos_Aires`) salvo `desde` explícito; `vista=semana` exige `desde/hasta` acotados por `AGENDA_SEMANA_MAX_DIAS` (default 7, env). `EXPLAIN` en apply debe mostrar index-scan (seq-scan solo aceptable en tablas casi vacías). Alternativa descartada: agregar en Python con N queries por profesional/sillón — no escala a semana multisillón.
5. **Visibilidad por rol en la grilla (R6, Ley 25.326 minimización).** Items con `{id, inicio, fin, estado, profesional_id, sillon_id, prestacion_id, sobreturno, paciente_nombre}`; `paciente_nombre` solo para `admin`/`recepcion` (necesario para operar el día: llamar al paciente en sala); `odontologo` recibe su propia agenda con igual minimización (sin DNI/teléfono/HC). DNI/teléfono/HC/hashes/tokens jamás en `200`/`4xx`/logs/`diff` (reusa `sanitizar_diff`). El detalle de contacto para ubicar al paciente se resuelve por canal operativo fuera de la grilla (C-06), no ampliando el response.
6. **RBAC por recursos existentes + endpoint dedicado de sobreturno.** Grilla y operación de turnos bajo `require_role("turnos")` (matriz ya incluye admin/odontólogo/recepción; el sobreturno añade chequeo fino recepcion/admin dentro del servicio con `403` + `acceso_denegado` para odontólogo — ver spec). Config bajo `require_role("configuracion_agenda")` (solo admin en matriz; lectura de recepción/odontólogo vía endpoints GET con permiso `turnos`/`agenda_propia`, sin escritura). Sin cambios en `matriz.py` salvo el predicado fino de sobreturno documentado en código. Alternativa descartada: nuevo rol `supervisor` — no existe en la KB.
7. **Testing (plan, se ejecuta en apply):** pytest sobre Postgres real (el GiST parcial no existe en SQLite), `fakeredis` innecesario aquí (sin rate limit nuevo), AAA, `--cov-fail-under=80` en el dominio nuevo; concurrencia: doble reprogramación simultánea y normal-vs-sobreturno en carrera (extiende patrón C-01).

## Risks / Trade-offs

- [Riesgo] Carrera normal-vs-sobreturno: la exclusión parcial no veta sobreturnos, dos escrituras simultáneas (normal + sobreturno) pueden solaparse físicamente → Mitigación: pre-chequeo aplicativo + orden determinista (el sobreturno exige motivo y auditoría previa al flush); si la grilla muestra doble ocupación, recepción lo resuelve manualmente; documentado como excepción operativa, no como bug silencioso.
- [Riesgo] Unicidad parcial de `token_publico` (original `reprogramado` + nuevo activo comparten token) → Mitigación: índice único parcial en 004 + test de duplicado de token entre inactivo/activo; C-05 (rotación ante fuga) lo reutiliza.
- [Riesgo] Zona horaria en `vista=dia` (bordes del día, DST) → Mitigación: todo `timestamptz`, `desde/hasta` aware obligatorios, día AR calculado en servicio con `ZoneInfo("America/Argentina/Buenos_Aires")`, tests en ese TZ.
- [Riesgo] Semana multisillón pesada (N turnos × joins) → Mitigación: una query + `selectinload`, límite de ventana por env, `EXPLAIN` en apply; paginación por ventana (no por offset) para no cortar días.
- [Riesgo] `odontologo` pide sobreturno por endpoint normal con `sobreturno=true` en el body → Mitigación: el flag solo se atiende en el endpoint dedicado; `TurnoCreate` ignora `sobreturno` (extra="ignore", patrón C-01 con `fin`).
- [Trade-off] GiST parcial vs GiST intacta + veto aplicativo total. Aceptado el predicado parcial porque mantiene la garantía DB para el 99 % del tráfico (normal-normal) y hace visible la excepción en el propio catálogo de constraints (`\d turno` muestra la excepción), en vez de esconderla en código.

## Migration Plan

1. `apply` ejecuta migración 004 sobre DB con datos C-01…C-03: columnas nuevas con defaults seguros (`sobreturno=false`), predicado GiST ampliado (transacción con `ALTER TABLE ... DROP CONSTRAINT / ADD CONSTRAINT`; ventana de bloqueo breve documentada), índice parcial de token, índice `(inicio, fin)`, `ck` de motivo y de estado ampliado. Sin backfill (cero sobreturnos históricos; `en_sala` se conserva).
2. Deploy: `docker compose up --build`; solo env nuevas documentadas en `.env.example` (`AGENDA_DIA_MAX`, `AGENDA_SEMANA_MAX_DIAS`); sin cambios en Compose.
3. Rollback: `alembic downgrade -1` (revierte columnas, constraints e índices; no toca turnos existentes salvo defaults).
4. Seed demo extiende el de C-03 con 2 turnos ficticios + 1 sobreturno ficticio marcado `demo` (R0).

## Open Questions

- Ninguna que cambie specs, enfoque o tasks: topes exactos de ventana (`AGENDA_SEMANA_MAX_DIAS=7`) y de items de grilla quedan en env para ajuste en piloto; la consolidación `en_sala→presente` la decide C-05 sin bloquear este change.
