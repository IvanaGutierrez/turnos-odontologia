# CHANGES — Secuencia de Implementación

> Índice canónico de todos los changes del proyecto **turnos-odontologia** (sistema de turnos odontológicos para Argentina).
> Cada change es atómico: un agente puede implementarlo en una sesión (~4-6 horas).
> **Leer este archivo antes de ejecutar cualquier `/opsx:propose`.**
> Stack fijo: FastAPI + JWT + SQLAlchemy + PostgreSQL + Redis + Docker/Compose; React + TypeScript + Vite. Leyes 25.326 y 26.529.
> Excluidos del roadmap (v2+, NO MVP ni v1.5): facturación ARCA nativa, periodontograma, IA en radiografías, app móvil.

---

## Cómo usar este documento

1. Identificar el change a implementar (verificar que sus dependencias están en `openspec/changes/archive/`).
2. Leer los docs de la knowledge-base indicados en "Leer antes".
3. Ejecutar `/opsx:propose <nombre-del-change>`.
4. Al terminar el change, archivarlo con `/opsx:archive <nombre-del-change>`.
5. Marcar el checkbox `[x]` en este archivo.

---

## Árbol de dependencias

```
C-01 crear-turno-anti-solapamiento (foundation + modelos + exclusion)   ← PRIMER CHANGE (mandato usuario)
  └── C-02 auth-jwt-roles-auditoria                                     ← desbloquea recursos protegidos
        └── C-03 disponibilidad-real-reserva-online
              └── C-04 agenda-dia-semana-recepcion
                    │
                    ├── C-05 autogestion-paciente                        ← camino crítico
                    │     ├── C-06 recordatorios-whatsapp                ← fin camino crítico MVP
                    │     │     └── C-12 confirmacion-conversacional (v1.5)
                    │     ├── C-08 sena-mercadopago
                    │     │     ├── C-09 caja-cierre-diario
                    │     │     │     └── C-11 roles-reportes-auditoria
                    │     │     └── C-14 lista-espera-inteligente (v1.5, + C-06)
                    │     └── C-13 validacion-os-preventiva (v1.5)
                    │
                    ├── C-07 ficha-odontograma-presupuesto
                    │
                    └── C-10 frontend-agenda-reserva (+ C-05, + C-08)
```

### Paralelismo por fase

> Cada "gate" es un punto de sincronización. Los changes dentro de un grupo pueden ejecutarse en paralelo.

```
GATE 0: ninguna
  → C-01 (solo)

GATE 1: C-01 ✓
  → C-02 (solo)

GATE 2: C-02 ✓
  → C-03 (solo)

GATE 3: C-03 ✓
  → C-04 (solo)

GATE 4: C-04 ✓                          ← FORK (2 paralelos)
  → C-05 autogestion-paciente           [Agente A]
  → C-07 ficha-odontograma-presupuesto  [Agente B]

GATE 5: C-05 ✓                          ← FORK (3 paralelos)
  → C-06 recordatorios-whatsapp         [Agente A]
  → C-08 sena-mercadopago               [Agente B]
  → C-13 validacion-os-preventiva       [Agente C]

GATE 6: C-06 ✓
  → C-12 confirmacion-conversacional    [Agente A]
  → C-14 lista-espera-inteligente       [Agente C — si C-08 ✓]

GATE 7: C-08 ✓
  → C-09 caja-cierre-diario             [Agente B]
  → C-10 frontend-agenda-reserva        [Agente C]

GATE 8: C-09 ✓
  → C-11 roles-reportes-auditoria       [Agente B]
```

### Camino crítico (6 changes — mínimo irreducible)

```
C-01 → C-02 → C-03 → C-04 → C-05 → C-06
```

> Prioridad N°1 del MVP (mandato usuario): gestión de turnos y agenda multiprofesional/multisillón
> con prevención de solapamientos, confirmación y recordatorios. El camino crítico cubre exactamente eso.

### Plan óptimo con 3 agentes

