# agenda/autogestion-paciente Specification

## Purpose
Permite que el paciente autogestione su turno con el token público sin llamar ni crear cuenta: verlo, confirmarlo, cancelarlo dentro de la antelación y reprogramarlo sobre slots reales, con minimización de datos personales y sin revelar la existencia de turnos ajenos.

## Requirements

### Requirement: Ver turno propio con token y campos mínimos

El sistema SHALL exponer `GET /api/v1/turnos/publicos/:token` sin JWT que devuelve el turno propio con solo los campos necesarios (`estado, inicio, fin, prestacion_nombre, profesional_nombre, sede, puede_cancelar_en_termino, horas_limite` y `url_pago` solo si hay seña pendiente), y SHALL responder `404` con cuerpo idéntico ante cualquier token desconocido o inválido, sin distinguir casos ni exponer PII (R6, Ley 25.326).

#### Scenario: Ver turno con token válido y campos mínimos

- **WHEN** se pide `GET /api/v1/turnos/publicos/:token` con el token de un turno `reservado` vigente
- **THEN** responde `200` con `estado, inicio, fin`, nombres de prestación/profesional/sede e indicador de cancelación en término, y el cuerpo no contiene DNI, teléfono, historia clínica, hashes ni el propio token

#### Scenario: Token inválido → 404 idéntico sin filtrar datos

- **WHEN** se pide `GET /api/v1/turnos/publicos/:token` con un token inexistente, malformado o rotado, y se compara con el `404` de un token nunca emitido
- **THEN** ambas respuestas son `404` con cuerpo byte-idéntico (`problema=pedido_invalido`-genérico, sin indicar si el token existió), sin DNI, teléfono ni horarios en cuerpo ni logs

### Requirement: Confirmar turno con token

El sistema SHALL exponer `POST /api/v1/turnos/publicos/:token/confirmar` sin JWT que transiciona `reservado→confirmado` y registra `turno_confirmado` sin PII; SHALL responder `200` idempotente si ya está `confirmado` (sin duplicar auditoría); SHALL responder `422` con `url_pago` si la prestación exige seña pendiente (RN-PA-02, el cobro es C-08); y SHALL responder `422` ante estados terminales y `404` idéntico ante token inválido.

#### Scenario: Confirmar reservado → confirmado + auditado

- **WHEN** se envía `POST /api/v1/turnos/publicos/:token/confirmar` sobre un turno `reservado` sin seña requerida
- **THEN** responde `200` con `estado=confirmado` y `AuditoriaLog` contiene `turno_confirmado` con turno y hora, sin DNI ni teléfono en el `diff`

#### Scenario: Confirmar duplicado → idempotente sin duplicar auditoría

- **WHEN** se envía dos veces `POST /api/v1/turnos/publicos/:token/confirmar` sobre el mismo turno (incluso concurrente)
- **THEN** ambas responden `200` con `estado=confirmado`, existe una sola auditoría `turno_confirmado` y el estado final es `confirmado`

#### Scenario: Confirmar con seña pendiente → 422 con link de pago

- **WHEN** se confirma un turno cuya prestación tiene `requiere_sena=true` sin pago acreditado
- **THEN** responde `422` con `problema=sena_pendiente` y `url_pago` no vacía, y el estado sigue `reservado`

### Requirement: Cancelar turno con antelación mínima

El sistema SHALL exponer `POST /api/v1/turnos/publicos/:token/cancelar` sin JWT que transiciona `reservado|confirmado→cancelado` (registrando `motivo_cancelacion?`, `cancelado_at` y `turno_cancelado` sin PII) solo si `inicio - ahora >= CANCEL_MIN_HOURS` (default 12 h, env); SHALL responder `422` con la política del consultorio fuera de término; SHALL responder `200` idempotente si ya está `cancelado`; y SHALL liberar el slot (el turno `cancelado` entra en `ESTADOS_INACTIVOS` del predicado GiST).

#### Scenario: Cancelar en término → cancelado + slot liberado

- **WHEN** se envía `POST /api/v1/turnos/publicos/:token/cancelar` con `inicio` a más de `CANCEL_MIN_HOURS` de `ahora` (reloj controlado en test)
- **THEN** responde `200` con `estado=cancelado`, audita `turno_cancelado` sin PII, y un turno nuevo puede crearse en ese mismo rango/profesional/sillón (`201`)

#### Scenario: Cancelar fuera de término → 422 con política

