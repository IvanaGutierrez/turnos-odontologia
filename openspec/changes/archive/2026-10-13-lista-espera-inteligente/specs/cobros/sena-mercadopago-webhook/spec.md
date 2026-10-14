# Spec Delta — `cobros/sena-mercadopago-webhook`

## ADDED Requirements

### Requirement: Webhook resuelve ofertas de espera y reclama el slot atómicamente

El sistema SHALL aceptar en el webhook `POST /webhooks/mercadopago` avisos cuya metadata porta `oferta_espera_id` (fijada al crear la preferencia de la oferta desde `link_pago_para` reuseado); SHALL reclamar la oferta con lock `FOR UPDATE` dentro de la misma transacción de acreditación existente: oferta `pendiente` vigente → camino de asignación (ver `agenda/lista-espera`); oferta ya `aceptada|expirada|desplazada` → el pago va a `reembolsado` con refund MP y evento `pago_reembolsado`, sin crear turno; y SHALL mantener intactas la verificación de firma, la idempotencia por `mp_payment_id` único y el reclamo por estado para avisos sin oferta (C-08 sin cambios).

#### Scenario: Aviso con oferta vigente asigna en la misma transacción

- **WHEN** llega un aviso verificado y acreditado con `oferta_espera_id` de oferta `pendiente` vigente y slot libre
- **THEN** en la misma transacción se acredita el pago, se acepta la oferta, se crea el turno `canal=lista_espera` y se emite `pago_acreditado`

#### Scenario: Aviso con oferta ya resuelta reembolsa sin duplicar

- **WHEN** llega un aviso acreditado con `oferta_espera_id` ya `aceptada|expirada|desplazada` (doble pago)
- **THEN** responde `200`, el pago queda `reembolsado` con refund ejecutado y `pago_reembolsado` auditado, y no se crea ningún turno

#### Scenario: Avisos sin oferta funcionan como siempre

- **WHEN** llega un aviso sin `oferta_espera_id` (flujo C-08 clásico turno/presupuesto)
- **THEN** se aplica el comportamiento C-08 vigente sin cambios (acreditación, duplicado, rechazo, `sin_turno`)
