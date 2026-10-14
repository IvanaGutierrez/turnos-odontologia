# Spec Delta — `auth/autenticacion-jwt`

## Purpose

Esta capacidad permite que los usuarios internos (admin, odontólogo, recepción) inicien sesión con email y contraseña, mantengan su sesión con tokens JWT de corta y larga duración, y la cierren de forma segura, con protección contra abuso y sin revelar información sensible.

## ADDED Requirements

### Requirement: Login válido emite access y refresh

El sistema SHALL autenticar al usuario con email + contraseña verificada contra el hash almacenado y SHALL responder `200` con un JWT access de 15 minutos y un refresh de 7 días, incluyendo los claims `sub`, `roles`, `email`, `jti`, `type`, `iat`, `exp`.

#### Scenario: Login válido → 200 + access/refresh

- **WHEN** se envía `POST /api/v1/auth/login` con email y contraseña correctos de un usuario activo
- **THEN** responde `200` con un `access_token` (claim `type = access`, expiración 15') y un refresh (`type = refresh`, expiración 7 d) transportado en cookie HttpOnly (`secure`, `samesite=lax`), ambos con `sub`, `roles`, `email` y `jti` presentes

### Requirement: Credencial inválida responde 401 sin revelar existencia

El sistema SHALL responder `401` con un mensaje genérico ante email inexistente, contraseña incorrecta o usuario inactivo, sin distinguir entre esos casos, y SHALL registrar el intento fallido para bloqueo sin exponer hashes ni PII en la respuesta ni en los logs.

#### Scenario: Credencial inválida → 401 sin revelar existencia

- **WHEN** se envía `POST /api/v1/auth/login` con un email inexistente o con una contraseña incorrecta
- **THEN** responde `401` con un mensaje genérico idéntico en ambos casos, sin indicar si el email existe, y la respuesta y los logs no contienen hashes, tokens ni datos personales en claro

### Requirement: Access expirado es rechazado con 401

El sistema SHALL rechazar con `401` toda petición a un endpoint protegido cuyo access token esté expirado (`exp` pasado), tenga `type` distinto de `access` o firma inválida.

#### Scenario: Access expirado → 401

- **WHEN** se llama a `GET /api/v1/auth/me` con un access token expirado (emitido hace más de 15 minutos)
- **THEN** responde `401` con problema de autenticación y no devuelve ningún dato del perfil

### Requirement: Refresh válido rota el par e invalida el anterior

El sistema SHALL, ante un refresh válido y no revocado, emitir un par nuevo (access + refresh con `jti` nuevos) y SHALL invalidar el refresh anterior de modo que su reuso resulte en `401`; el refresh SHALL viajar en cookie HttpOnly.

#### Scenario: Refresh válido rota (nuevo par + viejo invalidado, reuso → 401)

- **WHEN** se envía `POST /api/v1/auth/refresh` con un refresh válido y luego se reintenta con el mismo refresh anterior
- **THEN** la primera llamada responde `200` con un par nuevo de `jti` distintos y la segunda (reuso del refresh viejo) responde `401`

### Requirement: Logout invalida el refresh

El sistema SHALL invalidar el refresh vigente al invocar `POST /api/v1/auth/logout`, de modo que ese refresh ya no pueda usarse para obtener nuevos pares.

#### Scenario: Logout invalida

- **WHEN** se envía `POST /api/v1/auth/logout` con una sesión válida y luego `POST /api/v1/auth/refresh` con el refresh de esa sesión
- **THEN** el logout responde `200` (o `204`) y el refresh posterior responde `401`

### Requirement: Rate limit y bloqueo por intentos en login

El sistema SHALL limitar `POST /api/v1/auth/login` a 5 intentos por minuto por combinación IP+email, respondiendo `429` al excederse, y SHALL bloquear temporalmente la cuenta/email ante intentos fallidos reiterados.

#### Scenario: Rate limit excedido → 429

- **WHEN** se envían 6 o más `POST /api/v1/auth/login` dentro de 60 segundos desde la misma IP con el mismo email
- **THEN** a partir del sexto responde `429` con indicación de reintento, sin procesar la credencial

### Requirement: Perfil propio del usuario autenticado

El sistema SHALL exponer `GET /api/v1/auth/me`, que con un access válido devuelve el perfil propio (id, email, roles, activo) sin exponer el hash de contraseña.

#### Scenario: Me devuelve el perfil propio

- **WHEN** se llama a `GET /api/v1/auth/me` con un access token válido
- **THEN** responde `200` con el email y los roles del usuario del `sub`, sin incluir `password_hash` ni ningún secreto
