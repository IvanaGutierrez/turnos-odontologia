# Spec Delta — `clinica/ficha-odontograma-presupuesto`

## Purpose

Permite al odontólogo registrar ficha/HCE, odontograma FDI y presupuestos/planes en una sesión (US-020, Flujo 3) — solo con consentimiento informado (Ley 26.529), con firmante en cada edición, catálogo de estados versionado, firma del paciente antes de planes con seña, HCE cifrada en reposo y exportación garantizada (Ley 25.326) — con recepción limitada a contacto/lectura.

## ADDED Requirements

### Requirement: Creación de HCE gated por consentimiento informado

El sistema SHALL exigir `paciente.consentimiento_hc = true` (con fecha) para crear cualquier HCE; SHALL responder `422` con mensaje de política (sin crear ficha, odontograma ni evolución) cuando falte; y SHALL crear la ficha con `201` + `firmante_usuario_id` (= odontólogo JWT) + snapshot `consentimiento_en` cuando exista.

#### Scenario: Crear HCE sin consentimiento → 422

- **WHEN** `POST /api/v1/fichas` con un paciente sin `consentimiento_hc`
- **THEN** responde `422`, no crea ninguna fila clínica y el error no expone datos del paciente

#### Scenario: Crear HCE con consentimiento → 201 + firmante

- **WHEN** `POST /api/v1/fichas` con un paciente con `consentimiento_hc` registrado, autenticado como odontólogo
- **THEN** responde `201`, la ficha guarda `firmante_usuario_id` del odontólogo y la auditoría contiene `ficha_creada` sin contenido clínico

### Requirement: RBAC clínico — recepción no edita datos clínicos

El sistema SHALL denegar con `403` genérico + auditoría `acceso_clinico_denegado` cualquier escritura clínica (ficha, odontograma, evolución, firma profesional) con rol recepción; SHALL permitir a recepción editar solo contacto (nombre/teléfono/email) con `200`; y SHALL permitir a odontólogo CRUD clínico sobre sus pacientes (admin: lectura de auditoría).

#### Scenario: Recepción edita clínica → 403 + log

- **WHEN** un JWT con rol recepción hace `PATCH /api/v1/fichas/:id` o `POST …/odontograma`
- **THEN** responde `403` genérico, no muta nada clínico y audita `acceso_clinico_denegado` sin PII

#### Scenario: Recepción edita contacto → 200

- **WHEN** un JWT con rol recepción actualiza teléfono o email del paciente por el canal de pacientes
- **THEN** responde `200` con el contacto actualizado y la HCE permanece intacta

#### Scenario: Odontólogo edita clínica → 200 + auditoría con firmante

- **WHEN** el odontólogo tratante edita anamnesis o agrega evolución
- **THEN** responde `200`, registra `firmante_usuario_id + firmado_en` y audita `ficha_editada|evolucion_agregada` con solo IDs/campos/rol, sin contenido clínico en el diff

### Requirement: Odontograma batch por pieza con FDI 11–48 y catálogo versionado

El sistema SHALL exponer `POST /api/v1/fichas/:id/odontograma` con batch `[{pieza_fdi, estado_codigo, cara?}]` en upsert por `(ficha_id, pieza_fdi, cara)`; SHALL validar `pieza_fdi` FDI real (11–18, 21–28, 31–38, 41–48) con `422` ante pieza fuera de rango; SHALL validar `estado_codigo` contra `catalogo_odontograma_estado(version)` vigente con `422` ante código inexistente; y SHALL versionar cada entry (`estado_codigo + catalogo_version`) para preservar historia.

#### Scenario: Batch odontograma válido por pieza

- **WHEN** se envía un batch con piezas 11, 16, 36 y estados del catálogo vigente
- **THEN** responde `200/201` con las entries creadas/actualizadas y auditoría `odontograma_actualizado` con piezas y códigos, sin narrativa clínica

#### Scenario: Pieza fuera de 11–48 → 422