```
Paso │ Agente A (Backend Core) │ Agente B (Backend Aux)      │ Agente C (Frontend/Integraciones)
─────┼─────────────────────────┼─────────────────────────────┼─────────────────────────────────
  1  │ C-01 anti-solapamiento  │             —               │         —
  2  │ C-02 auth               │             —               │         —
  3  │ C-03 disponibilidad     │             —               │         —
  4  │ C-04 agenda recepción   │             —               │         —
  5  │ C-05 autogestión        │ C-07 ficha/odontograma      │         —
  6  │ C-06 recordatorios WA   │ C-08 seña MP                │ C-13 validación OS
  7  │ C-12 conversacional     │ C-09 caja/cierre            │ C-14 lista de espera
  8  │           —             │ C-11 roles/reportes         │ C-10 frontend agenda/reserva
```

---

## FASE 0 — Agenda crítica (camino crítico del MVP)

> C-01 a C-06 son secuenciales (cadena crítica). C-07 puede arrancar en paralelo con C-05 (GATE 4).

### [C-01] `crear-turno-evitando-solapamientos-profesional-sillon-box`

- **Nombre exacto (mandato usuario)**: `Crear un turno evitando solapamientos por profesional y por sillón/box`
- **Estado**: `[x]` archivado (2026-10-07)
- **Scope**: Núcleo de agenda con garantía física anti-doble-reserva (el scaffolding foundation-default va plegado aquí por mandato: el primer change es el turno, no el setup pelado)
  - Scaffolding mínimo: `backend/app/main.py` (FastAPI, routers `/api/v1`), `core/` (settings, db, logger, exceptions), `docker-compose.yml` (api + postgres + redis + worker), `.env.example`, Alembic inicializado
  - Modelos: `Usuario`, `Paciente` (dni único, teléfono E.164 AR, consentimiento_hc), `Profesional`, `Sillon`, `Prestacion` (motivo + duracion_min + requiere_sena), `Turno` (inicio, fin, estado, canal, token_publico único)
  - Migración 001: tablas agenda + `EXCLUDE USING gist` no-solapamiento por (profesional, rango) y por (sillon, rango) donde aplique
  - `POST /api/v1/turnos` — crea turno con `fin = inicio + prestacion.duracion` (override solo con motivo registrado); ante colisión concurrente la DB manda → 409 + slots alternativos
  - Seed mínimo: 1 admin, 1 sede "Consultorio" + 1 sillón demo, catálogo 6 prestaciones (consulta 30', limpieza 45', endodoncia 60', extracción 45', ortodoncia control 30', urgencia 20'), profesional y paciente `demo`
  - Tests: doble reserva concurrente por profesional → 409; por sillón → 409; `fin` calculado desde prestación; DNI/teléfono AR inválidos rechazados
- **Dependencias**: ninguna
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §Turno, §ERD (exclusion constraint)
  - `knowledge-base/05_reglas_de_negocio.md` §RN-AG-01/02/03
  - `knowledge-base/08_arquitectura_propuesta.md` §Patrones (Exclusion constraint PG), §Estructura de directorios
  - `knowledge-base/02_descripcion_general.md` §Stack

---

### [C-02] `auth-jwt-roles-auditoria`

- **Estado**: `[x]` archivado (2026-10-07)
- **Scope**: Autenticación JWT con RBAC y auditoría de acciones sensibles
  - `POST /api/v1/auth/login` — JWT access 15' + refresh 7 d, rate limit 5/60s por IP+email, hash Argon2/bcrypt, bloqueo por intentos
  - `POST /api/v1/auth/refresh` — rotación de refresh, blacklist del anterior; `POST /api/v1/auth/logout` — invalida refresh; `GET /api/v1/auth/me`
  - Claims JWT: `sub`, `roles`, `email`, `jti`, `type`, `iat`, `exp`; refresh en cookie HttpOnly (secure, samesite=lax)
  - `PermissionContext`: `require_role()`, `require_admin()`, deny-by-default según matriz (admin/odontologo/recepcion)
  - Migración 002: sesiones/refresh + tabla `AuditoriaLog` (accion, entidad, entidad_id, diff jsonb)
  - Tests: login ok/expirado, refresh rotation, rate limit, acceso denegado por rol
