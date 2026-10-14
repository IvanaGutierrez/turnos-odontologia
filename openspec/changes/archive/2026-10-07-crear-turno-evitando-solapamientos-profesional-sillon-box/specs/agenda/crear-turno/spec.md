# Spec Delta — `agenda/crear-turno`

## Purpose

Esta capacidad permite crear un turno odontológico a partir de una prestación/motivo garantizando físicamente que ningún profesional ni sillón/box quede doblemente reservado, incluso bajo peticiones concurrentes, y devolviendo alternativas útiles cuando el slot pedido está ocupado.

## ADDED Requirements

### Requirement: Crear turno válido calcula fin desde la prestación

El sistema SHALL crear un turno en estado `reservado` calculando `fin = inicio + prestacion.duracion_min`, emitiendo un `token_publico` único, y SHALL rechazar `fin` libre enviado por el cliente salvo override con motivo registrado.

#### Scenario: Éxito — crear turno válido calcula fin desde prestación

- **GIVEN** una prestación "Limpieza" con `duracion_min = 45`, un profesional y un sillón libres
- **WHEN** se envía `POST /api/v1/turnos` con `inicio` válido y sin `fin`
- **THEN** responde `201` con `fin = inicio + 45 minutos`, `estado = reservado` y `token_publico` único no vacío

#### Scenario: Fin libre del cliente es ignorado sin motivo registrado

- **GIVEN** una prestación con `duracion_min = 30`
- **WHEN** se envía `POST /api/v1/turnos` con un `fin` arbitrario distinto de `inicio + 30 minutos` y sin motivo de override
- **THEN** el turno se crea con `fin = inicio + 30 minutos` (el `fin` enviado no surte efecto)

### Requirement: Solapamiento por profesional devuelve 409 con alternativos

El sistema SHALL rechazar con `409` todo turno cuyo rango `[inicio, fin)` se superponga con otro turno activo del mismo profesional, y SHALL incluir slots alternativos calculados con la misma duración sobre ese profesional.

#### Scenario: Solapamiento por profesional → 409 + alternativos

- **GIVEN** un turno activo del profesional P de 10:00 a 10:30
- **WHEN** se pide un turno para P de 10:15 a 10:45
- **THEN** responde `409` con `problema = profesional_ocupado` y `slots_alternativos` no vacío con la misma duración

#### Scenario: Turnos adyacentes del mismo profesional están permitidos

- **GIVEN** un turno activo del profesional P de 10:00 a 10:30
- **WHEN** se pide un turno para P de 10:30 a 11:00
- **THEN** responde `201` (el fin exclusivo no colisiona con el inicio siguiente)

### Requirement: Solapamiento por sillón/box devuelve 409 con alternativos

El sistema SHALL rechazar con `409` todo turno que requiera sillón cuyo rango se superponga con otro turno activo del mismo sillón, aunque sea de distinto profesional, y SHALL incluir slots alternativos sobre ese sillón.

#### Scenario: Solapamiento por sillón/box → 409 + alternativos

- **GIVEN** un turno activo en el sillón S de 10:00 a 11:00 (profesional A)
- **WHEN** se pide un turno para el profesional B en S de 10:30 a 11:00
- **THEN** responde `409` con `problema = sillon_ocupado` y `slots_alternativos` no vacío

#### Scenario: Mismo horario en sillones distintos está permitido

- **GIVEN** un turno activo en el sillón S1 de 10:00 a 11:00
- **WHEN** se pide un turno para otro profesional en el sillón S2 de 10:00 a 11:00
- **THEN** responde `201`

### Requirement: Concurrencia — dos POST simultáneos al mismo slot, exactamente uno gana

El sistema SHALL garantizar que ante dos creaciones concurrentes sobre el mismo profesional/sillón y rango superpuesto, exactamente una resulta en `201` y la otra en `409`, sin importar el orden de llegada (la base de datos es la última línea de defensa).

#### Scenario: Doble reserva concurrente por profesional — una gana, otra 409

- **GIVEN** un slot libre para el profesional P de 10:00 a 10:30
- **WHEN** dos `POST /api/v1/turnos` idénticos se ejecutan simultáneamente
- **THEN** exactamente uno responde `201` y el otro `409` con alternativos, y existe un solo turno activo en ese rango

#### Scenario: Doble reserva concurrente por sillón — una gana, otra 409

- **GIVEN** un slot libre en el sillón S de 10:00 a 11:00 para dos profesionales distintos
- **WHEN** dos `POST /api/v1/turnos` sobre S con rangos superpuestos se ejecutan simultáneamente
- **THEN** exactamente uno responde `201` y el otro `409`, y existe un solo turno activo en S en ese rango

### Requirement: Validación de identidad AR rechaza DNI y teléfono inválidos

El sistema SHALL validar el DNI argentino (7–8 dígitos) y el teléfono en formato E.164 AR (`+54…`) en la creación del turno/paciente, y SHALL responder `422` ante valores inválidos sin crear ningún registro.

#### Scenario: DNI argentino inválido → 422

- **GIVEN** un payload con DNI `"12AB"` (formato inválido)
- **WHEN** se envía `POST /api/v1/turnos`
- **THEN** responde `422`, no se crea el turno y el error no incluye el DNI en claro más allá del eco de validación del campo

#### Scenario: Teléfono no E.164 AR → 422

- **GIVEN** un payload con teléfono `"12345"` (sin prefijo país ni formato AR)
- **WHEN** se envía `POST /api/v1/turnos`
- **THEN** responde `422` y no se crea ningún registro

### Requirement: Errores y respuestas nunca exponen datos sensibles

El sistema SHALL sanitizar todas las salidas de modo que ningún log, error `409`/`422` o response incluya DNI, teléfono o historia clínica en claro (R6, Ley 25.326 minimización).

#### Scenario: El 409 por colisión no filtra PII del otro turno

- **GIVEN** un turno existente ocupado por otro paciente
- **WHEN** se provoca una colisión y se inspeccionan la respuesta `409` y los logs
- **THEN** ni el cuerpo del error ni los logs contienen DNI, teléfono o datos clínicos del turno existente

### Requirement: Semilla demo exclusivamente sintética

El sistema SHALL proveer un seed demo idempotente con datos 100 % ficticios (marcados `demo`, teléfonos del rango ficticio, sin personas reales) que deje 1 admin, 1 sede + 1 sillón, 6 prestaciones y 1 profesional + 1 paciente demo (R0).

#### Scenario: Seed demo levanta un consultorio ficticio completo

- **GIVEN** una base de datos vacía migrada a 001
- **WHEN** se ejecuta el seed demo
- **THEN** existen 1 admin, 1 sillón, 6 prestaciones con sus duraciones, 1 profesional y 1 paciente demo, todos marcados `demo` y re-ejecutar el seed no duplica registros
