# auditoria/registro-acciones Specification

## Purpose
Esta capacidad deja trazabilidad inmutable de las acciones sensibles del sistema (quién hizo qué, sobre qué entidad y cuándo), para auditoría administrativa y cumplimiento de las reglas de negocio.

## Requirements

### Requirement: Auditoría obligatoria de acciones sensibles

El sistema SHALL registrar una fila en `AuditoriaLog` (accion, entidad, entidad_id, diff jsonb, usuario, ip, hora) por cada ocurrencia de: login, logout, refresh, denegación por rol, crear/cancelar turno, sobreturno, cobro, cierre de caja, edición clínica, cambio de roles, validación de cobertura OS y alta/actualización de afiliación OS (RN-AU-03), sin incluir DNI, teléfonos, nro. de afiliado, historia clínica, hashes ni tokens en el `diff`; y SHALL exponer `GET /api/v1/auditoria?entidad&entidad_id&accion&desde&hasta&page&page_size` (JWT, solo `admin`) que devuelve la bitácora paginada ordenada por hora descendente, con los `diff` ya sanitizados.

#### Scenario: Login/logout/refresh/denegación generan filas en AuditoriaLog

- **WHEN** ocurren un login exitoso, un refresh, un logout y una denegación `403` por rol insuficiente
- **THEN** existen 4 filas en `AuditoriaLog` con la acción, el usuario y la hora correspondientes, y ninguna contiene hashes, tokens ni datos personales en claro

#### Scenario: Crear turno queda auditado

- **WHEN** un usuario autorizado crea un turno con `POST /api/v1/turnos` y se consulta `GET /api/v1/auditoria?entidad=turno&entidad_id=<id>`
- **THEN** la bitácora muestra la creación con el usuario responsable, sin exponer DNI ni teléfono del paciente en el `diff`

#### Scenario: Bitácora filtra por entidad e id solo para admin

- **WHEN** admin consulta `GET /api/v1/auditoria?entidad=pago&entidad_id=<id>` y recepción intenta la misma consulta
- **THEN** admin recibe `200` con solo las filas de ese pago y recepción recibe `403` + `acceso_denegado`

#### Scenario: Los 5 eventos quedan registrados y son consultables

- **WHEN** ocurren crear turno, cancelar turno, cobro acreditado, cierre de caja y edición clínica, y admin filtra por cada `entidad/entidad_id`
- **THEN** cada filtro devuelve su evento (`turno_creado|turno_cancelado|pago_acreditado|cierre_creado|evolucion_registrada`) con usuario y hora, sin PII/HC en ningún `diff`

#### Scenario: Validación OS y afiliaciones quedan registradas sin PII

- **WHEN** ocurren una validación de cobertura y un alta/actualización de afiliación, y admin filtra por `entidad=validacion_cobertura` y `entidad=afiliacion_os`
- **THEN** cada filtro devuelve su evento (`validacion_os_registrada|afiliacion_creada|afiliacion_actualizada`) con usuario y hora, y ningún `diff` contiene nro. de afiliado, DNI, teléfono ni HCE

#### Scenario: Filtros y paginación acotan la bitácora

- **WHEN** admin consulta con `accion=cierre_creado&desde&hasta&page=2&page_size=20`
- **THEN** responde `200` con la página pedida, total y orden descendente por hora, sin exponer DNI, teléfonos, HCE ni tokens

### Requirement: Eventos de lista de espera auditados sin PII

El sistema SHALL registrar los eventos `lista_espera_creada|oferta_enviada|oferta_expirada|lista_espera_asignada|pago_reembolsado` (entidades `lista_espera|oferta_espera|pago` según corresponda) cuyos `diff`s solo contienen IDs, estados, score/componentes, horarios y montos — jamás DNI, teléfonos, HCE, nro. de afiliado ni datos de otros en espera — aplicando `sanitizar_diff()` existente (R6, Ley 25.326); y SHALL mantener consultables los eventos previos sin cambios.

#### Scenario: Asignación y reembolso auditados sin PII

- **WHEN** una oferta se asigna por pago o un doble pago se reembolsa, y admin consulta `GET /api/v1/auditoria?entidad=oferta_espera|pago`
- **THEN** existen `lista_espera_asignada` / `pago_reembolsado` con IDs, estados y monto, y ningún `diff`/log/response del flujo contiene PII ni datos de otros en espera