- **WHEN** el batch incluye pieza `19`, `49` u `00`
- **THEN** responde `422`, no persiste ninguna entry del batch (atomicidad) y el error no expone HC

#### Scenario: Estado fuera de catálogo → 422

- **WHEN** el batch incluye `estado_codigo` inexistente en la versión vigente del catálogo
- **THEN** responde `422` sin persistir y sugiere los códigos válidos (solo códigos, sin datos del paciente)

### Requirement: Presupuesto nacido de hallazgos con firma del paciente

El sistema SHALL generar items desde `desde_hallazgos: [{pieza_fdi, estado_codigo, prestacion_id}]` con total calculado en servicio; SHALL exigir `firma_paciente` (registro firma+fecha vía `POST /api/v1/presupuestos/:id/firma`) para `borrador→aprobado`, con `422` si falta; y SHALL exigir firma previa para cualquier plan con `sena_requerida > 0` (RN-CL-03).

#### Scenario: Presupuesto nace de hallazgos del odontograma

- **WHEN** `POST /api/v1/presupuestos` con hallazgos de piezas/códigos y prestaciones
- **THEN** responde `201` en `borrador` con items por pieza/prestación, cantidades y total correcto, sin narrativa clínica en la respuesta

#### Scenario: Plan con seña exige firma del paciente

- **WHEN** se intenta aprobar un presupuesto (o plan con `sena_requerida > 0`) sin `firma_paciente`
- **THEN** responde `422` con la política RN-CL-03 y el presupuesto sigue en `borrador`; con firma registrada → `aprobado`

### Requirement: Máquina de estados del presupuesto con transiciones válidas

El sistema SHALL aplicar `borrador→aprobado` (con firma) `→pagado_parcial|pagado` (solo vía acreditación C-08), `borrador→rechazado` (terminal, con motivo); y SHALL rechazar con `422` cualquier otra transición (p. ej. `borrador→pagado` directa o salidas desde `rechazado`).

#### Scenario: Transiciones válidas borrador→aprobado→pagado

- **WHEN** un presupuesto `borrador` se firma y aprueba, y luego C-08 acredita el pago
- **THEN** transita `borrador→aprobado→pagado(_parcial)` con auditoría `presupuesto_aprobado|presupuesto_pagado` en cada paso

#### Scenario: Transición inválida → 422

- **WHEN** se intenta `borrador→pagado` directo o cualquier movimiento desde `rechazado`
- **THEN** responde `422` y el estado permanece inalterado

### Requirement: Cifrado en reposo y minimización total de HCE

El sistema SHALL persistir anamnesis/evolución solo cifradas (AES-256-GCM app-level, `HCE_CIFRADO_KEY` por env, `clave_id` por fila); SHALL garantizar que ningún log, error, diff de auditoría ni response contenga anamnesis/HC/DNI/teléfonos en claro; y SHALL descifrar solo para titular y rol clínico autorizado.

#### Scenario: Anamnesis jamás en logs ni errores

- **WHEN** cualquier operación clínica genera logs, errores `422/403` o diffs de auditoría
- **THEN** ningún artefacto observable contiene texto de anamnesis/HC/DNI/teléfono (verificado por grep de suite), y los errores son genéricos minimizados

### Requirement: Exportación de datos del paciente

El sistema SHALL exponer `GET /api/v1/pacientes/:id/exportacion` que entrega `{datos_contacto, consentimientos, ficha, odontograma, evoluciones, presupuestos, turnos}`; SHALL restringirlo al titular o rol clínico/admin con auditoría `datos_exportados`; y SHALL aplicar rate-limit y minimización por rol (anamnesis descifrada solo titular/odontólogo tratante).

#### Scenario: Exportación completa del paciente

- **WHEN** el titular (o rol autorizado) pide `GET /api/v1/pacientes/:id/exportacion`
- **THEN** responde `200` con todas las secciones, audita `datos_exportados` sin PII en el diff y un rol no autorizado recibe `403`
