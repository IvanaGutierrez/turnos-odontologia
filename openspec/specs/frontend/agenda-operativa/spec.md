# frontend/agenda-operativa Specification

## Purpose
Grilla operativa de recepción sobre la agenda multiprofesional y multisillón: ver el día y la semana, y ejecutar crear, confirmar, reprogramar, check-in y sobreturno auditado contra los contratos C-04, mostrando a cada rol solo los datos que necesita para operar.

## Requirements

### Requirement: Vista día multiprofesional y multisillón

La UI SHALL renderizar la vista día a partir de `GET /api/v1/agenda?vista=dia` (filtros `profesional_id` y/o `sillon_id`), mostrando los turnos ordenados cronológicamente con profesional y sillón identificados, y SHALL reintentar con retroceso ante error de red sin duplicar consultas en paralelo para la misma vista.

#### Scenario: Agenda día renderiza grilla multiprofesional con datos mockeados

- **WHEN** recepción autenticada abre la vista día con fixtures MSW de tres profesionales y dos sillones con turnos activos solapados en horario pero de distinto profesional/sillón
- **THEN** la grilla muestra cada turno en su columna de profesional/sillón ordenado por hora de inicio, sin turnos fantasma ni duplicados, y cada celda expone solo nombre operativo del paciente más horario y estado

#### Scenario: Vista día sin turnos invita a actuar

- **WHEN** la vista día responde `200` con lista vacía para los filtros elegidos
- **THEN** la UI muestra un estado vacío en español que invita a crear un turno o cambiar de filtro, sin mensajes técnicos ni códigos de error

### Requirement: Vista semana por ventana con paginación

La UI SHALL renderizar la vista semana a partir de `GET /api/v1/agenda?vista=semana&desde&hasta` (ventana máxima la que rechaza el backend con `422`), paginando por ventana y SHALL mostrar el error de negocio del backend (`422`/`401`/`403`) traducido a español operativo sin exponer PII ni detalles técnicos.

#### Scenario: Semana multisillón pagina por ventana

- **WHEN** recepción avanza a la semana siguiente con turnos activos en dos sillones y tres profesionales
- **THEN** la UI pide la ventana nueva una sola vez, renderiza todos los turnos con su profesional y sillón, y no repite la consulta de la ventana anterior

#### Scenario: Ventana excesiva muestra aviso accionable

- **WHEN** el backend responde `422` por ventana mayor que el máximo permitido
- **THEN** la UI muestra un aviso en español que indica el rango máximo y ofrece volver a la semana actual, sin revelar turnos ni horarios

### Requirement: Crear, confirmar, reprogramar y check-in desde recepción

La UI SHALL exponer crear (`POST /api/v1/turnos`, `canal=recepcion`), confirmar (`reservado→confirmado`), reprogramar (conserva `token_publico`, original → `reprogramado`) y check-in (`reservado|confirmado→presente`) solo a sesión con permiso `turnos`, y SHALL ante `409` por slot ocupado mostrar los `slots_alternativos` del backend sin mutar nada localmente hasta la confirmación del servidor.

#### Scenario: Recepción crea y confirma un turno

- **WHEN** recepción con rol `recepcion` crea un turno en un slot libre con datos sintéticos y luego lo confirma
- **THEN** la UI envía `canal=recepcion`, refleja `reservado` tras el `201`, refleja `confirmado` tras la confirmación, y ambas acciones quedan visibles en la grilla sin recarga manual

#### Scenario: Recepción hace check-in de un turno confirmado

- **WHEN** recepción registra el check-in de un turno `confirmado`
- **THEN** la UI refleja `presente` tras el `200` y el turno permanece visible en el día con su nuevo estado

#### Scenario: Slot tomado en concurrente ofrece alternativas

- **WHEN** dos recepcionistas crean sobre el mismo slot y el segundo recibe `409` con `slots_alternativos`
- **THEN** la UI muestra el aviso de slot ocupado en español junto con los slots alternativos ofrecidos, sin crear ningún turno local y sin perder los datos ya ingresados del formulario

### Requirement: Sobreturno solo recepcion/admin con motivo registrado

La UI SHALL exponer la creación con `sobreturno=true` únicamente a sesión con rol `recepcion` o `admin`, exigiendo `motivo_sobreturno` no vacío antes de enviar, y SHALL ocultar el control de sobreturno a `odontologo`; ante `403` SHALL mostrar denegación genérica en español.

#### Scenario: Sobreturno con motivo crea y marca la fila

- **WHEN** recepción crea un sobreturno sobre un horario ocupado con motivo "urgencia dolor agudo" (dato sintético)
- **THEN** la UI envía `sobreturno=true` con el motivo, refleja el turno marcado como sobreturno tras el `201`, y el motivo queda registrado sin exponer DNI ni teléfono en ninguna vista o mensaje

#### Scenario: Odontólogo no ve el control de sobreturno

- **WHEN** una sesión con rol `odontologo` abre la agenda operativa
- **THEN** el control de sobreturno no existe en el DOM ni en la navegación, y cualquier respuesta `403` del backend se muestra como aviso genérico sin detalles técnicos

### Requirement: Visibilidad por rol y minimización en la grilla

La UI SHALL mostrar en la grilla solo los campos necesarios para operar según el rol (`admin`/`recepcion`: nombre operativo para gestionar el día; `odontologo`: solo su propia agenda con igual minimización), y SHALL jamás renderizar, registrar en consola ni incluir en reportes de error DNI, teléfono, historia clínica, hashes ni tokens.

#### Scenario: DNI y teléfono jamás visibles donde el rol no los ve

- **WHEN** se inspeccionan la vista día y semana renderizadas con turnos de varios pacientes, la consola del navegador y los mensajes de error ante un fallo de red
- **THEN** ninguna superficie contiene DNI, teléfono, historia clínica, hashes ni tokens; la auditoría de esta verificación queda registrada en el test E2E/unit correspondiente con fixtures sintéticas
