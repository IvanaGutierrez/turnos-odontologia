# Spec Delta — `auditoria/registro-acciones`

## Purpose

Esta capacidad deja trazabilidad inmutable de las acciones sensibles del sistema (quién hizo qué, sobre qué entidad y cuándo), para auditoría administrativa y cumplimiento de las reglas de negocio.

## ADDED Requirements

### Requirement: Auditoría obligatoria de acciones sensibles

El sistema SHALL registrar una fila en `AuditoriaLog` (accion, entidad, entidad_id, diff jsonb, usuario, ip, hora) por cada ocurrencia de: login, logout, refresh, denegación por rol, crear/cancelar turno, sobreturno, cobro, cierre de caja, edición clínica y cambio de roles (RN-AU-03), sin incluir DNI, teléfonos, historia clínica, hashes ni tokens en el `diff`.

#### Scenario: Login/logout/refresh/denegación generan filas en AuditoriaLog

- **WHEN** ocurren un login exitoso, un refresh, un logout y una denegación `403` por rol insuficiente
- **THEN** existen 4 filas en `AuditoriaLog` con la acción, el usuario y la hora correspondientes, y ninguna contiene hashes, tokens ni datos personales en claro

#### Scenario: Crear turno queda auditado

- **WHEN** un usuario autorizado crea un turno con `POST /api/v1/turnos` y se consulta `GET /api/v1/auditoria?entidad=turno&entidad_id=<id>`
- **THEN** la bitácora muestra la creación con el usuario responsable, sin exponer DNI ni teléfono del paciente en el `diff`
