# agenda/configuracion-agenda Specification

## Purpose
Permite al administrador centralizar la configuración de la agenda (profesionales, sillones, prestaciones, horarios y bloqueos) con control de acceso estricto, para que recepción y odontólogos operen sobre un catálogo consistente sin poder alterarlo.

## Requirements

### Requirement: CRUD de configuración solo admin, resto lectura según matriz

El sistema SHALL exponer CRUD de `profesionales`, `sillones`, `prestaciones` y `horarios/bloqueos` solo para el rol `admin` (recurso `configuracion_agenda`), y SHALL permitir lectura a `recepcion` (todo) y a `odontologo` (su propia agenda), respondiendo `403` + `acceso_denegado` auditado ante cualquier escritura no-admin.

#### Scenario: CRUD config solo admin (recepción → 403)

- **WHEN** un usuario `recepcion` con access válido intenta `POST /api/v1/profesionales` (o PUT/DELETE sobre sillones, prestaciones, horarios/bloqueos)
- **THEN** responde `403` con detalle genérico, no se crea ni muta ningún registro y se registra `acceso_denegado` con usuario, recurso y hora

#### Scenario: Admin crea prestación y queda visible para recepción

- **WHEN** `admin` crea una prestación `{"nombre": "Control sintético", "duracion_min": 30}` (datos ficticios)
- **THEN** responde `201`, `GET /api/v1/prestaciones` como `recepcion` la incluye, y la auditoría registra el alta sin PII

#### Scenario: Odontólogo lee su agenda pero no configura

- **WHEN** un `odontologo` pide su propia agenda (`GET /api/v1/agenda?vista=dia&profesional_id=<propio>`) y luego intenta `DELETE /api/v1/sillones/<id>`
- **THEN** la primera responde `200` y la segunda responde `403` con evento auditado

### Requirement: Validación de catálogo y horarios

El sistema SHALL validar que toda prestación tenga `duracion_min > 0`, que todo horario cumpla `hora_inicio < hora_fin` con `dia_semana` 0–6, que todo bloqueo cumpla `desde < hasta`, y SHALL responder `422` genérico ante valores inválidos sin crear registros.

#### Scenario: Prestación con duración inválida → 422

- **WHEN** `admin` envía una prestación con `duracion_min = 0`
- **THEN** responde `422` y no se crea la prestación

#### Scenario: Bloqueo con ventana invertida → 422

- **WHEN** `admin` crea un bloqueo con `desde >= hasta`
- **THEN** responde `422` y no se crea el bloqueo
