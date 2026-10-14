# Tasks — C-11 `roles-reportes-auditoria`

> Governance ALTO (RBAC + PII + dinero) — fase PROPOSE: este archivo es el plan. Ninguna tarea se ejecuta sin aprobación explícita del usuario (`apply`). Orden TDD estricto: RED → GREEN → TRIANGULATE → REFACTOR. Datos 100 % sintéticos/ficticios (R0); hints en todo Python público (R1); capas (`models/` vs `schemas/` vs `repositories/` vs `services/` vs `routers/`, sin migración salvo criterio design-1) (R2); turnos/solapamientos intactos (R3 N/A); cada comportamiento con test en verde pytest + Vitest/E2E (R5); PII/HC jamás en auditoría/reportes/CSV/logs (R6); sin secretos nuevos, solo env (R7); stack fijo (R8). Standards: fastapi (endpoints admin, CSV streaming), sqlalchemy (agregaciones, índices), testing-patterns, supabase; vercel-react (tablas, CSV download), design (densidad admin), web-guidelines (a11y tablas), playwright (E2E).

## 1. Tests backend en ROJO (TDD — antes de producción)

- [x] 1.1 Escribir `tests/integration/test_usuarios_crud.py` (admin CRUD + rol/activo + baja lógica; recepción/odontólogo en cada verbo → `403` + `acceso_denegado`; email duplicado → `409`; rol inválido → `422`; autodegradación admin → `422`; responses sin `password_hash`) y verificar que FALLA en rojo.
- [x] 1.2 Escribir `tests/integration/test_auditoria_lectura.py` (GET filtra `entidad/entidad_id/accion/rango` + pagina; admin `200` ordenado desc; recepción/odontólogo → `403`; los 5 eventos crear/cancelar turno, cobro, cierre, edición clínica aparecen con usuario/hora; barrido: ningún `diff` contiene DNI/teléfono/HC/hash/token) y verificar que FALLA en rojo.
- [x] 1.3 Escribir `tests/integration/test_reportes.py` (fixtures con conteos exactos: ocupación 50/25 por profesional/sillón, ausentismo 10 %, ingresos por método con diferencia 0; scoping: odontólogo ajeno → `403`, recepción fuera de hoy → `403`; CSV: headers exactos + BOM + montos == JSON + barrido PII + recepción CSV → `403`) y verificar que FALLA en rojo.
- [x] 1.4 Fijar fixtures/`conftest.py` (usuarios sintéticos admin/odontólogo/recepción, turnos/pagos/movimientos ficticios por día/sede/profesional, Postgres real, markers `integration`) y verificar `pytest --collect-only` lista 1.1–1.3 sin ejecutarlos.

## 2. Usuarios + auditoría lectura (GREEN backend)

- [x] 2.1 Implementar servicio `usuarios.py` + schemas (alta con hash, cambio rol/activo, baja lógica, autobloqueo, allowlist de salida sin `password_hash`) y recursos matriz `auditoria` y registrar eventos `usuario_creado|rol_cambiado|usuario_desactivado` vía `sanitizar_diff`, y verificar tests 1.1 en verde.
- [x] 2.2 Implementar routers `usuarios` (CRUD) + `GET /api/v1/auditoria` (filtros entidad/entidad_id/acción/rango, paginado, solo admin, `diff` sanitizados) y verificar tests 1.1–1.2 en verde.
- [x] 2.3 Medir `EXPLAIN` del GET auditoría con volumen y decidir índice 012 solo si hay seq-scan (criterio design-1), y verificar `alembic` head intacto en ambos casos.

## 3. Reportes + CSV (GREEN backend)

- [x] 3.1 Implementar servicio `reportes.py` (`alcance_reportes()` por rol + agregaciones SQL ocupación/ausentismo/ingresos con allowlist de columnas, zona AR) y recursos `reportes|reportes_csv`, y verificar JSON de tests 1.3 en verde.
- [x] 3.2 Implementar router `reportes` (3 JSON + 3 CSV en `StreamingResponse` con BOM/headers/`Content-Disposition`, evento `reporte_csv_exportado`, serializador allowlist) y verificar tests 1.3 completos en verde.
- [x] 3.3 Pasar `ruff`/`black`, `mypy` limpio, `pytest --cov --cov-fail-under=80` en verde con regresión C-02/C-08/C-09 intacta (deny-by-default, acreditación, cierre) y cero red real.

## 4. Frontend admin (GREEN con sus tests)

- [x] 4.1 Implementar `features/admin` (`tipos` estrictos cero `any`, `apiAdmin`, `apiReportes` sobre `apiClient`) + espejo de `auditoria|reportes|reportes_csv` en `guards.tsx`, y verificar `tsc --noEmit` limpio.
- [x] 4.2 Implementar `UsuariosPage` real (lista/pagina/crea/cambia-rol/desactiva con confirmación, catálogo `es-AR`) + `AuditoriaPage` (filtros entidad/id/acción/rango, tabla sin PII) con Vitest (guardas, 403 sin fetch, filtros) en verde.
- [x] 4.3 Implementar `ReportesPage` (3 vistas admin-propios-día + descarga blob `reporte-<tipo>-<desde>-<hasta>.csv`, tablas `<th scope>`, vacíos/errores en español) con Vitest + E2E Playwright (admin CRUD, auditoría filtra, odontólogo propios, recepción día sin CSV) en verde.

## 5. Verificación integral (solo checks, sin código nuevo)

- [x] 5.1 Suite completa backend + frontend en verde, `openspec validate --change roles-reportes-auditoria` y `openspec status --change roles-reportes-auditoria` en verde antes de pedir `/opsx:archive`.
