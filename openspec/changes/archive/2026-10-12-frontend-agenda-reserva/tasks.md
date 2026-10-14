# Tasks — C-10 `frontend-agenda-reserva`

> Governance MEDIO (UI sobre contratos estables, sin migraciones ni dinero nuevo) — fase PROPOSE: este archivo es el plan. Ninguna tarea se ejecuta sin aprobación explícita del usuario (`apply`). Orden: base → reserva → gestión → agenda → pago → verificación integral. Todo dato sintético (MSW/fixtures ficticias, jamás reales — R0); TS estricto sin `any`, componentes PascalCase (R4); capas por dominio `features/` vs `shared/` vs `pages/` (R2-front); backend C-01…C-09 solo lectura, ningún endpoint cambia (R3 N/A red); cada comportamiento con test en verde, E2E Playwright + unit Vitest (R5); DNI/tel/HCE/hashes/tokens jamás en vistas, consola, errores ni reportes donde el rol no los ve (R6); `VITE_API_URL` por entorno + `.env.example` con placeholders (R7); React 18 + TS 5 + Vite, sin Next ni frameworks extra (R8).

## 1. Base frontend + api-client + auth + env (tests en ROJO primero)

- [x] 1.1 Escribir los tests unit en rojo de `shared/api-client` (base `VITE_API_URL`, access en memoria, rotación única de refresh ante `401` con 3 requests en vuelo, idempotencia configurable, reintento limitado ante red/`5xx` sin PII en logs) con fixtures MSW sintéticas y verificar que FALLAN en rojo (cliente aún no existe).
- [x] 1.2 Escribir los tests unit en rojo de `shared/auth` + guarda de rutas (login/logout/`me`, deny-by-default por rol, `429` con aviso accionable, errores `401`/`403` sanitizados en español) y verificar que FALLAN en rojo.
- [x] 1.3 Escribir los tests unit en rojo de validadores AR + sanitizador R6 (DNI 7–8 dígitos, teléfono E.164 `+54…`, eliminación de DNI/tel/HCE/hashes/tokens de errores y reportes) y verificar que FALLAN en rojo.
- [x] 1.4 Crear el scaffolding Vite React-TS (`frontend/`, `VITE_API_URL` por entorno + `.env.example` con placeholders — R7, `tsconfig` estricto, lint) sin lógica de negocio y verificar `tsc --noEmit` y el dev server levantan en verde.
- [x] 1.5 Implementar `shared/api-client`, `shared/auth` (guarda por rol que refleja C-02), `shared/i18n/es-AR.ts` y MSW + fixtures sintéticas por recurso (shapes y códigos copiados de los routers C-01…C-09) y verificar los tests 1.1–1.3 pasan en verde.

## 2. Reserva pública 3 taps (E2E happy path + alternos)

- [x] 2.1 Escribir en rojo el E2E Playwright de reserva 3 taps (motivo→slot→DNI+tel sintéticos → `reservado` + `token_publico`, con MSW) y verificar que FALLA en rojo (vistas aún no existen).
- [x] 2.2 Escribir en rojo los E2E de doble envío idempotente, `409` con alternativos conservando inputs, y validación AR por campo sin envío (R6: nada en consola) y verificar que FALLAN en rojo.
- [x] 2.3 Implementar `features/reserva-publica` + `pages/reservar/:slug` (stepper accesible de 3 pasos, `Promise.all` para disponibilidad+catálogos, `startTransition` entre pasos, estados vacíos que invitan a actuar, copy en español) y verificar los E2E 2.1–2.2 pasan en verde.

## 3. Gestión del turno con token (ver-propio mínimo)

- [x] 3.1 Escribir en rojo los E2E de gestión con token (confirmar → `confirmado`; cancelar en término → `cancelado`; cancelar fuera de término → `422` con política; reprogramar conservando token; token inválido → no-encontrado genérico sin filtrar datos) y verificar que FALLAN en rojo.
- [x] 3.2 Implementar `pages/gestionar/:token` (ver/confirmar/cancelar/reprogramar contra C-05, tipos `TurnoPropio` separados de `TurnoOperativo`, repoblado tras errores recuperables) y verificar los E2E 3.1 pasan en verde.

## 4. Agenda operativa día/semana (recepción por rol)

- [x] 4.1 Escribir en rojo el E2E de agenda día (grilla multiprofesional/multisillón con MSW, orden cronológico, estado vacío accionable) + unit de minimización R6 (ninguna vista/log/error contiene DNI/tel/HCE/hashes/tokens) y verificar que FALLAN en rojo.
- [x] 4.2 Escribir en rojo los E2E de crear/confirmar/check-in, reprogramar con token conservado, `409` con alternativos sin mutar, sobreturno con motivo (solo `recepcion`/`admin`, oculto a `odontologo`) y semana por ventana con `422` accionable, y verificar que FALLAN en rojo.
- [x] 4.3 Implementar `features/agenda` + `pages/agenda` (grilla día/semana con `content-visibility`, filtros profesional/sillón, celdas memoizadas sin componentes inline, guarda `turnos`, sanitización central) y verificar los E2E/unit 4.1–4.2 pasan en verde.

## 5. Pago de seña con redirección MP

- [x] 5.1 Escribir en rojo los E2E de `pages/pagar/:token` (resumen ARS + redirección MP única ante doble clic, pendiente/rechazado con reintento sin declarar confirmado, token inválido genérico) con red MP mockeada a nivel request y verificar que FALLAN en rojo.
- [x] 5.2 Implementar `pages/pagar/:token` (resuelve link C-08, redirección única, estados en español, sin persistir el token) y verificar los E2E 5.1 pasan en verde.

## 6. Verificación integral (solo checks, sin código nuevo)

- [x] 6.1 Pasar `tsc --noEmit` estricto (cero `any`), lint, `vitest run` y `playwright test` en verde con MSW/fixtures sintéticas (cero llamadas de red real salvo redirección MP mockeada) y verificar cobertura de los flujos del scope (3 taps, gestión por token, pago→MP, agenda por rol, R6) más regresión de contrato contra el OpenAPI (`/docs`) sin modificar el backend.
  - DEUDA explícita (GREEN 2026-10-12, backend caído `localhost:8000`): la regresión viva contra `/docs` NO se ejecutó; en su lugar se hizo cruce estático solo-lectura routers↔MSW (ver retorno del change). Brechas mock-vs-real anotadas: (a) MSW sirve `/agenda` y `POST /turnos*` sin JWT (el backend exige permiso `turnos`; la app igual envía el header con sesión y sin sesión pide login en prod); (b) semana usa `ventana` ficticia (el backend pagina por `desde/hasta`); (c) alta staff sin `paciente`/`paciente_id` (el backend exige uno; selector de paciente = C-11); (d) `GET /pagar/:token` reenvía `?firma=` cuando la página lo trae (link HMAC C-03/C-08).
- [x] 6.2 Ejecutar suite completa en verde + `openspec validate --change frontend-agenda-reserva` y `openspec status --change frontend-agenda-reserva`, y verificar ambos en verde antes de pedir `/opsx:archive` (usar la forma posicional o `--change` que acepte cada subcomando).
