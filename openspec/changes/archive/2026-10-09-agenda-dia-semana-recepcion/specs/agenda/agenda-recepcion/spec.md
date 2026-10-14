# Spec Delta — `agenda/agenda-recepcion`

## Purpose

Permite a recepción operar la agenda diaria del consultorio sobre una grilla multiprofesional y multisillón: ver el día/semana, crear, confirmar, reprogramar y registrar check-in y sobreturnos auditados, sin debilitar la garantía anti-doble-reserva y sin exponer datos personales más allá de lo necesario para operar.

## ADDED Requirements

### Requirement: Grilla día por profesional para operación de recepción

El sistema SHALL exponer `GET /api/v1/agenda?vista=dia` que devuelve los turnos activos del día filtrados por `profesional_id` y/o `sillon_id`, ordenados cronológicamente, exigiendo JWT con permiso `turnos` y respondiendo `401` sin token y `403` + auditoría sin permiso.

#### Scenario: Grilla día por profesional

- **WHEN** recepción autenticada pide `GET /api/v1/agenda?vista=dia&profesional_id=<P>&desde=<2026-11-03T00:00-03:00>` existiendo dos turnos activos de P ese día y uno de otro profesional
- **THEN** responde `200` con exactamente los dos turnos de P ordenados por `inicio`, cada item con `{id, inicio, fin, estado, profesional_id, sillon_id, prestacion_id, sobreturno}` más nombre de paciente visible según rol, y sin DNI, teléfono ni historia clínica en claro

#### Scenario: Grilla exige auth — sin token 401, sin permiso 403 + log

- **WHEN** se pide `GET /api/v1/agenda?vista=dia` sin access token, y luego con un rol sin permiso `turnos`
- **THEN** la primera responde `401` sin ejecutar nada y la segunda responde `403` con detalle genérico y registra `acceso_denegado` en `AuditoriaLog` con usuario, recurso y hora

### Requirement: Grilla semana multisillón paginada por ventana

El sistema SHALL exponer `GET /api/v1/agenda?vista=semana` que devuelve los turnos activos en la ventana `[desde, hasta]` (máximo configurable `AGENDA_SEMANA_MAX_DIAS`, default 7) agregados por profesional y sillón, con paginación por ventana y sin consultas N+1 (una query por rango + índices).

#### Scenario: Grilla semana multisillón

- **WHEN** recepción pide `GET /api/v1/agenda?vista=semana&desde=<2026-11-03T00:00-03:00>&hasta=<2026-11-10T00:00-03:00>` existiendo turnos activos en dos sillones y tres profesionales esa semana
- **THEN** responde `200` con todos los turnos activos de la ventana, cada uno identificando `profesional_id` y `sillon_id`, ordenados por `inicio`, y el `EXPLAIN` de la query no usa seq-scan sobre turnos con fixtures de volumen día/semana

#### Scenario: Ventana excesiva rechazada sin goteo

- **WHEN** se pide `vista=semana` con `hasta - desde` mayor que `AGENDA_SEMANA_MAX_DIAS` o con `desde >= hasta`
- **THEN** responde `422` con mensaje genérico, sin revelar turnos, horarios ni bloqueos

### Requirement: Crear y confirmar turnos desde recepción

El sistema SHALL permitir a roles con permiso `turnos` crear turnos (`canal=recepcion`, mismo núcleo y shape `201`/`409`/`422` de `agenda/crear-turno`) y confirmar turnos (`reservado→confirmado`), registrando `turno_creado` / `turno_confirmado` en auditoría solo con IDs y horarios (R6).

#### Scenario: Recepción crea turno con canal recepcion

- **WHEN** recepción envía `POST /api/v1/turnos` con un slot libre válido
- **THEN** responde `201` con `estado=reservado`, `token_publico` único no vacío, y `AuditoriaLog` contiene `turno_creado` sin DNI ni teléfono en el `diff`

#### Scenario: Recepción confirma turno reservado

- **WHEN** recepción envía `POST /api/v1/turnos/<id>/confirmar` sobre un turno en `reservado`
- **THEN** responde `200` con `estado=confirmado` y registra `turno_confirmado` con usuario, turno y hora

#### Scenario: Confirmar estado no confirmable rechazado

- **WHEN** se intenta confirmar un turno en `atendido`, `cancelado`, `ausente` o `reprogramado`
- **THEN** responde `422` con mensaje genérico y el estado no cambia

### Requirement: Check-in marca presente y queda auditado