- **Dependencias**: C-01
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/03_actores_y_roles.md` §RBAC — Matriz de permisos
  - `knowledge-base/05_reglas_de_negocio.md` §RN-AU-01/02/03
  - `knowledge-base/08_arquitectura_propuesta.md` §Seguridad
  - `knowledge-base/04_modelo_de_datos.md` §Usuario, §AuditoriaLog

---

### [C-03] `disponibilidad-real-reserva-online`

- **Estado**: `[x]` archivado (2026-10-08)
- **Scope**: Disponibilidad real y reserva pública 24/7 sin cuenta (US-001, US-002)
  - `GET /api/v1/disponibilidad?prestacion_id&profesional_id&desde&hasta` — slots = horario profesional − bloqueos − turnos; agenda por motivo (motivo→duración→profesional→slot), sin huecos fantasma
  - `POST /api/v1/turnos/publicos` — crea turno `reservado` con DNI + teléfono (verificación por código en primera reserva), token de idempotencia, devuelve `token_publico`; rate limit por IP + teléfono
  - Link/QR compartible (`/reservar/:slug`) funciona sin login; si la prestación exige seña, devuelve link de pago (lo cobra C-08)
  - Modelos: `Horario/Bloqueo` profesional; Migración 003
  - Tests: slots excluyen bloqueos/turnos; doble submit idempotente; rate limit; 409 con alternativos
- **Dependencias**: C-01, C-02
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-001, §US-002
  - `knowledge-base/07_flujos_principales.md` §Flujo 1 (incluye casos de error 409/MP)
  - `knowledge-base/05_reglas_de_negocio.md` §RN-PU-01/02/03, §RN-AG-04
  - `knowledge-base/03_actores_y_roles.md` §Rutas públicas

---

### [C-04] `agenda-dia-semana-recepcion`

- **Estado**: `[x]` archivado (2026-10-09)
- **Scope**: Operación diaria de recepción sobre agenda multiprofesional/multisillón (US-004)
  - `GET /api/v1/agenda?vista=dia|semana&profesional_id&sillon_id` — grilla multiprofesional y multisillón
  - Crear/confirmar/reprogramar/check-in (`presente`) desde recepción; reprogramación conserva `token_publico`, turno original → `reprogramado`
  - Sobreturno solo recepcion/admin con `sobreturno=true` + auditoría obligatoria
  - CRUD config agenda: `profesionales`, `sillones`, `prestaciones`, `horarios/bloqueos` (admin CRUD, resto R según matriz)
  - Tests: check-in, sobreturno sin permiso → 403 + log, reprogramación conserva token
- **Dependencias**: C-02, C-03
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-004
  - `knowledge-base/05_reglas_de_negocio.md` §RN-AG-05/06/07
  - `knowledge-base/03_actores_y_roles.md` §RBAC — Matriz de permisos
  - `knowledge-base/04_modelo_de_datos.md` §Profesional, §Sillon, §Prestacion, §Turno

---

### [C-05] `autogestion-paciente-confirmar-cancelar-reprogramar`

- **Estado**: `[x]` archivado (2026-10-10)
- **Scope**: El paciente autogestiona su turno con el token público, sin llamar (US-003)
  - `GET /api/v1/turnos/publicos/:token` — ver turno propio; `POST .../:token/confirmar|/cancelar|/reprogramar`
  - Cancelación respeta antelación mínima configurable (`CANCEL_MIN_HOURS`, default 12 h); fuera de término → rechazo con política del consultorio
  - Reprogramación reutiliza validación de slots y máquina de estados de C-04; token rotatable ante sospecha de fuga
  - Máquina de estados: `reservado|confirmado|presente|atendido|cancelado|ausente|reprogramado` con transiciones válidas
  - Tests: confirmar/cancelar/reprogramar con token; cancelación tardía rechazada; token inválido → 404 sin filtrar datos (Ley 25.326 minimización)
- **Dependencias**: C-04
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-003
  - `knowledge-base/07_flujos_principales.md` §Flujo 1, §Flujo 2
  - `knowledge-base/05_reglas_de_negocio.md` §RN-AG-05/07, §RN-PU-02
  - `knowledge-base/04_modelo_de_datos.md` §Turno (estados, token_publico)

---

### [C-06] `recordatorios-whatsapp`

- **Estado**: `[x]` archivado (2026-10-11)
- **Scope**: Confirmación + recordatorios automáticos por WhatsApp Cloud API con workers Redis (US-010)
  - Integración `infrastructure/whatsapp`: plantillas utility aprobadas (confirmación inmediata + recordatorio 24 h + aviso 3 h, configurable); marketing exige opt-in aparte
  - Workers Redis: cola de envíos con reintentos, idempotencia por (turno_id, tipo_aviso); webhook `POST /webhooks/whatsapp` con verificación de firma
  - Fallback email/SMTP + SMS gateway cuando el paciente no tiene WhatsApp (RN-NO-04)
  - Degradación graceful: si WA/MP caen, flujo manual + aviso a recepción, nunca se pierde el turno
  - Tests: secuencia de 3 envíos, webhook con firma inválida → 401, reintento sin duplicar
- **Dependencias**: C-05
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-010
  - `knowledge-base/07_flujos_principales.md` §Flujo 2
  - `knowledge-base/05_reglas_de_negocio.md` §RN-NO-01/02/04
  - `knowledge-base/11_integraciones_locales.md` §1 WhatsApp Cloud API
  - `knowledge-base/08_arquitectura_propuesta.md` §Patrones (Workers + colas Redis)

---

## FASE 1 — Clínica y cobros

> C-07 arranca en GATE 4 (paralelo a C-05). C-08/C-09 van tras C-05 (GATES 5/7).

### [C-07] `ficha-odontograma-presupuesto`

- **Estado**: `[x]` archivado (2026-10-11)
- **Scope**: Ficha clínica + odontograma FDI + presupuestos/planes en un solo flujo (US-020)
  - Modelos: `Ficha` (anamnesis jsonb, firma profesional), `OdontogramaEntry` (pieza_fdi 11–48, catálogo de estados versionado ~18), `Evolucion`, `Presupuesto/PresupuestoItem/PlanTratamiento` (etapas jsonb, estados borrador→aprobado→pagado)
  - Sin consentimiento informado registrado no se crea HCE (Ley 26.529, RN-CL-01); recepción no edita datos clínicos (solo contacto); toda edición clínica registra firmante
  - Endpoints: `POST /api/v1/fichas`, `/odontograma` (batch por pieza), `/presupuestos` (nace de hallazgos) + firma del paciente (táctil/registro) antes de plan con seña
   - Migración 008; cifrado en reposo HCE; exportación de datos del paciente garantizada (Ley 25.326)
  - Tests: crear HCE sin consentimiento → 422; recepción editando clínica → 403; presupuesto desde odontograma
- **Dependencias**: C-02, C-04
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-020
  - `knowledge-base/07_flujos_principales.md` §Flujo 3
  - `knowledge-base/05_reglas_de_negocio.md` §RN-CL-01/02/03/04
  - `knowledge-base/04_modelo_de_datos.md` §Ficha, §OdontogramaEntry, §Presupuesto
  - `knowledge-base/03_actores_y_roles.md` §RBAC (clínica por rol)

---

### [C-08] `sena-mercadopago-webhook`

- **Estado**: `[x]` archivado (2026-10-11)
- **Scope**: Cobro de señas por Mercado Pago con webhook idempotente (US-030)
  - Crear preferencia MP con metadata (turno_id/presupuesto_id) → link de pago (`GET /pagar/:token`); moneda ARS
  - Webhook `POST /webhooks/mercadopago` — verifica firma (x-signature), idempotencia por `mp_payment_id` único; al acreditar: pago → `acreditado`, turno con seña requerida → `confirmado`, movimiento de caja MP + comprobante por WhatsApp
  - Primera vez y tratamientos largos requieren seña (monto/% configurable por prestación); pago rechazado → visible + reintento, turno sigue pendiente
  - Modelo `Pago` (mp_payment_id/mp_preference_id únicos); Migración 005
  - Tests: webhook duplicado → 200 sin doble acreditación; firma inválida → 401; seña pendiente no confirma turno
- **Dependencias**: C-05
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-030
  - `knowledge-base/07_flujos_principales.md` §Flujo 4
  - `knowledge-base/05_reglas_de_negocio.md` §RN-PA-01/02/03
  - `knowledge-base/11_integraciones_locales.md` §2 Mercado Pago
  - `knowledge-base/04_modelo_de_datos.md` §Pago

---

### [C-09] `caja-cierre-diario`

- **Estado**: `[x]` archivado (2026-10-12)
- **Scope**: Caja con cierre diario y conciliación (US-031)
  - `POST /api/v1/caja/movimientos` — ingresos/egresos por método (efectivo/transferencia/tarjeta/MP) con usuario y concepto registrados
  - `POST /api/v1/caja/cierre` — compara totales vs pagos acreditados, marca diferencias; un cierre abierto por día/sede; día cerrado bloqueado, reapertura solo admin auditada
  - Modelos `MovimientoCaja`, `CierreDiario`; Migración 006
  - Tests: doble cierre mismo día/sede → 409; movimiento en día cerrado → 422; reapertura no-admin → 403
- **Dependencias**: C-08
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-031
  - `knowledge-base/07_flujos_principales.md` §Flujo 6
  - `knowledge-base/05_reglas_de_negocio.md` §RN-PA-04/05
  - `knowledge-base/04_modelo_de_datos.md` §MovimientoCaja / CierreDiario

---

## FASE 2 — Frontend paciente y recepción

### [C-10] `frontend-agenda-reserva`

- **Estado**: `[x]` archivado (2026-10-12) — deuda explícita task 6.1: regresión viva vs `/docs` NO ejecutada por backend caído (`localhost:8000`); cruce estático routers↔MSW hecho (brechas: `/agenda` y `POST /turnos*` MSW sin JWT, semana por `ventana` ficticia vs `desde/hasta` real, alta staff sin `paciente`/`paciente_id`, `GET /pagar/:token` reenvía `?firma=`).
- **Scope**: SPA React + TS + Vite: agenda operativa y reserva pública
  - `features/agenda`: vista día/semana multiprofesional/multisillón (consume C-04), crear/confirmar/reprogramar/check-in, sobreturno
  - `features/reserva-publica` + `pages/reservar/:slug`: motivo→duración→profesional→slot, DNI+teléfono, gestión con token (consume C-03/C-05)
  - `pages/pagar/:token`: checkout/redirección MP de seña (consume C-08)
  - `shared/api-client` + auth (login, refresh, guarda de roles); todo en español
  - Tests: flujo reserva 3 taps (happy path), agenda render con datos mockeados
- **Dependencias**: C-04, C-05, C-08
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/08_arquitectura_propuesta.md` §Estructura de directorios (frontend)
  - `knowledge-base/07_flujos_principales.md` §Flujo 1, §Flujo 2
  - `knowledge-base/06_funcionalidades.md` §US-001–US-004, §US-030
  - `knowledge-base/02_descripcion_general.md` §Stack (React 18, TS 5)

