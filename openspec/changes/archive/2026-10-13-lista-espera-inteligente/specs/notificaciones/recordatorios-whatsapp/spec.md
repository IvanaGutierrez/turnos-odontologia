# Spec Delta — `notificaciones/recordatorios-whatsapp`

## ADDED Requirements

### Requirement: Tipo utility oferta de lista de espera y blast top-N

El sistema SHALL admitir el tipo utility `oferta_lista_espera` (plantilla `WA_TEMPLATE_OFERTA`, variables R6: `nombre_pila?, fecha, hora, sede, link_gestion/seña` — jamás datos de otros en espera) junto a los 3 existentes, manteniendo el veto marketing (cualquier otro tipo → `422`); y SHALL enviar el blast del hueco al top-N rankeado con idempotencia por oferta (una oferta = un envío; reintentos y fallback email/SMS reusean la cascada C-06 con `destino_hash`, sin llamar a Meta en `WA_DRY_RUN`).

#### Scenario: Blast de oferta con plantilla y variables mínimas

- **WHEN** el worker oferta un hueco al top-N
- **THEN** cada ofertado recibe UN mensaje `oferta_lista_espera` con solo su slot (fecha, hora, sede, link de seña) y `destino_hash` en el registro

#### Scenario: Veto marketing intacto con el tipo nuevo

- **WHEN** se intenta encolar cualquier tipo fuera de los 4 utility (3 existentes + oferta)
- **THEN** se rechaza con `422` sin encolar ni llamar al proveedor

#### Scenario: Fallo de WA en blast degrada a recepción sin perder el hueco

- **WHEN** el transporte WA falla o el paciente no tiene WhatsApp durante el blast
- **THEN** aplica la cascada fallback + `aviso_a_recepcion` existentes, la oferta queda registrada igual (el TTL corre) y el hueco sigue libre
