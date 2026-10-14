# Design — C-10 `frontend-agenda-reserva`

## Context

Ver `proposal.md` (Why/What). Estado actual (solo lectura): no existe `frontend/` (verificado: `Test-Path frontend → False`); el backend expone contratos estables bajo `/api/v1` — `auth` (`login/refresh/logout/me`, access 15' + refresh rotativo en cookie HttpOnly), `disponibilidad` (`GET ""` por prestación/profesional), `turnos_publicos` (`POST ""` con idempotencia), `autogestion` (`GET /{token}`, `POST /{token}/confirmar|cancelar|reprogramar`), `agenda` (`GET ?vista=dia|semana`), `turnos` (crear/confirmar/reprogramar/check-in/sobreturno), `pagar` (`GET /pagar/:token`, link MP sin JWT) — todos con errores con clave `detalle` y `422` sanitizado sin PII (`main.py`, handlers C-02/C-05). Restricciones: R0 fixtures sintéticas (MSW); R4 TS estricto sin `any`, componentes PascalCase; R5 E2E Playwright + unit Vitest; R6 minimización por rol (grilla C-04, ver-propio mínimo); R7 `VITE_API_URL` por entorno + `.env.example`; R8 React 18 + TS 5 + Vite, sin Next ni frameworks extra.

## Goals / Non-Goals

**Goals:**

- Agenda operativa usable por recepción y pago/reserva públicos consumiendo contratos existentes sin modificarlos.
- Base `api-client` + auth reutilizable por los changes C-11/C-12/C-14 (guarda por rol, sesión, sanitización).
- Suite E2E + unit que deja cada comportamiento del scope en verde con datos sintéticos.

**Non-Goals:**

- Cambiar o versionar endpoints, estados de turno, matriz RBAC o lógica de seña (pertenecen a C-01…C-09).
- Clínica/odontograma, caja, reportes, auditoría UI (C-07/C-11), bot conversacional (C-12), OS (C-13), lista de espera (C-14).
- Diseño final de marca; este change fija estructura, tokens y una superficie memorable por vista (ver decisión 6).

## Decisions

1. **Estructura `features/` + `shared/` + `pages/` (KB §08, sin barrels).** `features/agenda`, `features/reserva-publica`, `shared/api-client`, `shared/auth`, `shared/ui`, `pages/{login, agenda, reservar/:slug, gestionar/:token, pagar/:token}`. Cada feature importa directo del módulo (`bundle-barrel-imports`: nada de `index.ts` agregadores) y las rutas quedan analizables estáticamente (`bundle-analyzable-paths`). Alternativa descartada: carpetas por tipo (`components/hooks`) — dispersa la lógica de reserva 3 taps entre capas y rompe R2-front (capas por dominio, no por tipo).
2. **`api-client` + auth como base (standard client/vercel + server-auth adaptado a SPA).** Cliente `fetch` tipado por recurso con `VITE_API_URL` solo de env, access en memoria, rotación única de refresh ante `401` (`client-swr-dedup` adaptado: deduplicar la renovación, no cachear turnos), guarda de rutas que refleja la matriz C-02 deny-by-default. Access nunca en `localStorage` (`client-localstorage-schema`: solo preferencia no sensible como vista día/semana). Alternativa descartada: axios + interceptores con token en `localStorage` — superficie XSS mayor y dependencia extra sin necesidad.
3. **MSW + fixtures sintéticas como contrato de dev/test (R0).** Handlers MSW por recurso que replican shapes y códigos reales (`200/201/401/403/404/409/422` + `slots_alternativos`), fixtures con pacientes/profesionales ficticios; jamás datos reales ni snapshots del backend. Los mismos handlers alimentan Vitest y Playwright. Alternativa descartada: mockear `fetch` por test — cada test inventa su shape y el drift contra el contrato real no se detecta.
4. **E2E primero para flujos, unit para lógica (R5).** Playwright: reserva 3 taps happy path, gestión por token (confirmar/cancelar/reprogramar), pago→redirección MP mockeada a nivel request (`playwright-cli route`), agenda render con MSW; Vitest: api-client (rotación, idempotencia), guards por rol, validadores AR, sanitización R6. La pirámide se invierte a propósito: el valor de C-10 está en los flujos E2E, no en componentes aislados. Alternativa descartada: solo unit con Testing Library — deja sin cubrir el 3-taps y la redirección MP, que son el criterio de aceptación.
5. **Español AR neutro + i18n desde día 1.** Copy en español argentino neutro (voseo evitado en botones: "Confirmar turno", "Elegí" → "Elegir"), catálogo de mensajes centralizado (`shared/i18n/es-AR.ts`) con claves por flujo para que C-11/C-12 reutilicen; fechas en `America/Argentina_Buenos_Aires`. Alternativa descartada: strings hardcodeados por componente — el costo de unificar copy en C-11 supera el de un catálogo mínimo hoy.
6. **Diseño por rol con 1 elemento memorable por superficie (standards frontend-design + web-design-guidelines).** Agenda: la grilla día multiprofesional como pieza memorable (columnas por profesional/sillón, `content-visibility` en semana larga — `rendering-content-visibility`); reserva pública: stepper de 3 pasos con progreso visible y accesible (foco visible, `aria-current`, teclado completo, `prefers-reduced-motion` respetado); estados vacíos que invitan a actuar y errores que explican cómo seguir (sin disculpas ni vaguedad). Alternativa descartada: kit de cards SaaS genérico — indistinguible y con peor densidad para una grilla operativa.
7. **Rendimiento SPA: paralelo donde hay independencia, transiciones donde hay espera (`async-parallel`, `rerender-transitions`, `rerender-no-inline-components`).** Disponibilidad + catálogos en `Promise.all`, `startTransition` en cambios de vista día/semana, componentes memoizados solo donde hay cómputo (celdas de grilla), nada de componentes definidos dentro de componentes. Sin SSR/Next (R8): SPA Vite + `docker-compose` servicio `web`. Alternativa descartada: Next.js SSR — viola R8 y añade servidor sin necesidad (el contenido es dinámico por rol/token).
8. **Privacidad por construcción (R6, Ley 25.326).** Tipos que separan `TurnoOperativo` (grilla: sin DNI/tel) de `TurnoPropio` (gestión por token: ver-propio mínimo); sanitizador central en `api-client` que elimina DNI/tel/HCE/hashes/tokens de errores, consola y reportes; `odontologo` sin control de sobreturno en DOM. Alternativa descartada: filtrar PII en cada componente — un olvido expone datos; el sanitizador central hace imposible el descuido.

## Risks / Trade-offs

- [Riesgo] Drift MSW vs backend real → Mitigación: shapes y códigos copiados de los routers C-01…C-09 + un E2E de contrato que valida cada fixture contra el OpenAPI (`/docs`) en apply.
- [Riesgo] `409` concurrente mal gestionado pierde datos del formulario → Mitigación: spec exige conservar inputs + alternativos; E2E lo cubre con doble envío.
- [Riesgo] Token en URL queda en historial → Mitigación: gestión/pago son tokens opacos de un solo propósito (C-05/C-08), nunca JWT; la UI no los persiste ni los reporta.
- [Trade-off] SPA sin SSR: primer paint con esqueleto → Mitigación: esqueleto accesible + `Suspense` por vista (`async-suspense-boundaries` adaptado), sin waterfalls (requests de la vista en paralelo al montar la ruta).

## Open Questions

- Ninguna que cambie specs, enfoque o tasks: el slug multiconsultorio (`reservar/:slug`) se trata como identificador opaco que el backend resuelve (una sede "Consultorio" en MVP); si C multi-sede futuro lo redefine, solo cambia el resolver, no las vistas.
