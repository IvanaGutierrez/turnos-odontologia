# frontend/api-client-auth Specification

## Purpose
Base técnica del frontend: cliente HTTP tipado contra `/api/v1`, sesión JWT con refresh rotativo y guarda de rutas por rol que refleja la matriz C-02, con errores sanitizados que nunca exponen datos personales.

## Requirements

### Requirement: Cliente HTTP tipado con base por entorno y reintentos seguros

El sistema SHALL exponer un `api-client` con tipos estrictos por recurso (sin `any`), base URL solo desde `VITE_API_URL` por entorno, access token en memoria (nunca en `localStorage`), refresh con rotación ante `401` con una sola renovación en vuelo, e idempotencia configurable por request; SHALL responder ante fallo de red o `5xx` con reintento limitado y mensaje en español, sin registrar cuerpos con PII.

#### Scenario: Request tipada usa VITE_API_URL y access en memoria

- **WHEN** el cliente pide la disponibilidad y la agenda en paralelo con sesión iniciada
- **THEN** ambas requests salen contra el `VITE_API_URL` del entorno con `Authorization: Bearer` desde memoria, las respuestas quedan tipadas sin `any`, y ningún token, DNI ni teléfono aparece en consola o reportes

#### Scenario: Access expirado rota el refresh una sola vez

- **WHEN** una request recibe `401` por access expirado mientras hay tres requests en vuelo
- **THEN** el cliente ejecuta una sola rotación de refresh, reintenta las tres con el access nuevo, y ante refresh inválido cierra la sesión y redirige al login con aviso en español

### Requirement: Login, sesión y guarda de rutas por rol

La UI SHALL exponer login (`POST /api/v1/auth/login`), cierre (`logout` con invalidación), perfil propio (`me`) y guarda de rutas que refleja la matriz C-02 (deny-by-default: ruta sin permiso → pantalla de acceso denegado + redirección al área del rol), con todo el copy en español y los errores `401`/`403`/`429` traducidos a mensajes operativos genéricos.

#### Scenario: Login guarda rutas por rol

- **WHEN** un usuario `recepcion` inicia sesión y navega a la agenda, y luego intenta abrir una ruta solo `admin`
- **THEN** la agenda operativa carga con sus permisos, la ruta admin muestra acceso denegado genérico en español sin revelar recursos existentes, y el `odontologo` que abre la agenda solo ve su propia agenda sin el control de sobreturno

#### Scenario: Rate limit de login muestra espera accionable

- **WHEN** el backend responde `429` tras intentos fallidos de login
- **THEN** la UI muestra un aviso en español que indica esperar antes de reintentar, sin revelar si el email existe ni detalles del bloqueo

### Requirement: Sanitización de errores y minimización transversal

El sistema SHALL sanitizar todo error del `api-client` (cuerpos `4xx`/`5xx`, validaciones `422`, timeouts) eliminando DNI, teléfono, historia clínica, hashes y tokens antes de mostrar, registrar o reportar, y SHALL truncar textos libres a un máximo visible; los formularios SHALL repoblarse con los datos ya ingresados tras un error recuperable (`409`/`422`/`429`/`5xx`).

#### Scenario: Error de validación no expone PII

- **WHEN** una respuesta `422` o un fallo de red ocurre con un formulario que contiene DNI y teléfono sintéticos
- **THEN** el mensaje visible es genérico en español con el campo afectado, y ni la consola, ni el reporte de error, ni los logs contienen DNI, teléfono, tokens ni hashes
