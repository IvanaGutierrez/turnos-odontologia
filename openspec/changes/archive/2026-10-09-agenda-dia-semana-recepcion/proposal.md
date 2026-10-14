# Proposal — C-04 `agenda-dia-semana-recepcion`

## Why

Recepción hoy no tiene una grilla operativa multiprofesional/multisillón: no puede ver el día/semana, hacer check-in ni resolver sobreturnos y reprogramaciones sin romper la garantía anti-doble-reserva de C-01. Este change le da la operación diaria completa sobre la agenda real de C-03, antes de abrir la autogestión del paciente (C-05).

## What Changes

- `GET /api/v1/agenda?vista=dia|semana&profesional_id&sillon_id&desde&hasta` — grilla agregada multiprofesional y multisillón para operación diaria (día por defecto, semana paginada por ventana).
- Operación de recepción sobre turnos: crear (reusa núcleo C-01, `canal=recepcion`), confirmar (`reservado→confirmado`), reprogramar (conserva `token_publico`, original → `reprogramado` + nuevo turno enlazado), check-in (`confirmado|reservado→presente`, alias físico del `en_sala` actual).
- Sobreturno explícito y auditado: solo `recepcion`/`admin` con `sobreturno=true` + `motivo_sobreturno` obligatorio; bypass a nivel aplicación que convive con el GiST sin debilitarlo (ver design decisión 1).
- CRUD config agenda: `profesionales`, `sillones`, `prestaciones`, `horarios/bloqueos` — `admin` CRUD, resto R según matriz RBAC (odontólogo su propia agenda, recepción lectura).
- Migración 004 si hace falta: columna `sobreturno` + `motivo_sobreturno` + enlace `reprogramado_de_id`, estado `presente` (ver design decisión 2), índices para grilla día/semana.
- Plan TDD (los tests se escriben en `apply`, aquí solo se especifican): check-in, sobreturno con/sin permiso, reprogramación conserva token, CRUD config solo admin, grilla sin PII excedente.

## Capabilities

### New Capabilities

- `agenda/agenda-recepcion`: grilla día/semana multiprofesional-multisillón + crear/confirmar/reprogramar/check-in/sobreturno auditado desde recepción, con visibilidad por rol y sin PII excedente.
- `agenda/configuracion-agenda`: CRUD admin de profesionales, sillones, prestaciones y horarios/bloqueos con lectura según matriz RBAC.

### Modified Capabilities

_(ninguna — `agenda/crear-turno`, `agenda/disponibilidad`, `agenda/reserva-publica`, `auth/autorizacion-rbac` y `auditoria/registro-acciones` no cambian sus REQUIREMENTS: este change los reutiliza; el sobreturno es bypass explícito auditado a nivel aplicación, no un debilitamiento del GiST ni de los contratos 201/409/422 existentes)_

## Impact

- Nuevo: router `agenda` protegido (`require_role("turnos")` / `"configuracion_agenda"`), servicios `agenda_receptiva` (grilla + transiciones + reprogramación + sobreturno), schemas de grilla y config, migración 004, settings (`AGENDA_DIA_MAX`, `AGENDA_SEMANA_MAX_DIAS`, ventana por defecto).
- Reusa sin modificar: exclusión GiST C-01 (última línea), shape `409` + alternativos, validaciones AR, sanitización R6, auditoría C-02 (`turno_confirmado`, `turno_presente`, `sobreturno_creado`, `turno_reprogramado`, `acceso_denegado`), rate limit como patrón (no se exige rate limit nuevo en endpoints protegidos).
- No-objetivos explícitos: cancelación con antelación y autogestión con token (C-05), recordatorios WhatsApp (C-06), ficha/odontograma (C-07), frontend (C-10). La cancelación NO se incluye en este change.
