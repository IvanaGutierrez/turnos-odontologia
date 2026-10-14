# Turnos Odontología (AR) — Instrucciones para Agentes

> Este archivo (y su copia `CLAUDE.md`) es lo PRIMERO que todo agente lee al entrar al repo.
> Generado a partir de `knowledge-base/` y `CHANGES.md`. No editar a mano sin re-sincronizar ambos archivos.

Sistema de turnos odontológicos para Argentina (FastAPI + React) que combina agenda online sin cuenta, WhatsApp nativo, odontograma + presupuestos y señas por Mercado Pago; deja OS preventiva y lista de espera con seña como moat v1.5 y ARCA nativa para v2 — el hueco que ningún competidor cubre hoy.

---

## Stack Tecnológico

Stack fijo (restricción no negociable — `discovery/discovery.md` §9, state `discovery.restricciones`):

| Capa | Tecnologías | Versión mínima |
|------|-------------|----------------|
| Backend | Python + FastAPI + SQLAlchemy | Python 3.12, FastAPI 0.110+ |
| Auth | JWT (access + refresh) | — |
| Base de datos | PostgreSQL | 15+ |
| Caché / colas | Redis (+ workers para recordatorios, webhooks, blasts) | 7+ |
| Frontend | React + TypeScript + Vite | React 18, TS 5 |
| Deploy | Docker / Docker Compose en VPS argentino | Compose v2 |
| Idioma | Español (todo el producto) | — |

Detalle completo: [knowledge-base/02_descripcion_general.md](knowledge-base/02_descripcion_general.md)

---

## Base de Conocimiento

La fuente de verdad del dominio vive en `knowledge-base/`. **Leé el archivo relevante ANTES de implementar.**

| Archivo | Cuándo leerlo |
|---------|---------------|
| [README.md](knowledge-base/README.md) | Índice + resumen ejecutivo + quick start |
| [01_vision_y_objetivos.md](knowledge-base/01_vision_y_objetivos.md) | Entender propósito y alcance |
| [02_descripcion_general.md](knowledge-base/02_descripcion_general.md) | Stack fijo, arquitectura, integraciones, API REST |
| [03_actores_y_roles.md](knowledge-base/03_actores_y_roles.md) | Auth, RBAC, permisos |
| [04_modelo_de_datos.md](knowledge-base/04_modelo_de_datos.md) | Entidades, ERD, migraciones |
| [05_reglas_de_negocio.md](knowledge-base/05_reglas_de_negocio.md) | Reglas codificadas (RN-XX) |
| [06_funcionalidades.md](knowledge-base/06_funcionalidades.md) | Historias de usuario por épica |
| [07_flujos_principales.md](knowledge-base/07_flujos_principales.md) | Flujos E2E |
| [08_arquitectura_propuesta.md](knowledge-base/08_arquitectura_propuesta.md) | Patrones, estructura, env vars |
| [09_decisiones_y_supuestos.md](knowledge-base/09_decisiones_y_supuestos.md) | Decisiones DD + supuestos SU |
| [10_preguntas_abiertas.md](knowledge-base/10_preguntas_abiertas.md) | ⚠️ Inconsistencias a resolver ANTES de codear |
| [11_integraciones_locales.md](knowledge-base/11_integraciones_locales.md) | WhatsApp + Mercado Pago + ARCA + GCal |

> ⚠️ Resolver las preguntas de prioridad **Alta** de `10_preguntas_abiertas.md` antes de arrancar el primer change (OS en MVP vs v1.5, reserva sin cuenta vs login, multi-sucursal día 1, modelo de precio, validación del hábito online vs WhatsApp manual con pilotos).

---

## Skills Disponibles

| Agente | Rol | Skills que carga |
|--------|-----|------------------|
| **Backend Core** | FastAPI / SQLAlchemy / Postgres / TDD | `python-fastapi-development`, `sqlalchemy-postgres`, `supabase-postgres-best-practices`, `python-testing-patterns` |
| **Frontend** | React / TS / Vite / E2E | `vercel-react-best-practices`, `frontend-design`, `web-design-guidelines`, `webapp-testing`, `playwright-cli` |
| **Transversal** | Review multi-rol | `code-review` |

