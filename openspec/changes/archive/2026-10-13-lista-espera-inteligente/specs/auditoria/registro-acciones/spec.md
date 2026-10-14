# Spec Delta — `auditoria/registro-acciones`

## ADDED Requirements

### Requirement: Eventos de lista de espera auditados sin PII

El sistema SHALL registrar los eventos `lista_espera_creada|oferta_enviada|oferta_expirada|lista_espera_asignada|pago_reembolsado` (entidades `lista_espera|oferta_espera|pago` según corresponda) cuyos `diff`s solo contienen IDs, estados, score/componentes, horarios y montos — jamás DNI, teléfonos, HCE, nro. de afiliado ni datos de otros en espera — aplicando `sanitizar_diff()` existente (R6, Ley 25.326); y SHALL mantener consultables los eventos previos sin cambios.

#### Scenario: Asignación y reembolso auditados sin PII

- **WHEN** una oferta se asigna por pago o un doble pago se reembolsa, y admin consulta `GET /api/v1/auditoria?entidad=oferta_espera|pago`
- **THEN** existen `lista_espera_asignada` / `pago_reembolsado` con IDs, estados y monto, y ningún `diff`/log/response del flujo contiene PII ni datos de otros en espera
