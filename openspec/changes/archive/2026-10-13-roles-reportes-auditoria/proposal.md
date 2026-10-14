# Proposal — C-11 `roles-reportes-auditoria`

## Why

La clínica ya opera agenda, caja y clínica (C-01…C-10), pero la administración sigue ciega: la gestión de usuarios/roles es un probe mínimo sin CRUD (`routers/rbac.py` solo lista emails), la bitácora `AuditoriaLog` es solo-escritura (el `GET /auditoria` que cita su propio spec no existe) y no hay ningún reporte operativo (ocupación, ausentismo, ingresos). Sin este change el admin no puede controlar accesos ni decidir con datos (US-040, US-041). Governance ALTO: toca RBAC, PII y dinero.

## What Changes

- CRUD `usuarios` + asignación de roles solo admin: `GET/POST /api/v1/usuarios`, `GET/PATCH /api/v1/usuarios/:id` (rol, activo), `DELETE` lógico (desactivar); todo otro rol → `403` genérico + evento `acceso_denegado` (matriz C-02 intacta, recurso `usuarios` ya existe).
- Bitácora consultable: `GET /api/v1/auditoria?entidad&entidad_id&accion&desde&hasta&page&page_size` solo admin; reutiliza `AuditoriaLog` + `sanitizar_diff()` C-02 sin cambiar su escritura; cubre los 5 eventos (crear/cancelar turno, cobro, cierre, edición clínica) + cambio de roles.
- Reportes agregados solo-lectura: `GET /api/v1/reportes/ocupacion|ausentismo|ingresos?desde&hasta&profesional_id&sillon_id&sede` con scoping por rol (admin full / odontólogo solo propios / recepción solo operativo del día) + `GET /api/v1/reportes/:tipo.csv` con CSV sanitizado en streaming.
- Frontend `pages/admin/*` (guarda `RequireRol` existente): `UsuariosPage` (CRUD real), `AuditoriaPage` (tabla + filtros entidad/id), `ReportesPage` (3 vistas por rol + descarga CSV donde corresponde); sin `any`, componentes PascalCase.
- Tests planeados (se ejecutan en apply, datos sintéticos — R0).

## Capabilities

### New Capabilities
- `admin/gestion-usuarios`: CRUD de usuarios y asignación de roles solo admin, con baja lógica y eventos auditados.
- `admin/reportes-operativos`: ocupación por profesional/sillón, ausentismo e ingresos por método con filtros, scoping por rol y exportación CSV sanitizada en streaming.
- `frontend/administracion`: páginas admin de usuarios, auditoría y reportes con guardas por rol y las 3 vistas (full / propios / operativo día).

### Modified Capabilities
- `auditoria/registro-acciones`: la escritura obligatoria NO cambia; se agrega el requisito de lectura (GET filtrable por entidad/entidad_id solo admin) y la cobertura verificable de los 5 eventos con minimización R6.

## Impact

- Nuevo: servicio `usuarios.py` + extensión router `usuarios` (CRUD sobre tabla `usuario` C-01), servicio `reportes.py` + router `reportes` (agregaciones SQL solo-lectura sobre `turno`/`pago`/`movimiento_caja`), router lectura `auditoria`, recursos matriz `auditoria`/`reportes`/`reportes_csv` (recursos existentes intactos), `features/admin` + `pages/admin/{Usuarios,Auditoria,Reportes}` + `apiAdmin/apiReportes` en frontend.
- Reusa sin modificar: `AuditoriaLog` + `sanitizar_diff()` + `registrar_auditoria()` C-02 (eventos nuevos `usuario_creado|rol_cambiado|usuario_desactivado|reporte_csv_exportado`, mismo shape), matriz `puede()` + `require_role/require_admin` + guarda `tienePermiso/RequireRol` (se extienden, no se redefinen), tablas `turno`/`pago`/`movimiento_caja`/`cierre` como fuentes de agregación.
- No-objetivos explícitos: RLS en Postgres (design §8: scoping en servicio), multi-sede real (sede texto default `Consultorio`), facturación ARCA (v2), OS/liquidaciones (C-13), lista de espera (C-14), alta pública de usuarios (solo admin crea).
