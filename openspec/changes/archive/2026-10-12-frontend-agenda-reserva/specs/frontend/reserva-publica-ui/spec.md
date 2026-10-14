# Spec Delta — `frontend/reserva-publica-ui`

## Purpose

Reserva pública 24/7 sin cuenta para el paciente: elegir motivo, profesional y slot real, reservar con DNI y teléfono, y autogestionar el turno con el token público (confirmar, cancelar, reprogramar), consumiendo los contratos C-03 y C-05 sobre una experiencia de tres pasos en español.

## ADDED Requirements

### Requirement: Reserva en 3 taps motivo→slot→DNI+teléfono

La UI SHALL guiar la reserva pública en tres pasos — 1) motivo (prestación con su duración), 2) profesional + slot real desde `GET /api/v1/disponibilidad`, 3) DNI + teléfono argentinos validados en cliente — y SHALL crear el turno con `POST /api/v1/turnos/publicos` con token de idempotencia, mostrando tras el `201` la confirmación con el `token_publico` para gestionar el turno; ante `409` SHALL ofrecer los slots alternativos sin perder los datos ingresados.

#### Scenario: Reserva 3 taps crea turno reservado con token

- **WHEN** un paciente sin sesión elige motivo "Limpieza", elige profesional y slot libre, ingresa DNI y teléfono argentinos válidos (datos sintéticos) y confirma
- **THEN** la UI envía una sola creación idempotente, muestra el estado `reservado` con el `token_publico` y el resumen (motivo, profesional, fecha y hora), todo en español y sin exigir registro ni login

#### Scenario: Doble envío no duplica el turno

- **WHEN** el paciente pulsa confirmar dos veces seguidas (o reintenta tras un corte de red) con el mismo token de idempotencia
- **THEN** la UI envía un solo intento efectivo o reutiliza el mismo token de idempotencia, existe un único turno `reservado` y el paciente ve una sola confirmación

#### Scenario: Slot tomado en concurrente ofrece alternativas sin perder datos

- **WHEN** el slot elegido fue ocupado por otro paciente y el backend responde `409` con `slots_alternativos`
- **THEN** la UI muestra el aviso de slot ocupado en español con los slots alternativos, conserva motivo, profesional, DNI y teléfono ya ingresados, y permite elegir un alternativo en un tap

### Requirement: Validación AR de identidad en cliente antes de enviar

La UI SHALL validar DNI argentino (7–8 dígitos) y teléfono en formato E.164 AR (`+54…`) antes de enviar, con mensajes en español por campo, y SHALL jamás enviar ni registrar valores inválidos; la primera reserva informa que puede requerir verificación por código (el flujo de verificación lo ejecuta el backend C-03).

#### Scenario: DNI o teléfono inválidos bloquean el envío con aviso por campo

- **WHEN** el paciente ingresa un DNI de 5 dígitos o un teléfono sin código país y pulsa confirmar
- **THEN** la UI marca cada campo inválido con su mensaje en español, no envía ninguna request y no registra los valores en consola ni en reportes de error

### Requirement: Gestión del turno propio con token sin login

La UI SHALL exponer ver (`GET .../publicos/:token`), confirmar, cancelar (respetando la antelación mínima del backend) y reprogramar (`POST .../publicos/:token/...`) a partir del `token_publico`, con el principio de ver-propio mínimo: solo los campos del turno alcanzado por ese token; ante token inválido SHALL responder con no-encontrado genérico sin filtrar datos de otros turnos.

#### Scenario: Gestión con token confirma un turno reservado

- **WHEN** el paciente abre su enlace de gestión con un `token_publico` válido de un turno `reservado` y pulsa confirmar
- **THEN** la UI refleja `confirmado` tras el `200`, muestra el resumen actualizado en español y no expone ningún dato de otros turnos

#### Scenario: Gestión con token cancela en término y rechaza fuera de término

- **WHEN** el paciente cancela un turno dentro de la antelación mínima configurada, y luego intenta cancelar otro fuera de término que responde `422` con la política del consultorio
- **THEN** la primera cancelación refleja `cancelado` con su comprobante en español, y la segunda muestra la política del consultorio (horas mínimas y contacto) sin mutar el turno

#### Scenario: Gestión con token reprograma conservando el token

- **WHEN** el paciente reprograma su turno a un slot libre de igual prestación
- **THEN** la UI muestra el nuevo horario con el mismo `token_publico`, indica que la reserva anterior quedó como `reprogramado`, y la trazabilidad es visible en el resumen

#### Scenario: Token inválido no filtra datos

- **WHEN** se abre la gestión con un token inexistente o malformado
- **THEN** la UI muestra un no-encontrado genérico en español, no renderiza ningún dato de turnos, pacientes ni agenda, y no registra el token en consola ni en reportes
