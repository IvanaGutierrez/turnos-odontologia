# Tasks — C-02 `auth-jwt-roles-auditoria`

> Governance CRITICO — fase PROPOSE: este archivo es el plan. Ninguna tarea se ejecuta sin aprobación explícita del usuario (`apply`). Orden TDD estricto: RED → GREEN → TRIANGULATE → REFACTOR. Todo dato de prueba sintético (R0, credenciales ficticias). Las Open Questions de `design.md` (recuperación de clave, gestión multi-dispositivo) están diferidas a C-10/C-11 y no cambian lo que se construye aquí.

## 1. Tests en ROJO primero (TDD — antes de cualquier código de producción)

- [x] 1.1 Escribir `tests/integration/test_auth_login_valido_200.py` (`test_login_credencial_valida_emite_access_y_refresh`) con usuario sintético y verificar que FALLA en rojo (sin código: error de colección/import).
- [x] 1.2 Escribir `tests/integration/test_auth_login_invalido_401.py` (`test_login_email_inexistente_401_generico`, `test_login_password_incorrecta_401_generico`, `test_login_fallido_no_revela_existencia_ni_expone_hash`) con freezegun donde aplique y verificar que FALLAN en rojo.
- [x] 1.3 Escribir `tests/integration/test_auth_expiracion_401.py` (`test_access_expirado_me_401` con freezegun +15' y `test_access_con_type_refresh_rechazado_401`) y verificar que FALLAN en rojo.
- [x] 1.4 Escribir `tests/integration/test_auth_refresh_rotation.py` (`test_refresh_valido_rota_par_nuevo`, `test_reuso_refresh_viejo_401_y_revoca_cadena`, `test_logout_invalida_refresh`) y verificar que FALLAN en rojo.
- [x] 1.5 Escribir `tests/integration/test_auth_rate_limit_429.py` (`test_login_sexto_intento_misma_ip_email_429`, `test_bloqueo_temporal_tras_10_fallidos_429`) con Redis de test y verificar que FALLAN en rojo.
- [x] 1.6 Escribir `tests/integration/test_auth_rbac_403.py` (`test_recepcion_gestion_usuarios_403`, `test_odontologo_agenda_propia_200_y_config_admin_403`, `test_denegacion_genera_evento_auditoria`, `test_endpoint_sin_token_401`) y verificar que FALLAN en rojo.
- [x] 1.7 Escribir `tests/integration/test_auditoria_eventos_auth.py` (`test_login_logout_refresh_denegacion_generan_4_filas`, `test_diff_auditoria_sin_hashes_tokens_pii`) y verificar que FALLAN en rojo.
- [x] 1.8 Fijar `conftest.py` (fixtures aisladas con self-cleanup contra Postgres/Redis de test, usuario sintético con hash Argon2, helper de login), markers (`integration`, `slow`) y verificar `pytest --collect-only` lista los 14+ tests sin ejecutarlos.

## 2. Migración 002 + modelos (GREEN base para los tests 1.1–1.7)

- [x] 2.1 Implementar modelos SQLAlchemy 2.0 (`Mapped[]`/`mapped_column`): `SesionRefresh` (`jti` PK, `usuario_id` FK, `expira_at`, `revocado`) y `AuditoriaLog` (accion, entidad, entidad_id, diff jsonb, usuario_id?, ip?, creado_en) en capas `models/` separadas de `schemas/` (R1, R2) y verificar `mypy` limpio en `models/`.
- [x] 2.2 Escribir migración 002 (ambas tablas + índices `(usuario_id, expira_at)` y `(entidad, entidad_id)`) solo vía Alembic (R2) y verificar `alembic upgrade head` + `downgrade -1` + re-`upgrade` sin error.
- [x] 2.3 Implementar `repositories/` (sesiones: buscar por jti, revocar por jti/cadena de usuario; auditoría: insertar) + helper `registrar_auditoria()` con `sanitizar_diff()` por denylist (R6) y verificar test unitario del sanitizador en verde.

## 3. Seguridad JWT + endpoints de auth (GREEN para los tests 1.1–1.4)

- [x] 3.1 Implementar `core/security.py` (hash Argon2id vía `pwdlib`, `crear_par_tokens()` con claims `sub/roles/email/jti/type/iat/exp`, `decodificar_y_validar()` con leeway 30 s) + settings fail-fast (`JWT_SECRET` requerido, `JWT_ACCESS_MIN=15`, `JWT_REFRESH_DAYS=7`) + `.env.example` (placeholders, R7) y verificar los tests 1.1 y 1.2 pasan en verde.
- [x] 3.2 Implementar `POST /api/v1/auth/login` (401 genérico, registra intento fallido para bloqueo, audita éxito/fracaso sin PII en logs) + `GET /api/v1/auth/me` (sin `password_hash` en la respuesta) y verificar los tests 1.2 (existencia no revelada) y 1.3 (expirado → 401) pasan en verde.
- [x] 3.3 Implementar `POST /api/v1/auth/refresh` (rotación: revoca fila vieja + `bl:refresh:{jti}` en Redis con TTL remanente + emite par nuevo; reuso → 401 + revocación de cadena + auditoría) + `POST /api/v1/auth/logout` (revoca + blacklista) con refresh en cookie HttpOnly (`secure`, `samesite=lax`) y verificar los tests 1.4 pasan en verde (TRIANGULATE: rotación, reuso y logout cubiertos).
- [x] 3.4 Pasar `ruff`/`black` y `mypy` limpio en el dominio auth y verificar `pytest tests/integration/test_auth_login_valido_200.py tests/integration/test_auth_expiracion_401.py tests/integration/test_auth_refresh_rotation.py` en verde.

## 4. RBAC + protección de routers C-01 + rate limit (GREEN para los tests 1.5–1.7)

- [x] 4.1 Implementar `PermissionContext` (`get_current_user`, factoría `require_role(*roles)` con 403 genérico + auditoría, `require_admin()`) + matriz única (`domain/auth/matriz.py`, espejo de `03_actores_y_roles.md`) y verificar los tests 1.6 pasan en verde.
- [x] 4.2 Proteger `POST /api/v1/turnos` y routers de C-01 con las dependencias (saldar deuda: quitar los comentarios `DEUDA → C-02` de `main.py`, `core/db.py`, `routers/turnos.py`) sin cambiar el shape 201/409/422 y verificar suite de C-01 sigue en verde + nuevos escenarios 401 de la delta `agenda/crear-turno` en verde.
- [x] 4.3 Implementar rate limit (`rl:login:{ip}:{sha256(email)}` Lua INCR+EXPIRE 60 s, tope 5 → 429 con `Retry-After`) + bloqueo (`fail:`/`lock:` con TTL 900 s, 10 fallidos) con degradación fail-open + warning si Redis cae, y verificar los tests 1.5 pasan en verde.
- [x] 4.4 Cablear `registrar_auditoria()` en crear/cancelar turno (RN-AU-03, base para sobreturno/cobro/cierre/clínica/roles en changes posteriores) y verificar los tests 1.7 pasan en verde.

## 5. Endurecimiento + verificación integral (solo checks, sin código nuevo)

- [x] 5.1 Pasar `ruff`/`black`, `mypy` limpio total, `pytest --cov --cov-fail-under=80` en verde y verificar cobertura ≥80 % en el dominio auth/auditoría.
- [x] 5.2 Verificar inventario de endpoints internos: todo router bajo `/api/v1` (salvo lista explícita de públicos de `03_actores_y_roles.md` §Rutas públicas) exige permiso, y verificar el test de inventario en verde.
- [x] 5.3 Ejecutar suite completa en verde + `openspec validate --change auth-jwt-roles-auditoria` y verificar ambos en verde antes de pedir `/opsx:archive`.
