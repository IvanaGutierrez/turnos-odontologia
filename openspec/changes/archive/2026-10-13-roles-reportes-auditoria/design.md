# Design — C-11 `roles-reportes-auditoria`

## Context

Ver `proposal.md` (Why/What). Estado actual verificado por lectura de `app/` y `frontend/src/`: `AuditoriaLog` append-only con `sanitizar_diff()` denylist R6 (`repositories/auditoria.py`) existe desde C-02 pero sin endpoint de lectura; matriz `domain/auth/matriz.py` sin recursos `auditoria`/`reportes`/`reportes_csv` (deny-by-default: lo no listado → `403`); `routers/rbac.py` es un probe (lista emails, sin CRUD); `core/dependencies.py` ya da `require_role` + `require_admin` con `403` genérico + `acceso_denegado` auditado; frontend tiene guarda espejo `tienePermiso/RequireRol` (`shared/auth/guards.tsx`), `apiClient` con JWT en memoria + sanitización R6 y `UsuariosPage` placeholder con guarda. Restricciones: R0 sintético; R1 hints; R4 TS estricto cero `any`; R2 capas + Alembic; R5 TDD (pytest + Vitest/E2E); R6 crítico (minimización por rol, CSV sanitizado); R7 env; R8 stack fijo.

## Goals / Non-Goals

**Goals:**

- Cerrar el hueco admin: CRUD usuarios/roles + bitácora legible + reportes con CSV (US-040/041, RN-AU-02/03).
- Minimización por rol de punta a punta: cada vista devuelve lo mínimo necesario, verificable en tests.

**Non-Goals:**

- RLS en Postgres; alta pública de usuarios; multi-sede real; ARCA (v2); OS (C-13); lista de espera (C-14).

## Decisions

1. **Migración: NO (verificado).** `usuario` (C-01) y `auditoria_log` con índice `(entidad, entidad_id)` (C-02) ya existen; reportes son `SELECT` agregados sin tablas nuevas. Solo si `EXPLAIN` en apply muestra seq-scan sobre auditoría con volumen se agrega migración 012 con índices `(creado_en DESC)` + `(usuario_id)` — decisión diferida con criterio medible. Alternativa descartada: migración preventiva sin evidencia — costo sin beneficio.
2. **Agregaciones en DB, no en Python.** Ocupación/ausentismo/ingresos como `COUNT/GROUP BY` por `(profesional_id|sillon_id|metodo, día)` con `date_trunc('day')` en zona `America/Argentina_Buenos_Aires`; ocupación = turnos no-cancelados del rango (el denominador "slots" se expone como `horas_ocupadas` + `turnos_activos`, no se inventa capacidad); ausentismo = `ausente/(presente+atendido+ausente)`; ingresos = movimientos (ingresos−egresos) + `pago acreditado` solo lectura (patrón C-09). Índices ya existentes (`turno(profesional_id,inicio)`, `(sillon_id,inicio)`, `pago(turno_id)`, `movimiento(fecha,sede)`) cubren los filtros. Alternativa descartada: agregar en Python — trae filas con posible PII a memoria y rompe streaming.
3. **CSV en streaming con contrato fijo.** `StreamingResponse` + generador por chunks, `text/csv; charset=utf-8` con BOM (Excel AR), separador `,`, headers fijos en español por tipo (ver spec), `Content-Disposition: attachment; filename=reporte-<tipo>-<desde>-<hasta>.csv`, evento `reporte_csv_exportado`. El serializador CSV solo acepta claves del contrato (allowlist) — cualquier campo fuera del contrato no se emite aunque el servicio lo devuelva. Alternativa descartada: construir el CSV en memoria — picos de memoria en rangos largos; y `;` como separador — rompe el contrato esperado por los tests/consumidores definidos aquí.
4. **RBAC: 3 recursos nuevos, matriz existente intacta.** `auditoria→{admin}`, `reportes→{admin,odontologo,recepcion}` (scoping en servicio: odontólogo fuerza `profesional_id=propio`, recepción fuerza `desde==hasta==hoy`), `reportes_csv→{admin,odontologo}` (odontólogo CSV solo propio; recepción sin CSV → `403`). La guarda frontend espeja los 3 recursos. Todo bajo `/api/v1` con JWT (nada público). Alternativa descartada: CSV para recepción — el operativo día no necesita exportar y cada exportación es superficie de fuga PII.
5. **Minimización R6 por capa (crítico).** Servicio reportes/auditoría devuelve solo IDs/conteos/montos/estados (allowlist de columnas, jamás `dni/telefono/nombre/email/anamnesis/token/hash`); `diff` pasa por `sanitizar_diff()` existente; CSV usa el mismo serializador allowlist; frontend no tiene columnas PII en estas vistas y `sanitize.ts`/`sanitizarError` cubren errores/logs. Tests con aserción negativa (barrido de PII sintética marcada) en JSON, CSV y eventos. Alternativa descartada: "confiar en no seleccionar PII" sin allowlist — un `SELECT *` futuro la filtraría.
6. **Frontend: extiende, no reinventa.** `features/admin/{apiAdmin,apiReportes,tipos}` + `pages/admin/{Usuarios,Auditoria,Reportes}Page` (PascalCase, cero `any`); `RequireRol` + `areaPorRol` (admin aterriza en `/admin/usuarios` — ya existe); `apiClient.get` con `ParametrosConsulta` tipado; descarga CSV por blob + `URL.createObjectURL`; tablas semánticas `<table>/<th scope>` + estados vacío/error en español. `UsuariosPage` placeholder se reemplaza (no se duplica la ruta). Alternativa descartada: páginas fuera de `/admin/*` — rompería el modelo mental de guardas ya documentado.
7. **Testing (plan, se ejecuta en apply — R5).** Backend pytest sobre Postgres real: CRUD por no-admin → `403` + `acceso_denegado`; unicidad email/rol; autobloqueo admin → `422`; GET auditoría filtra entidad/id y trae los 5 eventos sin PII; reportes con fixtures de conteos exactos (ocupación 50/25, ausentismo 10 %, ingresos por método); CSV con headers/formato/BOM y barrido PII. Frontend Vitest (guardas, vistas por rol, descarga con blob mockeado, cero `any` vía `tsc --noEmit`) + E2E Playwright (admin CRUD, auditoría filtra, odontólogo propios, recepción día sin CSV). Datos 100 % sintéticos (R0).

## Risks / Trade-offs

- [Riesgo] Agregación pesada en rangos largos → Mitigación: filtros acotados (`desde/hasta` obligatorios, `page_size` max 100), agregación en DB, streaming en CSV.
- [Riesgo] Fuga PII por campo nuevo en modelos → Mitigación: allowlist de columnas en servicio + serializador CSV + test de barrido con PII marcada.
- [Riesgo] Odontólogo adivina IDs ajenos → Mitigación: scoping forzado en servicio (no solo en frontend), ajeno → `403`.
- [Trade-off] Sin RLS: el scoping vive en servicio. Se acepta (coherente con C-02…C-09); costo: cada query de reportes debe aplicar el filtro de rol — mitigación: helper único `alcance_reportes(rol, usuario)` testeado.

## Migration Plan

Sin migración (decisión 1). Deploy: solo código + `.env.example` sin secretos nuevos. Rollback: revert del change (ningún schema cambia, `AuditoriaLog` sigue append-only).

## Open Questions

Ninguna que cambie specs, enfoque o tasks — todo lo diferible (índice 012 opcional) lleva criterio medible en la decisión 1.
