# obras-sociales/validacion-cobertura Specification

## Purpose
Permite validar antes de confirmar si la prestación del turno está cubierta por la obra social del paciente — `cubre|parcial|no_cubre` contra nomenclador local versionado con topes y frecuencias — con derivación a particular si no cubre, sin mutar el turno y con auditoría sin PII.

## Requirements

### Requirement: Validación preventiva de cobertura por turno

El sistema SHALL exponer `POST /api/v1/obras-sociales/validar` (JWT, solo staff `admin|recepcion|odontologo`) que, dado `{turno_id, afiliacion_id}`, resuelve la afiliación vigente del paciente, cruza la prestación del turno contra el nomenclador LOCAL versionado de la obra social y sus topes/frecuencias, persiste una fila `ValidacionCobertura` (turno, afiliación, versión de nomenclador usada, resultado, detalle `jsonb`, fecha) y SHALL responder `{resultado: cubre|parcial|no_cubre, detalle, validacion_id, nomenclador_version}` sin exponer nro. de afiliado ni DNI en la respuesta (R6).

#### Scenario: Afiliado válido + práctica cubierta → `cubre` con detalle

- **WHEN** staff válido pide validar un turno cuya prestación figura en el nomenclador vigente de la OS, con afiliación vigente y topes/frecuencias sin agotar
- **THEN** responde `200` con `resultado='cubre'`, `detalle` con la entrada de nomenclador aplicada y la versión usada, y persiste la `ValidacionCobertura` con esa versión congelada

#### Scenario: Tope agotado o frecuencia excedida → `parcial` con copago

- **WHEN** la práctica está en el nomenclador pero el tope (monto/cantidad) está agotado o la frecuencia del período está excedida para el afiliado
- **THEN** responde `200` con `resultado='parcial'`, `detalle` con el tope/frecuencia agotado y el copago/particular a cargo, y persiste la validación

#### Scenario: No afiliado o fuera de nomenclador → `no_cubre` + deriva a particular

- **WHEN** el paciente no tiene afiliación vigente con esa OS o la prestación no figura en el nomenclador vigente
- **THEN** responde `200` con `resultado='no_cubre'`, `detalle` con el motivo (`sin_afiliacion_vigente|fuera_de_nomenclador`), y la respuesta incluye la derivación a flujo particular (`deriva_particular=true` + indicación de generar presupuesto C-07 antes de confirmar); el turno NO cambia de estado por validar

#### Scenario: Validar no confirma ni muta el turno

- **WHEN** se valida cualquier turno `reservado` (cualquiera sea el resultado)
- **THEN** el estado del turno queda intacto y la única escritura es la `ValidacionCobertura` + su evento de auditoría

#### Scenario: Cambio de versión de nomenclador no rompe validaciones previas

- **WHEN** la OS publica una nueva versión del nomenclador después de validaciones ya registradas
- **THEN** las validaciones previas conservan su `nomenclador_version` y su resultado original, y las validaciones nuevas usan la versión vigente

#### Scenario: Validación sin permiso o con datos inválidos

- **WHEN** un rol sin permiso intenta validar, el turno/afiliación no existe, o la afiliación pertenece a otro paciente
- **THEN** responde `403` genérico + `acceso_denegado` (sin permiso), `404` idéntico sin filtrar datos (inexistente), o `422` (afiliación de otro paciente / OS inactiva), sin exponer nro. de afiliado ni DNI en ningún caso

### Requirement: Validación auditada sin PII

El sistema SHALL registrar el evento `validacion_os_registrada` por cada validación (entidad `validacion_cobertura`), cuyo `diff` solo contiene `{validacion_id, turno_id, obra_social_id, resultado, nomenclador_version}` — jamás nro. de afiliado, DNI, teléfonos ni detalle clínico — y SHALL aplicar `sanitizar_diff()` existente (R6, Ley 25.326).

#### Scenario: Validación auditada sin PII

- **WHEN** se registra cualquier validación y admin consulta `GET /api/v1/auditoria?entidad=validacion_cobertura&entidad_id=<id>`
- **THEN** existe el evento `validacion_os_registrada` con resultado y versión, y ningún `diff`/log/response de la validación contiene nro. de afiliado, DNI, teléfono ni HCE