---

## FASE 3 — Administración y reportes

### [C-11] `roles-reportes-auditoria`

- **Estado**: `[x]` archivado (2026-10-13)
- **Scope**: Gestión de usuarios/roles, auditoría consultable y reportes operativos (US-040, US-041)
  - CRUD `usuarios` + asignación de roles (solo admin); bitácora de acciones sensibles consultable (`GET /api/v1/auditoria?entidad&entidad_id`)
  - Reportes: ocupación por profesional/sillón, ausentismo, ingresos por método + exportación CSV
  - Frontend `pages/admin/*`: usuarios, auditoría, reportes (full admin / propios odontólogo / operativos día recepción)
  - Tests: CRUD roles por no-admin → 403; CSV con formato esperado; auditoría registra crear/cancelar turno, cobro, cierre, edición clínica
- **Dependencias**: C-02, C-09
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-040, §US-041
  - `knowledge-base/03_actores_y_roles.md` §RBAC — Matriz de permisos
  - `knowledge-base/05_reglas_de_negocio.md` §RN-AU-02/03
  - `knowledge-base/04_modelo_de_datos.md` §AuditoriaLog

---

## FASE 4 — Diferenciadores v1.5

> Moat post-MVP: validación OS, lista de espera con seña y bot conversacional. Requieren MVP (FASE 0–1) estable.

