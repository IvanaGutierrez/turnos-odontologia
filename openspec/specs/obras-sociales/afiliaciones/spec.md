# obras-sociales/afiliaciones Specification

## Purpose
Permite que recepción registre el padrón de afiliaciones a obras sociales con vigencia y nro. de afiliado enmascarado — alta, lectura, actualización y baja lógica solo staff — con duplicadas rechazadas y auditoría sin PII.

## Requirements

### Requirement: CRUD de afiliaciones solo staff con vigencia

El sistema SHALL exponer `GET/POST /api/v1/afiliaciones` y `GET/PATCH/DELETE /api/v1/afiliaciones/:id` (JWT, solo `admin|recepcion`; `DELETE` lógico con `vigente=false`), donde cada afiliación vincula `{paciente_id, obra_social_id, vigencia_desde, vigencia_hasta?}`; el nro. de afiliado se acepta al alta pero SHALL devolverse enmascarado (últimos 4) en toda lectura y jamás en logs/errores (R6); SHALL responder `409` ante afiliación duplicada vigente del mismo paciente en la misma OS y `422` ante vigencia inválida (`hasta < desde`); y SHALL auditar `afiliacion_creada|afiliacion_actualizada` sin PII.

#### Scenario: Alta de afiliación por staff con enmascarado

- **WHEN** recepción da de alta una afiliación vigente con datos ficticios válidos
- **THEN** responde `201`, las lecturas posteriores muestran el nro. de afiliado enmascarado (solo últimos 4), y existe el evento `afiliacion_creada` sin PII en el `diff`

#### Scenario: Duplicada vigente → 409, vigencia inválida → 422

- **WHEN** se da de alta una segunda afiliación vigente del mismo paciente en la misma OS, o con `vigencia_hasta` anterior a `vigencia_desde`
- **THEN** responde `409` (duplicada) o `422` (vigencia inválida) respectivamente, sin crear filas y sin exponer el nro. de afiliado en el error

#### Scenario: CRUD afiliaciones solo staff

- **WHEN** un odontólogo o un usuario sin JWT intenta cualquier verbo de `/afiliaciones`, o recepción opera normalmente
- **THEN** el primero recibe `403` genérico + `acceso_denegado` (odontólogo: lectura clínica sí, padrón OS no) y el segundo `401`; recepción opera `200/201` según el caso
