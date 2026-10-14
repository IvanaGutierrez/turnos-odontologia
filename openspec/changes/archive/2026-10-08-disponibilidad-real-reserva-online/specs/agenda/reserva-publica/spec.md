# Spec Delta — `agenda/reserva-publica`

## Purpose

Permite que un paciente sin cuenta reserve un slot real con DNI y teléfono, con protección anti-spam y anti-doble-reserva, recibiendo un token público para gestionar su turno y el link de pago cuando corresponda.

## ADDED Requirements

### Requirement: Reserva pública crea turno reservado con token público

El sistema SHALL exponer `POST /api/v1/turnos/publicos` sin JWT, que valida DNI AR + teléfono E.164 AR, calcula `fin = inicio + prestacion.duracion_min` (ignorando `fin` libre del cliente), crea el turno en estado `reservado` con `canal = online`, emite un `token_publico` único y SHALL registrar la acción en auditoría sin PII (RN-AU-03, R6).

#### Scenario: Reserva online válida → 201 con token público

- **WHEN** se envía `POST /api/v1/turnos/publicos` con prestación, profesional, `inicio` correspondiente a un slot libre ofrecido por disponibilidad, DNI y teléfono AR válidos de un paciente ya verificado, y clave de idempotencia nueva
- **THEN** responde `201` con `estado = reservado`, `fin = inicio + duracion_min`, `canal = online` y `token_publico` único no vacío

#### Scenario: DNI o teléfono inválidos → 422 sin crear nada

- **WHEN** se envía la reserva con DNI o teléfono AR inválidos (datos sintéticos de prueba)
- **THEN** responde `422` con mensaje genérico y no se crea ningún turno ni paciente

### Requirement: Primera reserva exige verificación por código sin enumerar

El sistema SHALL exigir un código de verificación vigente (emitido al teléfono declarado) cuando el par DNI + teléfono no tenga una verificación previa exitosa, SHALL limitar intentos y bloquear temporalmente ante fallos reiterados, y SHALL responder con mensajes idénticos exista o no el par, sin revelar si un DNI o teléfono ya reservó antes (RN-PU-01, R6).

#### Scenario: Primera reserva sin código o con código inválido → 422/429 sin crear turno

- **WHEN** se envía la reserva para un par DNI + teléfono sin verificación previa, sin código o con código incorrecto/expirado
- **THEN** responde `422` (código requerido o inválido) o `429` (bloqueo temporal por intentos) con mensaje genérico idéntico exista o no el par, y no se crea ningún turno

#### Scenario: Reserva posterior del par verificado no exige código nuevo

- **WHEN** se envía la reserva para un par DNI + teléfono con verificación previa exitosa vigente y slot libre
- **THEN** responde `201` sin requerir código

### Requirement: Doble submit con la misma clave de idempotencia crea un solo turno

El sistema SHALL aceptar un token de idempotencia por reserva (`Idempotency-Key`) y SHALL garantizar que dos `POST` con la misma clave y mismo payload devuelven el mismo turno sin crear duplicados, incluso bajo envío concurrente.

#### Scenario: Doble submit misma idempotency-key → un solo turno

- **WHEN** se envían dos `POST /api/v1/turnos/publicos` idénticos con la misma `Idempotency-Key` de forma simultánea
- **THEN** exactamente un turno `reservado` existe para esa clave, ambas respuestas son `201` (o la segunda `200` con el mismo recurso) con idéntico `token_publico`, y no hay doble reserva

### Requirement: Rate limit por IP y por teléfono en reserva pública

El sistema SHALL limitar `POST /api/v1/turnos/publicos` por IP y por teléfono declarado, respondiendo `429` con indicación de reintento al excederse, sin procesar la reserva (RN-PU-03).

#### Scenario: Rate limit por IP/teléfono → 429

- **WHEN** se supera el tope configurable de reservas por minuto desde la misma IP o con el mismo teléfono
- **THEN** responde `429` con indicación de reintento y no se crea ningún turno

### Requirement: Prestación con seña devuelve link de pago sin cobrar aquí

El sistema SHALL, cuando `prestacion.requiere_sena` sea verdadero, incluir en la respuesta `201` un link de pago (`url_pago`) para la seña y mantener el turno en `reservado` pendiente de seña; el cobro y la confirmación al acreditarse pertenecen a C-08 y NO se implementan aquí (RN-PA-01/02 solo en lo que toca a este change: no confirmar sin pago).

#### Scenario: Prestación con seña devuelve link de pago y queda reservado

- **WHEN** se reserva con éxito una prestación con `requiere_sena = true`
- **THEN** responde `201` con `estado = reservado` y `url_pago` no vacía, y el turno NO pasa a `confirmado` en este change

### Requirement: Carrera entre GET y POST → 409 con alternativos del mismo shape C-01

El sistema SHALL, cuando el slot pedido se ocupó entre la consulta de disponibilidad y la reserva (la exclusión DB manda, R3), rechazar con `409` y el mismo shape de C-01 (`problema` + `slots_alternativos` de igual duración, sin PII), sin crear el turno.

#### Scenario: 409 con alternativos si el slot se ocupó entre GET y POST

- **WHEN** se reserva un slot que otro turno ocupó después de haber sido listado como libre
- **THEN** responde `409` con `problema = profesional_ocupado | sillon_ocupado`, `slots_alternativos` no vacío de igual duración y sin DNI/teléfonos en cuerpo ni logs
