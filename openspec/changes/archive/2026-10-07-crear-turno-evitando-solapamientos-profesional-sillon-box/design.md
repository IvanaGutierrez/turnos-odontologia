# Design — C-01 `crear-turno-evitando-solapamientos-profesional-sillon-box`

## Context

Ver `proposal.md` (Why/What). Estado actual: repo sin backend (solo `knowledge-base/`, `CHANGES.md`, `openspec/`). Restricciones: stack fijo Python 3.12 + FastAPI 0.110+ + SQLAlchemy 2.0 + PostgreSQL 15+ + Redis 7 + Compose v2 (R8); capas separadas + Alembic (R2); type hints siempre (R1); sin auth hasta C-02; todo seed/ejemplo sintético (R0); nada de DNI/tel/HC en logs, errores o responses (R6).

## Goals / Non-Goals

**Goals:**

- Invariante anti-doble-reserva exigible por la DB bajo concurrencia real (no solo chequeo aplicativo).
- `POST /api/v1/turnos` con contrato de error útil: 409 + slots alternativos calculados sobre la misma prestación/profesional.
- Base fundacional (scaffolding, modelos, migración 001, seed) sobre la que C-02→C-06 construyen sin re-trabajo de schema.

**Non-Goals:**

- Cancelación, reprogramación y máquina completa de estados → C-05 (aquí solo `reservado` al crear; el resto de estados se declaran como enum pero sin transiciones).
- Auth/JWT/RBAC → C-02 (se deja hook: dependencia `get_current_user` opcional documentada como deuda).
- Disponibilidad pública, reserva sin cuenta, rate limiting público → C-03.
- Frontend, WhatsApp, Mercado Pago, OS, ARCA → changes posteriores.

## Decisions

1. **Exclusión con `EXCLUDE USING gist` sobre rangos `tstzrange(inicio, fin)`** (dos constraints: por `profesional_id`, por `sillon_id` donde el turno requiere sillón; turnos `cancelado`/`ausente`/`reprogramado` excluidos del constraint vía predicado `WHERE`). Racional: es la única garantía correcta bajo concurrencia; el chequeo aplicativo previo es optimización UX, la DB manda (RN-AG-01/02, R3). Alternativa descartada: lock aplicativo/Redis — introduce TTL, split-brain y no cubre escrituras fuera del API.
2. **Requiere `btree_gist`** para igualdades sobre UUID/FK dentro del gist. Sin esta extensión el constraint no compila; la migración 001 la crea idempotentemente.
3. **`fin` calculado en la capa de servicio** (`fin = inicio + prestacion.duracion_min`); override solo con `motivo_override` registrado y auditable (RN-AG-03). La API nunca acepta `fin` libre del cliente.
4. **Doble defensa**: validación de solapamiento en el servicio (para devolver 409 rápido con alternativos) + constraint como última línea; la violación del constraint (`ExclusionViolation`) se mapea en el handler global a 409 con el mismo shape (`problema` + `slots_alternativos`), nunca a 500.
5. **Shape 409**: `{ "problema": "slot_ocupado" | "profesional_ocupado" | "sillon_ocupado", "detalle": <mensaje sin PII>, "slots_alternativos": [{inicio, fin}] }`. Los alternativos se calculan con la duración de la prestación sobre el mismo profesional/sillón (ventana de búsqueda configurable, default ±2 h). Sin DNI/teléfonos en el cuerpo (R6).
6. **SQLAlchemy 2.0** (`Mapped[]`/`mapped_column`), engine async + `async_sessionmaker`, sesión por dependencia FastAPI; capas `models/` vs `schemas/` (Pydantic `from_attributes=True`) vs `repositories/` (genérico + por entidad, eager loading anti-N+1) vs `services/` vs `routers/` (R2, standards sqlalchemy-postgres / python-fastapi-development).
7. **Errores**: excepciones custom (`SlotOcupadoError`, `EntidadNoEncontradaError`, `ValidacionARerror`) + handlers globales con respuestas consistentes y OpenAPI completo; versionado `/api/v1`.
8. **Validación AR en schemas Pydantic**: DNI 7–8 dígitos con algoritmo de consistencia básica; teléfono E.164 AR (`+54` + código área + número, con/sin `9` móvil normalizado); 422 ante inválidos. Consentimiento `consentimiento_hc` registrado en `Paciente` (base para RN-CL-01 en C-07).
9. **`token_publico` único** (`secrets.token_urlsafe(32)`, índice único) generado al crear; en C-01 solo se emite y persiste (su uso para autogestión llega en C-05).
10. **Seed sintético idempotente** (script `seed_demo.py`, datos marcados `demo`, teléfonos del rango ficticio `+54 9 11 15-000-0000`, DNIs del rango de ejemplo) — R0.
11. **Sin RLS en C-01** (no hay auth ni multitenancy todavía): deuda explícita hacia C-02, registrada en tasks + Open Questions. Supabase-postgres: pooling configurado desde el día 1; el GiST del exclusion actúa como índice (sin índice adicional redundante sobre rangos).
12. **Testing (plan, se ejecuta en apply)**: pytest, layout `tests/` con `conftest.py` por nivel (unit/integration), markers, fixtures aisladas con self-cleanup, AAA, nombres `test_<unit>_<scenario>_<expected>`, `--cov-fail-under=80`. Concurrencia probada con doble `POST` simultáneo (asyncio/`anyio` + `asyncpg`) contra DB real de test, no SQLite (el constraint gist no existe en SQLite).

