# Design — C-02 `auth-jwt-roles-auditoria`

## Context

Ver `proposal.md` (Why/What). Estado actual: backend C-01 con `Usuario` (email único, `password_hash`, `rol`, `activo`) pero sin ningún mecanismo de autenticación; `POST /api/v1/turnos` abierto con deuda explícita (`get_current_user` en `main.py`, `core/db.py`, `routers/turnos.py`). No existe tabla de sesiones ni `AuditoriaLog`. Redis ya está en el Compose canónico (hoy solo cableado mínimo para futuros workers). Restricciones: capas separadas + todo schema vía Alembic (R2); type hints siempre (R1); 401 genérico + jamás PII/hashes/tokens en errores/logs (R6); secretos solo por env (R7); stack fijo intacto (R8); el exclusion constraint de agenda no se toca (R3).

## Goals / Non-Goals

**Goals:**

- Saldar el hook `get_current_user`: identidad verificable en cada request interno y protección de los routers de C-01 sin cambiar su shape 201/409/422.
- Rotación de refresh con detección de reuso y auditoría RN-AU-03 desde el día 1 (base que C-11 expone como bitácora consultable).

**Non-Goals:**

- Recuperación de contraseña (flujo con token por email/WhatsApp) → se difiere a C-10/C-11 (requiere frontend y plantillas de notificación); el login nace sin "olvidé mi clave".
- RLS en Postgres → NO se introduce (ver decisión 8); el control vive en la capa de aplicación.
- Frontend de login / guarda de roles SPA → C-10 (aquí solo API + cookie).

## Decisions

1. **Hash: Argon2id vía `pwdlib[argon2]`** (nunca `passlib`, sin mantenimiento). Racional: Argon2id es el ganador del PHC, memory-hard contra GPU/ASIC, y `pwdlib` es el backend mantenido que recomienda la doc actual de FastAPI. Solo existe un admin demo seed (hash generado en el seed, R0); sin hashes legacy que migrar, no se necesita estrategia de re-hash (si apareciera un bcrypt viejo, se rechaza y se rota la credencial en el seed).
2. **JWT: `PyJWT` con HS256** (nunca `python-jose`, sin mantenimiento). Racional: librería mínima y auditada, sin dependencias cripto pesadas; HS256 con `JWT_SECRET` de 32+ bytes es suficiente para firma simétrica emisor=verificador (mismo monolito). Validación explícita en `core/security.py`: firma, `exp` (leeway 30 s por skew), `type` esperado por endpoint (`access` vs `refresh`) y presencia de `sub`/`jti`. Alternativa descartada: RS256 — añade gestión de par de claves sin beneficio con un único emisor.
3. **Fuente de verdad de sesiones en Postgres + Redis como fast-path.** Tabla `sesion_refresh` (`jti` PK, `usuario_id` FK, `expira_at`, `revocado` bool, `creado_en`; índice `(usuario_id, expira_at)`): la rotación verifica firma + `type=refresh` + fila existente no revocada y no expirada → revoca la fila vieja, inserta la fila nueva y emite el par nuevo. Redis guarda `bl:refresh:{jti}` (solo jtis revocados, TTL = vida remanente) para rechazar el reuso sin tocar la DB; ante caída de Redis la fila DB manda (corrección preservada, solo se pierde el atajo). Reuso de un refresh revocado → `401` + revocación de **toda la cadena de sesiones del usuario** (señal de robo) + evento de auditoría.
4. **Rate limit en Redis con claves hasheadas (R6).** `POST /auth/login`: contador `rl:login:{ip}:{sha256(email)}` con `INCR` + `EXPIRE 60` atómicos (Lua), tope 5/60 s → `429` con `Retry-After`. El email NUNCA va en claro en la clave (hash SHA-256 en minúsculas/trim). Bloqueo por intentos: `fail:login:{sha256(email)}` (TTL 900 s); 10 fallidos → `lock:login:{sha256(email)}` TTL 900 s → `429` aunque la credencial sea correcta. Claves, topes y TTLs parametrizados por env (`RATE_LOGIN_MAX`, `RATE_LOGIN_WINDOW_S`, `LOCKOUT_MAX_INTENTOS`, `LOCKOUT_S`).

    > NOTA GREEN (delta mínimo, sin reescribir): no hay Redis local en la máquina de dev, así que los tests usan `fakeredis` (API asyncio) tras la capa `app/core/redis_client.py` (`USAR_REDIS_FALSO=true`; cada `create_app()` recibe una instancia propia → aislamiento por test); producción usa Redis real vía `REDIS_URL` (compose). Como `fakeredis` no ejecuta Lua, el incremento+expiración se implementa por pipeline INCR+EXPIRE ("o equivalente" del design): el comportamiento observable (tope 5/60 s, 429 + `Retry-After`) es idéntico y la suite lo verifica.
