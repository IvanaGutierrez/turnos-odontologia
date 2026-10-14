# Proposal — C-08 `sena-mercadopago-webhook`

## Why

Primera vez y tratamientos largos exigen seña para confirmar (RN-PA-01, US-030), pero hoy `url_pago` es un link opaco firmado sin cobro real (C-03/C-05): ningún pago puede acreditarse y el `422 sena_pendiente` no tiene salida. Este change cierra el circuito de dinero del MVP: preferencia Mercado Pago con metadata → webhook verificado por firma → acreditación idempotente que confirma el turno. Governance CRITICO: hay dinero real en juego.

## What Changes

- Preferencia MP con metadata (`turno_id`/`presupuesto_id`) en ARS; `GET /pagar/:token` resuelve el link opaco existente a la preferencia real (init_point) sin cambiar su shape en C-03/C-05.
- Webhook `POST /webhooks/mercadopago` (fuera de `/api/v1`, sin JWT): verifica firma `x-signature` (HMAC-SHA256) siempre; firma inválida → `401` sin procesar ni mutar.
- Idempotencia por `mp_payment_id` UNIQUE: webhook duplicado → `200` sin doble acreditación (RN-PA-03).
- Al acreditarse: pago → `acreditado`, turno con seña requerida → `confirmado` (RN-PA-02), evento de caja MP para conciliación de C-09 + comprobante por WhatsApp (reusa infraestructura C-06).
- Pago rechazado → estado visible + reintento, turno sigue pendiente (`reservado`).
- Monto/% de seña configurable por prestación (`sena_monto_fijo` / `sena_porcentaje` sobre `precio_base`).
- Modelo `Pago` (`mp_payment_id`/`mp_preference_id` únicos); **migración Alembic 009** (ver design decisión 1: CHANGES.md decía "005" pero 005–008 ya existen; head verificado `008_ficha_clinica`).
- Tests planeados (se ejecutan en apply, con Fake MP client y sandbox, jamás red real ni credenciales reales — R0).

## Capabilities

### New Capabilities

- `cobros/sena-mercadopago`: cobro de señas por Mercado Pago — preferencia con metadata en ARS, link de pago (`GET /pagar/:token`), webhook con firma e idempotencia, máquina de estados del pago, confirmación del turno al acreditarse, evento de caja MP y comprobante por WhatsApp.

### Modified Capabilities

_(ninguna — `agenda/reserva-publica` y `agenda/autogestion-paciente` no cambian sus REQUIREMENTS: ya especifican `url_pago` no vacía y `422 sena_pendiente` "el cobro es C-08". Este change rellena ese hueco respetando sus shapes `201`/`422`; la máquina de estados C-05 y las plantillas/colas C-06 se reutilizan sin modificar)_

## Impact

- Nuevo: `infrastructure/mercadopago/` (cliente con protocolo mockeable + Fake para tests), servicio `pagos.py` (preferencia + acreditación transaccional), router `webhooks/mercadopago` (verificación `x-signature`) + `GET /pagar/:token`, modelo `Pago` + migración 009 (+ columnas de seña en `prestacion`), settings `MP_*` / `SENA_*` solo por env (R7), `.env.example` extendido.
- Reusa sin modificar: link opaco C-03 (`url_pago_para` sigue siendo la entrada; ahora resuelve a preferencia real), bloqueo `SenaPendienteError → 422` C-05 (sigue vigente hasta acreditar), colas/plantillas WhatsApp C-06 (solo se encola un comprobante), auditoría C-02 (nuevos eventos `pago_*` sin PII).
- Interfaz hacia C-09: la acreditación deja evento de caja MP (`pago_acreditado` con monto/método/turno) para conciliación del cierre diario; C-09 crea `MovimientoCaja`/`CierreDiario` (migración 010+), no este change.
- No-objetivos explícitos: cierre/conciliación de caja (C-09), factura ARCA (v2), reembolsos automáticos (el estado `reembolsado` se modela pero el flujo es manual), marketing, lista de espera (C-14 consume el link de seña, no lo implementa).