El sistema SHALL exponer la transición de check-in a `presente` (única transición válida desde `reservado` o `confirmado`) solo para roles con permiso `turnos`, y SHALL registrar `turno_presente` en auditoría con usuario y hora.

#### Scenario: Check-in marca presente + audita

- **WHEN** recepción envía `POST /api/v1/turnos/<id>/check-in` sobre un turno `confirmado`
- **THEN** responde `200` con `estado=presente` y `AuditoriaLog` muestra `turno_presente` con el usuario responsable, sin PII en el `diff`

#### Scenario: Check-in desde estado inválido rechazado

- **WHEN** se hace check-in sobre un turno `atendido`, `cancelado`, `ausente` o `reprogramado`
- **THEN** responde `422` y el estado no cambia

### Requirement: Sobreturno solo recepcion/admin con motivo y auditoría obligatoria

El sistema SHALL permitir crear un turno con `sobreturno=true` únicamente a roles `recepcion` y `admin`, exigiendo `motivo_sobreturno` no vacío, marcando la fila `sobreturno=true`, y SHALL registrar `sobreturno_creado` con usuario, turno, motivo y hora; cualquier otro rol recibe `403` + `acceso_denegado` auditado.

#### Scenario: Sobreturno con permiso crea + audita con motivo

- **WHEN** recepción envía `POST /api/v1/turnos/sobreturno` con slot ya ocupado, `sobreturno=true` y `motivo="urgencia dolor agudo"` (datos sintéticos)
- **THEN** responde `201` con `sobreturno=true`, el constraint GiST sigue intacto para turnos normales, y `AuditoriaLog` contiene `sobreturno_creado` con usuario, motivo y hora, sin DNI ni teléfono en el `diff`

#### Scenario: Sobreturno sin permiso → 403 + log

- **WHEN** un usuario con rol `odontologo` (sin permiso de sobreturno según matriz de este change) envía `POST /api/v1/turnos/sobreturno` con access válido
- **THEN** responde `403` con detalle genérico, no se crea ningún turno y se registra `acceso_denegado` con usuario, recurso y hora

#### Scenario: Sobreturno sin motivo rechazado

- **WHEN** recepción envía sobreturno sin `motivo_sobreturno` o con motivo vacío
- **THEN** responde `422` y no se crea ningún turno

### Requirement: Reprogramación conserva token y traza el original

El sistema SHALL exponer `POST /api/v1/turnos/<id>/reprogramar` que, ante un slot destino libre, marca el turno original como `reprogramado` (liberando el recurso por el predicado de estados inactivos) y crea un turno nuevo con el mismo `token_publico`, enlazado vía `reprogramado_de_id`, registrando `turno_reprogramado`; si el destino colisiona responde `409` + alternativos sin mutar nada (la cancelación NO pertenece a este change — es C-05).

#### Scenario: Reprogramación conserva token_publico y original → reprogramado

- **WHEN** recepción reprograma un turno `reservado|confirmado` a un slot libre de igual prestación enviando `POST /api/v1/turnos/<id>/reprogramar {nuevo_inicio}`
- **THEN** responde `200|201` con el turno nuevo con idéntico `token_publico` que el original, el original queda en `reprogramado` con `reprogramado_de_id` enlazado, y la auditoría muestra `turno_reprogramado` sin PII

#### Scenario: Reprogramación a slot ocupado → 409 sin mutar

- **WHEN** se reprograma hacia un rango superpuesto con otro turno activo del mismo profesional o sillón
- **THEN** responde `409` con `problema` + `slots_alternativos` (mismo shape que `agenda/crear-turno`), el turno original conserva su estado y no se crea ningún turno nuevo

### Requirement: Visibilidad por rol y minimización en la grilla (R6)

El sistema SHALL devolver en la grilla solo los campos necesarios para operar según el rol (`admin`/`recepcion`: nombre de paciente para operar el día; `odontologo`: su propia agenda con igual minimización), y SHALL jamás incluir DNI, teléfono, historia clínica, hashes ni tokens en cuerpos `200`, errores `4xx` ni logs (Ley 25.326 minimización).

#### Scenario: Grilla no filtra PII excedente

- **WHEN** se inspeccionan el cuerpo `200` de `GET /api/v1/agenda` y los logs ante una grilla con turnos de varios pacientes
- **THEN** ningún cuerpo ni log contiene DNI, teléfono, historia clínica, hashes ni tokens; el `diff` de auditoría de grilla (si lo hay) lleva solo IDs, horarios y estados
