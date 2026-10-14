# Proposal — C-06 `recordatorios-whatsapp`

## Why

El ausentismo se combate con confirmación inmediata + recordatorios 24 h / 3 h automáticos (US-010, RN-NO-01/02); hoy no existe ningún envío (el worker de compose es un placeholder `ping` y Redis solo se usa para rate-limit). Este change cierra el camino crítico del MVP (C-01→…→C-06): sin él, la autogestión de C-05 no reduce no-shows ni avisa a recepción ante fallos.

## What Changes

- Integración `infrastructure/whatsapp`: cliente Cloud API con plantillas **utility** aprobadas (confirmación inmediata + recordatorio 24 h + aviso 3 h, nombres y ventanas configurables por env); marketing exige opt-in aparte y queda fuera de scope (RN-NO-01).
- Workers Redis: cola de envíos `wa:envios` con reintentos (backoff exponencial + DLQ), idempotencia por `(turno_id, tipo_aviso)`; scheduler que encola al crear/confirmar y reagenda ante reprogramación/cancelación.
- Webhook `POST /webhooks/whatsapp` con verificación de firma siempre (GET verify + HMAC-SHA256 en POST); firma inválida → `401` sin procesar ni mutar.
- Fallback email/SMTP + SMS gateway cuando el paciente no tiene WhatsApp (RN-NO-04); degradación graceful: si WA cae tras reintentos, flujo manual + aviso a recepción, el turno nunca se pierde.
- Migración Alembic: tabla `aviso_envio` mínima (idempotencia durable + auditoría de los 3 envíos).
- Tests planeados (se ejecutan en apply): secuencia de 3 envíos en orden, firma inválida → 401, reintento sin duplicar, fallback sin WA, WA caído con turno intacto.

## Capabilities

### New Capabilities

- `notificaciones/recordatorios-whatsapp`: confirmación + recordatorios automáticos por WhatsApp con workers Redis — plantillas utility configurables, cola con reintentos e idempotencia (turno_id + tipo_aviso), webhook verificado por firma, fallback email/SMS y degradación a flujo manual sin perder el turno.

### Modified Capabilities

_(ninguna — `agenda/crear-turno`, `agenda/reserva-publica`, `agenda/autogestion-paciente` y `agenda/agenda-recepcion` no cambian sus REQUIREMENTS: este change solo reacciona a sus eventos crear/confirmar/reprogramar/cancelar y reutiliza sus shapes `201`/`409`/`422`, la máquina de estados C-05 y el rate-limit Redis existente)_

## Impact

- Nuevo: `infrastructure/whatsapp/` (transporte mockeable + plantillas), `workers/envios.py` + `workers/scheduler.py`, router `webhooks/whatsapp` (verificación de firma), modelo + migración `aviso_envio`, settings `WHATSAPP_*` / `RECORDATORIO_*` / `SMTP_*` / `SMS_*` solo por env (R7), `.env.example` extendido.
- Reusa sin modificar: exclusión GiST C-01 (R3 intacta), máquina de estados y auditoría C-02/C-05 (nuevos eventos `aviso_encolado|aviso_enviado|aviso_fallido|aviso_fallback`, sin PII), Redis real en prod + fakeredis en tests (patrón C-02/C-03, R8), compose `worker` que pasa de `ping` a consumidor real (cambio de comando, no de topología).
- No-objetivos explícitos: writeback conversacional "SÍ" (C-12, aquí el webhook solo acusa recibo y audita sin mutar agenda), cobro MP (C-08), validación OS (C-13), lista de espera (C-14), marketing con opt-in.
