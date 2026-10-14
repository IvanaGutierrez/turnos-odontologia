# admin/gestion-usuarios Specification

## Purpose
Permite que el admin gestione usuarios internos y sus roles con trazabilidad completa, bloqueando cualquier operación de no-admin con 403 auditable.

## Requirements

### Requirement: CRUD de usuarios solo admin con baja lógica

El sistema SHALL exponer `GET /api/v1/usuarios` (lista paginada), `POST /api/v1/usuarios` (alta con email único, rol válido, password hasheada Argon2/bcrypt), `GET /api/v1/usuarios/:id`, `PATCH /api/v1/usuarios/:id` (cambiar `rol` y/o `activo`) y `DELETE /api/v1/usuarios/:id` (baja lógica → `activo=false`, nunca borrado físico); todos SHALL exigir JWT + recurso `usuarios` (solo `admin`); la respuesta JAMÁS incluye `password_hash` (R6).

#### Scenario: Admin crea usuario odontólogo → 201 sin hash expuesto

- **WHEN** admin crea un usuario con email, rol `odontologo` y password válidos
- **THEN** responde `201` con `{id, email, rol, activo}` sin `password_hash`, y existe el evento `usuario_creado`

#### Scenario: Recepción intenta crear usuario → 403 + log

- **WHEN** un JWT con rol `recepcion` (u `odontologo`) invoca `POST /api/v1/usuarios`
- **THEN** responde `403` genérico sin crear nada y registra `acceso_denegado` con usuario, recurso y hora

#### Scenario: Email duplicado o rol inválido → 422/409 sin efectos

- **WHEN** se crea un usuario con email ya existente o rol fuera de `admin|odontologo|recepcion`
- **THEN** responde `409` (duplicado) o `422` (rol inválido) sin crear usuario ni evento de alta

#### Scenario: Baja lógica desactiva sin borrar

- **WHEN** admin elimina un usuario activo
- **THEN** responde `200` con `activo=false`, el login posterior de ese usuario es `401`, y existe `usuario_desactivado`

### Requirement: Cambio de roles auditado con denegación trazada

El sistema SHALL auditar todo cambio de rol (`rol_cambiado` con `{usuario_id, rol_anterior, rol_nuevo}`, sin credenciales ni PII) y toda denegación sobre `usuarios` (`acceso_denegado`); SHALL validar que el rol destino pertenece al enum; un admin NO puede quitarse su propio rol admin en su propio usuario (autobloqueo → `422`).

#### Scenario: Admin cambia rol recepción→odontólogo → 200 + auditado

- **WHEN** admin cambia el rol de un usuario de `recepcion` a `odontologo`
- **THEN** responde `200` con el rol nuevo y existe `rol_cambiado` con anterior y nuevo, sin exponer hash ni tokens

#### Scenario: Odontólogo lista usuarios → 403 + log

- **WHEN** un JWT `odontologo` invoca `GET /api/v1/usuarios`
- **THEN** responde `403` genérico y registra `acceso_denegado`

#### Scenario: Admin intenta auto-degradarse → 422

- **WHEN** admin intenta cambiar su propio rol a `recepcion`
- **THEN** responde `422` y conserva el rol `admin`
