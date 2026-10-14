# auth/autorizacion-rbac Specification

## Purpose
Esta capacidad garantiza que cada endpoint interno solo sea operable por los roles habilitados según la matriz (admin, odontólogo, recepción), denegando por defecto todo acceso no autorizado de forma auditable.

## Requirements

### Requirement: Acceso denegado por defecto según matriz de roles

El sistema SHALL exigir autenticación JWT en todos los endpoints internos y SHALL autorizar cada acción contra la matriz de `knowledge-base/03_actores_y_roles.md` (admin/odontologo/recepcion), denegando por defecto cualquier combinación no permitida.

#### Scenario: Rol sin permiso → 403 + evento auditado

- **WHEN** un usuario con rol `recepcion` invoca una operación reservada a `admin` (por ejemplo gestión de usuarios y roles) con un access válido
- **THEN** responde `403` sin ejecutar la acción y registra un evento de denegación en la auditoría con usuario, recurso y hora

#### Scenario: Odontólogo accede a su agenda pero no a administración

- **WHEN** un usuario con rol `odontologo` consulta su propia agenda y luego intenta una operación de configuración de agenda reservada a `admin`
- **THEN** la primera responde `200` y la segunda responde `403` con el evento auditado

### Requirement: Endpoints sin token o con token inválido responden 401

El sistema SHALL responder `401` (no `403`) cuando falta el access token, su firma es inválida o su `type` no es `access`, antes de evaluar cualquier permiso de rol.

#### Scenario: Sin token → 401

- **WHEN** se invoca un endpoint interno sin header de autorización
- **THEN** responde `401` sin ejecutar la acción ni revelar qué roles podrían acceder