### [C-12] `confirmacion-conversacional-whatsapp`

- **Estado**: `[x]` archivado (2026-10-13)
- **Scope**: Bot conversacional 24/7: confirmar/cancelar/reprogramar por WhatsApp sin abrir la web (US-011 + diferenciador)
  - Writeback: "SÍ" confirma solo si el remitente coincide con el teléfono del turno; remitente desconocido → link de gestión sin mutar nada
  - Intents confirmar/cancelar/reprogramar (cancelación valida antelación RN-AG-05; si exige seña pendiente → responde link MP)
  - Reagenda recordatorios 24 h/3 h tras cada cambio (reusa workers C-06)
  - Tests: "SÍ" de remitente válido → confirmado; remitente desconocido no muta; cancelación tardía rechazada por chat
- **Dependencias**: C-06
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-011
  - `knowledge-base/07_flujos_principales.md` §Flujo 2
  - `knowledge-base/05_reglas_de_negocio.md` §RN-NO-03
  - `knowledge-base/11_integraciones_locales.md` §1 WhatsApp Cloud API

---

### [C-13] `validacion-os-preventiva`

- **Estado**: `[x]` archivado (2026-10-13)
- **Scope**: Validación de cobertura de obra social antes de confirmar (US-050, v1.5)
  - Modelos: `ObraSocial` (nomenclador/topos jsonb), `AfiliacionOS`, `ValidacionCobertura`; Migración 007
  - Cruza afiliado + nomenclador + topes → `cubre|parcial|no_cubre` con detalle; si `no_cubre` → ofrece flujo particular con presupuesto antes de confirmar
  - Endpoints `POST /api/v1/obras-sociales/validar` (por turno), CRUD afiliaciones; sin login OS en v1 (actor externo)
  - Riesgo SU-02: spike técnico con 2–3 OS grandes en semana 1 de v1.5; si es inviable, cae a registro manual simple (ver IN-01)
  - Tests: cubre/parcial/no_cubre por fixtures de nomenclador; no_cubre deriva a particular