Cargá la skill correspondiente al contexto ANTES de escribir código.

> Los compact rules de cada skill los resuelve el orquestador desde `.atl/skill-registry.md` (generado por `skill-registry`; no versionado — no está en el repo). Esta tabla solo mapea skill→rol.

---

## Roadmap de Changes

El plan de implementación completo está en [CHANGES.md](CHANGES.md). Resumen:

- **Total**: 14 changes en 5 fases (FASE 0 agenda crítica + FASE 1 clínica y cobros + FASE 2 frontend + FASE 3 administración y reportes + FASE 4 diferenciadores v1.5).
- **Camino crítico** (6): `C-01 → C-02 → C-03 → C-04 → C-05 → C-06`.
- **Primer change**: `C-01` (crear-turno-anti-solapamiento — `crear-turno-evitando-solapamientos-profesional-sillon-box`: núcleo de agenda con garantía física anti-doble-reserva + scaffolding foundation plegado).

**Antes de cualquier `/opsx:propose`**: leé [CHANGES.md](CHANGES.md), identificá las dependencias del change y los archivos de "Leer antes".

---

## Reglas Duras

> Global `~/.claude/CLAUDE.md` NO existe (verificado 2026-10-01): no hay herencia. Este archivo es la única fuente — incluye la base universal compacta + las reglas específicas del proyecto. Son contrato; romperlas es un defecto.

**Base universal (aplica a todo change):**

- Gobernanza por niveles (CRITICO / ALTO / MEDIO): a mayor nivel, más evidencia y más freno antes de avanzar.
- Memoria engram: buscar contexto antes de decidir, guardar decisiones/bugfixes/descubrimientos al cerrar trabajo, resumir la sesión al terminar.
- TDD estricto: test en rojo antes de implementar, verde mínimo para pasar, refactor solo con suite en verde.
- NUNCA buildear, commitear o pushear sin pedido explícito del usuario → proponer el cambio y esperar aprobación.
- Commits en formato conventional commits, sin co-autoría IA.

**Específicas del proyecto (confirmadas por el usuario, formato NUNCA X → hacer Y):**

- R0: NUNCA almacenar ni procesar datos reales de pacientes en el repositorio ni en las pruebas → usar datos sintéticos/ficticios siempre.
- R1: NUNCA código Python sin type hints → tipar funciones públicas, modelos y schemas.
- R2: NUNCA mezclar capas (models/ vs schemas/ vs repositories/ vs services/) ni editar la DB a mano → todo cambio de schema vía migración Alembic.
- R3: NUNCA crear un turno sin chequeo de solapamiento por profesional y sillón → el constraint de exclusión es la última línea de defensa.
- R4: NUNCA usar `any` en TypeScript → tipado estricto; componentes en PascalCase.
- R5: NUNCA dar por hecho un flujo de negocio sin test en verde (solapamiento, cancelación mínima, seña) → pytest en backend, E2E en frontend.
- R6: NUNCA loguear ni exponer DNI, teléfonos o historia clínica en logs, errores o responses → sanitizar toda salida.
- R7: NUNCA hardcodear secretos (JWT, tokens MP/WhatsApp) ni commitear `.env` → variables de entorno + `.env.example`.
- R8: NUNCA sustituir el stack fijo (FastAPI/PostgreSQL/React) sin aprobación explícita → proponer y esperar.

---

## Flujo de Trabajo

```
1. Leer la KB relevante (knowledge-base/)        → entender el dominio
2. Identificar el change en CHANGES.md           → respetar dependencias
3. /opsx:propose C-NN-nombre                     → proposal + design + specs + tasks
4. Implementar las tasks (cargando skills)       → respetando las reglas duras
5. /opsx:archive C-NN-nombre + marcar [x]        → cerrar el change
```

Aplicar TODAS las reglas duras en cada paso. Ante conflicto entre la KB y este archivo, las reglas duras prevalecen.
