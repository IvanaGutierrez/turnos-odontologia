# Spec Delta — `auditoria/registro-acciones`

## MODIFIED Requirements

### Requirement: Auditoría obligatoria de acciones sensibles

El sistema SHALL registrar una fila en `AuditoriaLog` (accion, entidad, entidad_id, diff jsonb, usuario, ip, hora) por cada ocurrencia de: login, logout, refresh, denegación por rol, crear/cancelar turno, sobreturno, cobro, cierre de caja, edición clínica y cambio de roles (RN-AU-03), sin incluir DNI, teléfonos, historia clínica, hashes ni tokens en el `diff`; y SHALL exponer `GET /api/v1/auditoria?entidad&entidad_id&accion&desde&hasta&page&page_size` (JWT, solo `admin`) que devuelve la bitácora paginada ordenada por hora descendente, con los `diff` ya sanitizados.

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

#### Scenario: Filtros y paginación acotan la bitácora

- **WHEN** admin consulta con `accion=cierre_creado&desde&hasta&page=2&page_size=20`
- **THEN** responde `200` con la página pedida, total y orden descendente por hora, sin exponer DNI, teléfonos, HCE ni tokens