- **WHEN** se envía `POST /api/v1/turnos/publicos/:token/cancelar` con `inicio` a menos de `CANCEL_MIN_HOURS` de `ahora`
- **THEN** responde `422` con `problema=fuera_de_termino`, las horas restantes y el texto de `CANCEL_POLICY_TEXT`, y el estado no cambia

#### Scenario: Cancelar duplicado → idempotente

- **WHEN** se cancela dos veces el mismo token ya `cancelado`
- **THEN** ambas responden `200` con `estado=cancelado` sin duplicar auditoría ni mutar el slot

### Requirement: Reprogramar con token sobre slots reales

El sistema SHALL exponer `POST /api/v1/turnos/publicos/:token/reprogramar {nuevo_inicio}` sin JWT que reutiliza la validación de slots y el enlace de C-04 (RN-AG-07): ante destino libre marca el original `reprogramado` y crea el turno nuevo con idéntico `token_publico` y `reprogramado_de_id`, registrando `turno_reprogramado` sin PII; ante destino ocupado SHALL responder `409` con `problema` + `slots_alternativos` del mismo shape que `agenda/crear-turno` sin mutar nada; solo acepta origen `reservado|confirmado`.

#### Scenario: Reprogramar a slot libre conserva token + original reprogramado

- **WHEN** se envía `POST /api/v1/turnos/publicos/:token/reprogramar {nuevo_inicio}` libre de igual prestación
- **THEN** responde `200|201` con el turno nuevo con idéntico `token_publico`, el original queda `reprogramado` con enlace, y la auditoría muestra `turno_reprogramado` sin PII

#### Scenario: Reprogramar a ocupado → 409 sin mutar

- **WHEN** se reprograma hacia un rango superpuesto con otro turno activo del mismo profesional o sillón
- **THEN** responde `409` con `problema=profesional_ocupado|sillon_ocupado` y `slots_alternativos` no vacío de igual duración, el original conserva su estado y no se crea ningún turno nuevo

### Requirement: Rotación de token por staff ante sospecha de fuga

El sistema SHALL exponer `POST /api/v1/turnos/<id>/rotar-token` solo para roles con permiso `turnos` (JWT + `403` + `acceso_denegado` sin permiso) que genera un `token_publico` nuevo, invalida el anterior (el viejo responde `404` idéntico en todos los endpoints públicos) y registra `token_rotado` sin PII; los endpoints públicos SHALL jamás rotar el token por sí solos.

#### Scenario: Rotación invalida el token anterior

- **WHEN** staff con permiso rota el token de un turno y luego se usa el token viejo en `GET /api/v1/turnos/publicos/:token` y el nuevo
- **THEN** el viejo responde `404` idéntico al de un token nunca emitido, el nuevo responde `200`, y la auditoría contiene `token_rotado` sin PII

### Requirement: Máquina de estados consolidada con presente canónico

El sistema SHALL implementar la máquina completa `reservado→confirmado→presente→atendido`, `reservado|confirmado→cancelado`, `reservado|confirmado→reprogramado` (vía enlace), `reservado|confirmado→ausente` (solo staff); los terminales (`cancelado|ausente|atendido|reprogramado`) no admiten más transiciones; el valor `en_sala` SHALL dejar de existir (migración 005 lo convierte a `presente`); y toda transición inválida por token o por staff SHALL responder `422` sin mutar nada.

#### Scenario: Transición inválida por token → 422

- **WHEN** se intenta confirmar un turno `atendido` o cancelar uno `presente` por token, o staff intenta `atender` un `reservado`
- **THEN** responde `422` con mensaje genérico y el estado no cambia

#### Scenario: En_sala consolidado a presente

- **WHEN** se leen turnos históricos que estaban en `en_sala` tras la migración 005
- **THEN** todos exponen `estado=presente`, el check de estados rechaza `en_sala` y el check-in sigue escribiendo `presente`

### Requirement: Rate limit y auditoría en endpoints públicos por token

El sistema SHALL aplicar rate limit por IP a los cuatro endpoints públicos por token (mismo esquema Redis que `agenda/reserva-publica`, `429` con `Retry-After` sin procesar) y SHALL auditar `turno_confirmado`, `turno_cancelado`, `turno_reprogramado` (con `usuario_id=NULL`, `canal=online`, IP y hora) sin DNI, teléfono, historia clínica, hashes ni tokens en `diff`, cuerpos ni logs.

#### Scenario: Rate limit público → 429 sin procesar

- **WHEN** se supera el tope configurable de consultas por token desde la misma IP
- **THEN** responde `429` con `Retry-After`, no muta ningún turno y no revela si el token existe
