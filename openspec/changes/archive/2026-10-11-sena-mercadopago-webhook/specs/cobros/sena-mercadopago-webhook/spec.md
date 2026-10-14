# Spec Delta — `cobros/sena-mercadopago`

## Purpose

Permite que la clínica cobre señas de primera vez y tratamientos largos por Mercado Pago en ARS — preferencia con metadata, link de pago, webhook verificado por firma con acreditación idempotente que confirma el turno, evento de caja MP y comprobante por WhatsApp — con rechazo visible y reintento sin perder la reserva.

## ADDED Requirements

### Requirement: Preferencia MP con metadata y link de pago en ARS

El sistema SHALL, ante `GET /pagar/:token` con token opaco válido (firmado con `PAGO_LINK_SECRET`, patrón C-03), buscar o crear idempotentemente UN `Pago pendiente` por turno y crear (o reutilizar si sigue vigente) la preferencia MP con `currency_id='ARS'`, `metadata={turno_id, presupuesto_id?}` y monto según la seña configurada de la prestación; SHALL devolver `{init_point, monto, moneda:'ARS', estado_pago}`; y SHALL responder `404` idéntico ante token inválido y `422` de configuración si `requiere_sena=true` sin monto ni porcentaje configurados (nunca monto cero silencioso).

#### Scenario: Preferencia creada con link y metadata

- **WHEN** se abre `GET /pagar/:token` válido de un turno `reservado` cuya prestación exige seña configurada
- **THEN** responde `200` con `init_point` no vacío, `moneda='ARS'`, `estado_pago='pendiente'`, y la preferencia contiene `metadata.turno_id` igual al turno

#### Scenario: Monto fijo gana a porcentaje por prestación

- **WHEN** la prestación tiene `sena_monto_fijo` y `sena_porcentaje` configurados
- **THEN** el monto de la preferencia es `sena_monto_fijo`, y sin fijo es `precio_base * sena_porcentaje/100`

#### Scenario: Seña sin monto configurado es error visible

- **WHEN** la prestación tiene `requiere_sena=true` sin `sena_monto_fijo` ni (`precio_base` + `sena_porcentaje`)
- **THEN** responde `422` de configuración sin crear preferencia, y el turno sigue `reservado`

### Requirement: Webhook MP con verificación de firma siempre

El sistema SHALL exponer `POST /webhooks/mercadopago` (fuera de `/api/v1`, sin JWT) que exige `x-signature: ts=...,v1=...` con `v1 = HMAC-SHA256(MP_WEBHOOK_SECRET, "id:{data.id};request-id:{x-request-id};ts:{ts};")` comparado con `compare_digest`; SHALL responder `401` genérico ante firma ausente, inválida o cuerpo alterado, sin procesar, sin mutar pagos/turnos, sin auditar contenido y sin loguear PII; y SHALL confirmar el estado del pago contra MP (Fake en tests) antes de acreditar, no solo desde el cuerpo del aviso.

#### Scenario: Firma webhook inválida → 401 sin procesar

- **WHEN** llega `POST /webhooks/mercadopago` sin firma, con firma incorrecta o con cuerpo alterado tras firmar
- **THEN** responde `401` genérico, ningún pago cambia de estado, ningún turno muta y ningún log contiene PII del pagador ni tokens

### Requirement: Acreditación idempotente que confirma el turno

El sistema SHALL, ante aviso verificado de pago aprobado, transicionar en UNA transacción `pago pendiente→acreditado` (reclamo por estado + UNIQUE `mp_payment_id`), luego el turno con seña requerida `reservado→confirmado` (RN-PA-02, reusa máquina C-05), registrar el evento de caja MP `pago_acreditado` (para conciliación C-09) y encolar el comprobante por WhatsApp (reusa C-06); y SHALL responder `200` sin ningún efecto repetido ante el mismo `mp_payment_id` duplicado o concurrente (RN-PA-03).

#### Scenario: Webhook válido acredita de punta a punta

- **WHEN** llega un aviso verificado de pago aprobado para un turno `reservado` con seña requerida
- **THEN** el pago queda `acreditado` con `mp_payment_id` y `webhook_recibido_at`, el turno queda `confirmado`, existe el evento `pago_acreditado` con monto ARS, y hay un comprobante WA encolado — todo sin PII del pagador

#### Scenario: Webhook duplicado → 200 sin doble efecto

- **WHEN** el mismo aviso verificado (`mp_payment_id` idéntico) llega dos veces, incluso en concurrente
- **THEN** ambas responden `200`, existe UN solo `acreditado`, UN solo evento de caja y UN solo comprobante, y el turno sigue `confirmado` sin transiciones extra

### Requirement: Pago rechazado visible con reintento y turno pendiente

El sistema SHALL, ante aviso verificado de pago rechazado, transicionar `pago pendiente→rechazado` (idempotente por `mp_payment_id`), exponer `estado_pago='rechazado'` en `GET /pagar/:token` y en el turno público sin PII, ofrecer reintento con el mismo link (nueva preferencia, jamás dos pendientes por turno), y MANTENER el turno en `reservado` (Flujo 4: el turno sigue pendiente).

#### Scenario: Pago rechazado → visible + reintento, turno pendiente

- **WHEN** llega un aviso verificado de pago rechazado para un turno `reservado` con seña
- **THEN** el pago queda `rechazado`, `GET /pagar/:token` muestra `rechazado` con link de reintento, y el turno sigue `reservado` (confirmar sigue `422 sena_pendiente`)

### Requirement: Seña pendiente bloquea confirmar (integración C-05)

El sistema SHALL mantener que `POST /api/v1/turnos/publicos/:token/confirmar` responde `422` con `problema=sena_pendiente` y `url_pago` no vacía mientras no exista `pago acreditado` vinculado al turno, y SHALL confirmar (`reservado→confirmado`) por esa vía solo cuando el pago esté `acreditado` o la prestación no exija seña (RN-PA-01/02 ya especificados en `agenda/autogestion-paciente`, aquí se integran con el cobro real).

#### Scenario: Confirmar con seña pendiente sigue 422 hasta acreditar

- **WHEN** se confirma un turno con `requiere_sena=true` sin pago acreditado, y luego se acredita vía webhook verificado y se reintenta confirmar
- **THEN** el primer intento es `422 sena_pendiente` con `url_pago` y estado `reservado`; tras acreditar, el turno está `confirmado`

### Requirement: Configuración, privacidad y observabilidad de los pagos

El sistema SHALL leer `MP_ACCESS_TOKEN`/`MP_WEBHOOK_SECRET` (fail-fast si `MP_CLIENT=http` sin ellos), `MP_CLIENT=fake|http`, `MP_TIMEOUT_S`, `MP_PUBLIC_KEY?` y `SENA_*` solo de env con placeholders no reales en `.env.example` (R7); SHALL loguear/auditar solo `{pago_id, turno_id, monto, estado, mp_payment_id, mp_preference_id}` (eventos `pago_creado|pago_acreditado|pago_rechazado`, jamás email/tarjeta/DNI/teléfono/tokens — R6, Ley 25.326); y SHALL exponer `GET /pagar/:token` con rate limit público (patrón C-03, RN-PU-03).

#### Scenario: Logs y errores sin PII del pagador

- **WHEN** se crea, acredita o rechaza un pago, o el webhook falla con `401`/`422`
- **THEN** ningún log, auditoría ni response contiene email, datos de tarjeta/cuenta, DNI, teléfono ni tokens MP; solo IDs, monto, moneda y estados
