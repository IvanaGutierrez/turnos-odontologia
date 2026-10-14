# Spec Delta — `notificaciones/recordatorios-whatsapp`

## Purpose

El inbound del webhook deja de ser solo-acuse: con firma válida enruta al handler conversacional (C-12), manteniendo intactos el `401` ciego y el `200` idempotente de C-06.

## MODIFIED Requirements

### Requirement: Webhook con verificación de firma siempre

El sistema SHALL exponer `POST /webhooks/whatsapp` (más `GET` de verificación con `hub.verify_token`) que exige `X-Hub-Signature-256 = HMAC-SHA256(WHATSAPP_WEBHOOK_SECRET, body)` comparado con `compare_digest`; SHALL responder `401` con cuerpo genérico ante firma ausente, inválida o cuerpo alterado, sin procesar, sin mutar agenda, sin auditar contenido y sin loguear PII; SHALL responder `200` idempotente ante `wa_message_id` duplicado (sin re-mutar ni re-responder); y SHALL, solo con firma válida y mensaje no duplicado, enrutar al handler conversacional (`notificaciones/confirmacion-conversacional`), registrando la respuesta junto a `aviso_recibido` sin texto libre.

#### Scenario: Firma webhook inválida → 401 sin procesar

- **WHEN** llega `POST /webhooks/whatsapp` sin firma, con firma incorrecta o con cuerpo alterado tras firmar
- **THEN** responde `401` genérico, no muta ningún turno, no crea ningún aviso ni conversación, y ningún log contiene teléfonos, textos libres ni tokens

#### Scenario: Mensaje verificado se enruta al bot sin doble proceso

- **WHEN** llega `POST /webhooks/whatsapp` con firma válida y `wa_message_id` nuevo con texto "SÍ"
- **THEN** responde `200`, el handler conversacional procesa el intent una sola vez observable, y un reintento Meta con el mismo `wa_message_id` devuelve `200` sin re-mutar ni re-responder
