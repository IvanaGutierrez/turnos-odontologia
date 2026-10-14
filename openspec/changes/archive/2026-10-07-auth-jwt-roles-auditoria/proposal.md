# Proposal — C-02 `auth-jwt-roles-auditoria`

## Why

El endpoint `POST /api/v1/turnos` de C-01 nació abierto (deuda explícita: hook `get_current_user` pendiente) y no existe identidad verificable para auditar quién crea, cancela, cobra o edita clínica (RN-AU-02/03). Sin auth JWT + RBAC + auditoría, ningún recurso protegido de C-03 en adelante puede operar con garantías mínimas de seguridad multi-rol.

## What Changes

- `POST /api/v1/auth/login` — credenciales (email + password) → JWT access 15' + refresh 7 d; rate limit 5/60 s por IP+email; hash Argon2/bcrypt; bloqueo temporal por intentos fallidos; error 401 genérico que no revela si el email existe (R6).
- `POST /api/v1/auth/refresh` — rotación de refresh (emite par nuevo + blacklist del anterior en Redis; reuso del viejo → 401); `POST /api/v1/auth/logout` — invalida el refresh; `GET /api/v1/auth/me` — perfil propio.
- Claims JWT: `sub`, `roles`, `email`, `jti`, `type` (`access`|`refresh`), `iat`, `exp`; refresh transportado en cookie HttpOnly (`secure`, `samesite=lax`).
- `PermissionContext`: `require_role()`, `require_admin()`, deny-by-default según matriz admin/odontologo/recepcion (`knowledge-base/03_actores_y_roles.md`); salda la deuda de C-01 protegiendo los routers existentes.
- Migración 002 (solo vía Alembic, R2): tabla de sesiones/refresh (jti, usuario_id, expira_at, revocado) + tabla `AuditoriaLog` (accion, entidad, entidad_id, diff jsonb, usuario_id?, ip?).
- Auditoría obligatoria (RN-AU-03) en: login/logout/refresh, denegación por rol, crear/cancelar turno, sobreturno, cobro, cierre, edición clínica, cambio de roles.
- Plan TDD (los tests se escriben en `apply`, aquí solo se especifican): login ok/expirado, rotación de refresh + reuso, rate limit 429, acceso denegado por rol 403 + evento auditado.

## Capabilities

### New Capabilities

- `auth/autenticacion-jwt`: login, refresh con rotación, logout, perfil propio, expiración, rate limit y bloqueo por intentos.
- `auth/autorizacion-rbac`: `PermissionContext` (`require_role()`, `require_admin()`), deny-by-default según matriz de roles.
- `auditoria/registro-acciones`: tabla `AuditoriaLog` y eventos obligatorios (auth, turnos, cobros, clínica, roles).

### Modified Capabilities

- `agenda/crear-turno`: `POST /api/v1/turnos` pasa a exigir JWT válido (`401` sin token o con access expirado); el shape 201/409/422 de C-01 no cambia.

## Impact

- Nuevo: `backend/app/domain/usuarios/` (o `core/security.py` + `domain/auth/`) con routers `/api/v1/auth/*`, servicios JWT/sesiones, `PermissionContext` como dependencias FastAPI; migración 002; vars `JWT_SECRET`, `JWT_ACCESS_MIN`, `JWT_REFRESH_DAYS` (+ `.env.example`, R7); Redis para rate limit y blacklist de refresh.
- Modificado: routers de C-01 protegidos con `get_current_user` (se salda la deuda documentada en `main.py`, `core/db.py`, `routers/turnos.py`).
- Sin frontend en este change (el login SPA llega en C-10); sin cambios al exclusion constraint de agenda (R3 intacto); todo dato de prueba sintético (R0); stack fijo intacto (R8).
