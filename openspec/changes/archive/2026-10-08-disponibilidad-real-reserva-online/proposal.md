# Proposal — C-03 `disponibilidad-real-reserva-online`

## Why

El paciente hoy no puede ver huecos reales ni reservar sin llamar: la agenda vive en recepción y cada consulta telefónica cuesta tiempo operativo. Este change abre la agenda online 24/7 con disponibilidad real (sin huecos fantasma) y reserva pública sin cuenta, que es el primer paso del camino crítico hacia la autogestión (C-05) y los recordatorios (C-06).

## What Changes

- `GET /api/v1/disponibilidad?prestacion_id&profesional_id&desde&hasta` — slots calculados como horario del profesional menos bloqueos menos turnos activos, derivados de la prestación/motivo (`motivo→duración→profesional→slot`); sin login, con rate limit.
- `POST /api/v1/turnos/publicos` — crea turno en estado `reservado` con DNI + teléfono; exige código de verificación en primera reserva; acepta token de idempotencia y devuelve `token_publico`; rate limit por IP + teléfono; ante colisión entre GET y POST responde `409` + alternativos (mismo shape que C-01).
- Link/QR compartible (`/reservar/:slug`) consumible sin login (el slug lo resuelve el frontend en C-10; el backend garantiza que los endpoints públicos no exigen JWT); si la prestación exige seña, la respuesta incluye link de pago (el cobro lo implementa C-08, aquí solo el link).
- Modelos `HorarioProfesional` / `Bloqueo` + migración 003 con índices para rango/fecha; auditoría de la reserva pública (RN-AU-03).
- Plan TDD (los tests se escriben en `apply`, aquí solo se especifican): slots excluyen bloqueos/turnos; doble submit idempotente; rate limit; 409 con alternativos; verificación exigida en primera reserva.

## Capabilities

### New Capabilities

- `agenda/disponibilidad`: exponer slots reales por prestación/profesional/ventana como horario menos bloqueos menos turnos activos, sin exponer quién ocupa un slot y sin ofrecer huecos fantasma.
- `agenda/reserva-publica`: crear turno `reservado` sin cuenta (DNI + teléfono + verificación en primera reserva), con idempotencia por clave, rate limit por IP + teléfono, `token_publico` en respuesta, link de pago cuando la prestación exige seña y `409` + alternativos ante carrera con otro ocupante.

### Modified Capabilities

_(ninguna — `agenda/crear-turno` no cambia: el endpoint protegido `POST /api/v1/turnos` conserva su contrato C-01/C-02; la reserva pública lo reutiliza por servicio interno y la exclusión DB sigue mandando)_

## Impact

- Nuevo: routers públicos (`disponibilidad`, `turnos publicos`) sin JWT, servicio de cálculo de slots, servicio de reserva pública (verificación por código + idempotencia + rate limit Redis), modelos `HorarioProfesional`/`Bloqueo`, migración 003, settings/env nuevos (`CANCEL_MIN_HOURS` no — es C-05; aquí `RATE_PUBLIC_*`, `VERIF_*`, `RESERVA_*`).
- Reusa sin modificar: constraint de exclusión C-01 (última línea de defensa), shape `409` + alternativos, validaciones AR DNI/E.164, sanitización R6, auditoría C-02.
- Sin frontend en este change (el `/reservar/:slug` se consume en C-10); sin cobro real MP (C-08); sin WhatsApp programático (C-06; la verificación por código usa el proveedor existente solo como emisor, degradando a flujo manual si cae).
- No-objetivos explícitos: autogestión con token (C-05), agenda de recepción (C-04), confirmación conversacional (C-12), lista de espera (C-14).