- **Dependencias**: C-05
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-050
  - `knowledge-base/05_reglas_de_negocio.md` §RN-OS-01/02/03
  - `knowledge-base/04_modelo_de_datos.md` §ObraSocial / AfiliacionOS / ValidacionCobertura
  - `knowledge-base/10_preguntas_abiertas.md` §IN-01

---

### [C-14] `lista-espera-inteligente`

- **Estado**: `[x]` completado (cierre definitivo 2026-10-14 — ver **Verificación técnica** al pie)
- **Scope**: Hueco liberado → oferta automática a la espera, asigna quien paga seña (US-051, v1.5)
  - Modelo `ListaEspera` (ventana desde/hasta, score, estados activa|ofertada|asignada|expirada); Migración 013
  - Worker: detecta hueco por cancelación → scoring (distancia, historial, valor tratamiento) → blast WhatsApp top-N con oferta expirable + link de seña; quien paga primero toma el slot (`asignada`), resto vuelve a `activa`; expiración → re-oferta al siguiente
  - Caja registra seña; agenda notifica a recepción
  - Tests: cancelación dispara oferta; doble pago concurrente → un solo asignado; expiración re-oferta
- **Dependencias**: C-05, C-06, C-08
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-051
  - `knowledge-base/07_flujos_principales.md` §Flujo 5
  - `knowledge-base/05_reglas_de_negocio.md` §RN-PA-01, §RN-AG
  - `knowledge-base/04_modelo_de_datos.md` §ListaEspera
