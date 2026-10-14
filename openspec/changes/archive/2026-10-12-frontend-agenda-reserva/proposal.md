# Proposal — C-10 `frontend-agenda-reserva`

## Why

El backend expone agenda, reserva pública, autogestión por token y señas MP (C-01…C-09 archivados, contratos en `/api/v1` + `/pagar/:token`), pero no existe ninguna superficie usable: recepción sigue sin grilla día/semana operativa y el paciente sin cuenta no puede reservar ni pagar desde la web. Sin este change, US-001–US-004 y US-030 no son operables por sus actores (Flujo 1 reserva online, Flujo 2 confirmación). Governance MEDIO: es UI sobre contratos existentes, sin dinero nuevo ni migraciones; el riesgo está en exponer PII donde el rol no la ve (R6) y en romper el stack fijo (R8).

## What Changes

- SPA React 18 + TS 5 + Vite (nuevo `frontend/`): `features/agenda` (vista día/semana multiprofesional/multisillón, crear/confirmar/reprogramar/check-in, sobreturno auditado), `features/reserva-publica` + `pages/reservar/:slug` (motivo→duración→profesional→slot, DNI+teléfono, gestión con token), `pages/pagar/:token` (checkout/redirección MP de seña), `shared/api-client` + auth (login, refresh rotativo, guarda de rutas por rol); todo en español (Argentina, neutro).
- La UI consume en solo lectura los contratos existentes C-03 (disponibilidad + `POST turnos/publicos`), C-04 (agenda + transiciones + sobreturno), C-05 (autogestión por token), C-08 (`GET /pagar/:token` + redirección MP), C-02 (login/refresh/me + matriz RBAC). **Backend intacto: ningún endpoint cambia su REQUIREMENT.**
- Tests planeados (se ejecutan en apply, datos sintéticos — R0): E2E Playwright del flujo reserva 3 taps (happy path) + gestión por token + pago→MP, y render de agenda con datos mockeados (MSW/fixtures); unit Vitest para api-client, auth/guards y sanitización R6.

## Capabilities

### New Capabilities

- `frontend/agenda-operativa`: grilla día/semana multiprofesional/multisillón para recepción (consume C-04), con crear/confirmar/reprogramar/check-in, sobreturno con motivo y visibilidad por rol (R6).
- `frontend/reserva-publica-ui`: reserva pública sin cuenta en 3 taps motivo→slot→DNI+teléfono más gestión del turno con token — confirmar/cancelar/reprogramar (consume C-03/C-05).
- `frontend/pago-sena-ui`: página `pagar/:token` que inicia el checkout y redirige a Mercado Pago ante seña requerida (consume C-08).
- `frontend/api-client-auth`: cliente HTTP tipado + sesión JWT (login, refresh, `me`) + guarda de rutas por rol y sanitización de errores sin PII (consume C-02).

### Modified Capabilities

_(ninguna — `agenda/*`, `auth/*` y `cobros/*` no cambian sus REQUIREMENTS: la UI consume los contratos C-01…C-09 en solo lectura; `GET /api/v1/agenda`, `POST /api/v1/turnos/publicos`, `.../publicos/:token/...`, `GET /pagar/:token` y `POST /api/v1/auth/*` conservan shape y estados)_

## Impact

- Nuevo: `frontend/` (Vite + React 18 + TS 5 estricto, `any` prohibido — R4) con `src/features/`, `src/shared/`, `src/pages/`, `.env` por entorno (`VITE_API_URL`) + `.env.example` con placeholders (R7); MSW + fixtures sintéticas para dev/test (R0); suites Vitest (unit) + Playwright (E2E 3 taps, reserva→pago→gestión por token) (R5).
- Reusa sin modificar: routers `agenda`, `disponibilidad`, `turnos`, `turnos_publicos`, `autogestion`, `pagar`, `auth` (contratos y códigos `200/201/401/403/404/409/422` intactos), matriz RBAC C-02 (la guarda de rutas la refleja, no la redefine), regla de visibilidad R6 (grilla por rol de C-04, ver-propio mínimo en autogestión).
- No-objetivos explícitos: ficha/odontograma/presupuestos (clínica, fuera de C-10), caja/cierres/reportes/auditoría UI (C-11), bot conversacional (C-12), OS (C-13), lista de espera (C-14), multi-sucursal día 1, app móvil, ARCA (v2).
