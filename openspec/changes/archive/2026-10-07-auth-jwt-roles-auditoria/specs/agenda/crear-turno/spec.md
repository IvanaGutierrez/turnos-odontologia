# Spec Delta — `agenda/crear-turno`

## ADDED Requirements

### Requirement: Crear turno exige JWT válido

El sistema SHALL exigir un JWT access válido en `POST /api/v1/turnos` (saldando el hook `get_current_user` dejado por C-01) y SHALL responder `401` ante token ausente o expirado, manteniendo intacto el shape `201`/`409`/`422` definido por C-01 para peticiones autenticadas y autorizadas.

#### Scenario: Crear turno sin token → 401

- **WHEN** se envía `POST /api/v1/turnos` con un payload válido pero sin access token
- **THEN** responde `401` y no se crea ningún turno

#### Scenario: Crear turno con access expirado → 401

- **WHEN** se envía `POST /api/v1/turnos` con un access token expirado
- **THEN** responde `401` y no se crea ningún turno