- **Verificación técnica (cierre definitivo 2026-10-14)**:
  - Lógica de producción en `backend/app/models/lista_espera.py` (modelos `ListaEspera`/`OfertaEspera` alineados a la migración 013), `backend/app/routers/lista_espera.py` (RBAC por dependencia antes de validar el body —escritura solo `admin|recepcion` → `403` + `acceso_denegado`—, schema Pydantic estricto, evento `lista_espera_creada` con commit único) y `backend/app/services/lista_espera.py` (scoring normalizado `100*(p_vent*0.5+p_hist*0.3+p_valor*0.2)`, `ofertar_hueco_liberado` top-3 con TTL 30 min y blast 1-a-1 sin PII, `barrer_ofertas_expiradas` con re-oferta al siguiente).
  - Integración: hook de cancelación en autogestión que publica el hueco; webhook MP que acepta `metadata.oferta_espera_id` con reclamo atómico (`FOR UPDATE` + GiST vigente) —oferta vigente → turno `canal=lista_espera` + `pago_acreditado` + `lista_espera_asignada` + `aviso_a_recepcion`; oferta tardía o slot ocupado → `reembolsado` sin turno duplicado—; tipo utility `oferta_lista_espera` + `wa_template_oferta` en settings/mensajes; grilla de recepción que propaga `canal`.
  - Validación: C-14 `21/21` tests en verde (`test_lista_espera_alta|oferta|concurrencia|privacidad`); suite completa backend **305 passed, 0 failed** (PostgreSQL efímera local en 5439, sin Docker; `WHATSAPP_WEBHOOK_SECRET` según `.env.example`). Proyecto listo para la defensa.
- **Retrospectiva de cierre (2026-10-15)**:
  1. **Propose vs. Apply**: validar y ajustar especificaciones antes de codificar (fase Propose) es sumamente económico; cada error de diseño que llegó a la fase Apply (modelo `OfertaEspera` desalineado de la migración 013, RBAC con excepción que mapeaba a `422` en vez de `403`, scoring sin componentes normalizados) costó ciclos completos de diagnóstico + re-ejecución de suite. La lección queda fijada: ningún cambio entra a Apply sin contrato de tests y esquema de datos revisados.
  2. **Especificación como Contrato**: el spec aprobado actuó como contrato estricto —los tests de integración fijaron estados, eventos (`lista_espera_creada|oferta_enviada|oferta_expirada|lista_espera_asignada|pago_reembolsado`), códigos HTTP y reglas de privacidad— e implementar consistió en trasladar esos requerimientos validados sin margen para adivinar (p. ej. fecha ISO y nombre completo en el blast, `canal=lista_espera` visible en grilla, TTL 30 min y top-3 exactos).
  3. **Arquitectura y Test Rig**: la base de reglas de negocio (`knowledge-base/05_reglas_de_negocio.md` y las políticas duras de agentes R0–R8) aportó el mayor valor técnico —cada bug real se resolvió invocando la regla correspondiente (R3 GiST como última defensa, R6 cero PII, R1/R2 capas y migraciones—. Y la estabilización del aislamiento global de tests fue determinante: el fixture de autoreseteo (`TRUNCATE ... CASCADE` de 27 tablas + reseed demo en `tests/conftest.py`) eliminó colisiones `usuario_email_key`/GiST/FK entre tests y corridas matadas, volviendo la suite determinista; el manejo de `deadlock detected` (40P01) como perdedor de carrera cerró la última fuente de flakiness en concurrencia real con threads.