## Risks / Trade-offs

- [Riesgo] Rangos adyacentes (`fin == inicio` del siguiente) bloqueados por `&&` si se usa `tstzrange` inclusivo → Mitigación: usar cota superior exclusiva (`'[)'`) para que back-to-back esté permitido.
- [Riesgo] Turnos sin sillón (`sillon_id NULL`): dos NULL no se consideran iguales en gist y el constraint por sillón no aplica → Mitigación: es el comportamiento deseado (RN-AG-02 solo "cuando el turno requiere sillón"); el servicio valida `requiere_sillon` por prestación.
- [Riesgo] Zona horaria: `inicio` naive vs aware rompe comparaciones → Mitigación: `timestamptz` + Pydantic exige offset; Argentina `America/Argentina/Buenos_Aires` por defecto en seed.
- [Riesgo] 409 bajo tormenta de concurrencia sin alternativos útiles → Mitigación: ventana de búsqueda parametrizada (`SLOT_MINUTES_BEFORE/AFTER`) y límite de N slots.
- [Trade-off] Exclusion constraint exige `btree_gist` (extensión) a cambio de corrección total. Aceptado: Postgres 15+ gestionado por nosotros vía Compose/Alembic.
- [Trade-off] Sin auth en C-01 el endpoint nace abierto → Mitigación: deuda explícita; C-02 lo protege sin cambiar el contrato (hook `get_current_user` documentado).

## Migration Plan

1. `apply` ejecuta migración 001 en DB vacía (sin backfill: no hay datos previos).
2. Deploy: `docker compose up --build` (api + postgres + redis + worker; el worker queda cableado mínimo, su lógica llega en C-06).
3. Rollback: `alembic downgrade -1` (revierte tablas + constraints + extensión si fue creada por la migración).
4. Seed solo en entornos demo/dev (`SEED_DEMO=true`), jamás en producción.

## Open Questions

- ¿El consultorio opera multi-sede desde el día 1 (`sede` como entidad) o sede única con campo texto? (No bloquea: se modela `sede` como texto en `Sillon` + deuda hacia C-04; la pregunta abierta de `10_preguntas_abiertas.md` sobre multi-sucursal sigue vigente.)
- Política de sobreturno (`sobreturno=true` + auditoría, RN-AG-06) se implementa en C-04: ¿el constraint debe contemplar excepción para sobreturnos desde ahora? Decisión propuesta: NO en C-01 (el sobreturno se modela en C-04 con bypass explícito auditado); se deja constancia para no sorprender.