5. **`PermissionContext` como dependencias FastAPI componibles.** `get_current_user` (decodifica access, carga `Usuario` activo, `401` si no) → factoría `require_role(*roles)` que devuelve dependencia (`403` + auditoría si el rol no está en el claim) → atajo `require_admin()`. Los routers internos declaran su permiso en `dependencies=[...]`; deny-by-default significa que todo router nuevo sin permiso explícito se rechaza en review (regla verificada por test: endpoint sin permiso → 403/401). La matriz vive en un único módulo (`domain/auth/matriz.py`) espejo de `03_actores_y_roles.md` para que C-11 la reuse en reportes.
6. **Refresh en cookie HttpOnly (`secure`, `samesite=lax`, `path=/api/v1/auth`)** y access en cuerpo JSON (el SPA de C-10 lo guarda en memoria, nunca en `localStorage`). `SameSite=Lax` bloquea el POST cross-site, que es el vector CSRF relevante para `refresh`/`logout`; no se añade token CSRF doble-submit en este change (se reevalúa en C-10 con el cliente real).
7. **Auditoría a nivel de servicio, con sanitizador central.** Helper `registrar_auditoria(session, accion, entidad, entidad_id, diff, usuario_id?, ip?)` invocado desde los servicios (no desde routers), con `sanitizar_diff()` que elimina por denylist las claves `dni, telefono, email?, password_hash, token*, anamnesis, ...` — nota: `email` SÍ se audita como identificador de login (es la identidad, no PII sorpresiva), pero jamás junto a credenciales. `GET /api/v1/auditoria` NO se expone aquí (llega en C-11); en C-02 la tabla solo se escribe.
8. **Sin RLS (deuda de C-01 resuelta con justificación).** Un único rol de app + pool compartido; la matriz se enforcea en dependencias FastAPI + servicios, con tests por rol. RLS duplicaría la matriz en SQL, rompería los workers con rol de servicio y no aporta con sede única; se reevalúa solo si aparece multitenancy real.
9. **Configuración fail-fast (R7).** `JWT_SECRET` requerido (sin default; la app no levanta sin él), `JWT_ACCESS_MIN=15`, `JWT_REFRESH_DAYS=7`. `.env.example` solo con placeholders y los defaults no sensibles.

## Risks / Trade-offs

- [Riesgo] Robo de refresh entre rotación y expiración → Mitigación: ventana de uso de 7 d con rotación en cada uso + revocación de cadena ante reuso + logout explícito; el access de 15' acota el daño.
- [Riesgo] Redis caído: rate limit ciego y blacklist sin fast-path → Mitigación: la DB es fuente de verdad (el refresh sigue validándose); el rate limit degrada a fail-open con warning estructurado (disponibilidad primero, regla global de degradación graceful) y alerta a logs; documentado para endurecer en C-06 (workers).
- [Riesgo] Clock skew access 15' rechaza tokens válidos → Mitigación: leeway de 30 s solo en `exp`; `iat` futuro más allá del leeway → 401.
- [Riesgo] `403` que filtra qué roles existen → Mitigación: mensaje genérico "sin permiso" sin enumerar roles permitidos; el detalle (recurso, requerido) solo va a `AuditoriaLog`.
- [Riesgo] Bypass de autorización por router nuevo sin `dependencies` → Mitigación: test de inventario que falla si un endpoint interno carece de permiso (grupo 4 de tasks) + checklist en review.
- [Trade-off] HS256 simétrico vs RS256: se gana simplicidad operativa (un secreto) a cambio de no poder delegar verificación a terceros; aceptado porque emisor = verificador = monolito.
- [Trade-off] Cookie HttpOnly exige HTTPS en producción para `secure`; en dev local se permite `secure=false` solo vía env explícita (`COOKIE_SECURE=false`), nunca por default.

## Migration Plan

1. `apply` ejecuta migración 002 en DB de dev/test (tablas `sesion_refresh` + `auditoria_log` + índices; sin backfill: no hay sesiones previas).
2. Seed: el admin demo pasa a crearse con hash Argon2id generado al momento del seed (R0; credencial demo a rotar en primer login real).
3. Rollback: `alembic downgrade -1` (revierte ambas tablas; los JWT emitidos quedan inválidos por depender de filas inexistentes → fail-closed, correcto).
4. Deploy: `docker compose up --build`; verificación: login → me → refresh → logout → reuso → 401 (smoke manual del grupo 5).

## Open Questions

- ¿Recuperación de contraseña por email o por WhatsApp con código (coherente con RN-PU-01)? No bloquea: se define en C-10/C-11 cuando exista el canal de notificación; la API reserva `POST /api/v1/auth/recuperar` como nombre.
- ¿Sesiones multi-dispositivo visibles/revocables por el usuario ("cerrar todas")? El modelo lo soporta (una fila por dispositivo); el endpoint de gestión se propone para C-11 junto a la bitácora.
