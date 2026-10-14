# Proposal — C-01 `crear-turno-evitando-solapamientos-profesional-sillon-box`

## Why

La doble reserva (mismo profesional o mismo sillón/box en horarios superpuestos) es el fallo físico más grave de una agenda odontológica: dos pacientes citados al mismo recurso destruyen la operación del consultorio y la confianza. Este primer change establece el núcleo de agenda con garantía a nivel de base de datos antes de construir todo lo demás (auth, reserva online, recordatorios).

## What Changes

- Scaffolding mínimo foundation (plegado aquí por mandato, no como change separado): `backend/app/main.py` (FastAPI, routers `/api/v1`), `core/` (settings, db, logger, exceptions), `docker-compose.yml` (api + postgres + redis + worker), `.env.example`, Alembic inicializado.
- Modelos: `Usuario`, `Paciente` (dni único, teléfono E.164 AR, `consentimiento_hc`), `Profesional`, `Sillon`, `Prestacion` (motivo + `duracion_min` + `requiere_sena`), `Turno` (inicio, fin, estado, canal, `token_publico` único).
- Migración 001: tablas de agenda + `EXCLUDE USING gist` anti-solapamiento por (profesional, rango) y por (sillón, rango) donde aplique (R3: el constraint es la última línea de defensa).
- `POST /api/v1/turnos`: crea el turno con `fin = inicio + prestacion.duracion` (override solo con motivo registrado); ante colisión concurrente la DB manda → `409` + slots alternativos.
- Seed demo 100 % sintético (R0): 1 admin, sede "Consultorio" + 1 sillón demo, 6 prestaciones (consulta 30', limpieza 45', endodoncia 60', extracción 45', ortodoncia control 30', urgencia 20'), profesional y paciente `demo`.
- Plan TDD (los tests se escriben en `apply`, aquí solo se especifican): doble reserva concurrente por profesional → 409; por sillón → 409; `fin` calculado; DNI/teléfono AR inválidos rechazados.

## Capabilities

### New Capabilities

- `agenda/crear-turno`: crear un turno a partir de prestación/motivo con duración calculada, invariante de no-solapamiento por profesional y por sillón/box garantizada en DB, error 409 con slots alternativos ante colisión (incluida concurrencia), validaciones AR de identidad y contrato de error sanitizado.

### Modified Capabilities

_(ninguna — primer change del roadmap, sin dependencias)_

## Impact

- Nuevo: backend FastAPI (`/api/v1`), PostgreSQL 15+ (extensión `btree_gist`), Redis 7, Docker Compose (api + postgres + redis + worker). Sin frontend en este change (C-10).
- Sin auth todavía: JWT/RBAC llegan en C-02; el endpoint se diseña sin asumir autenticación, con hook explícito de protección futura (deuda documentada en `design.md`).
- Todo cambio de schema vía migración Alembic (R2); secretos solo por env + `.env.example` (R7); stack fijo intacto (R8).
- No-objetivos explícitos: cancelación/reprogramación (C-05), disponibilidad pública y reserva online (C-03), señas/MP (C-08), WhatsApp (C-06).
