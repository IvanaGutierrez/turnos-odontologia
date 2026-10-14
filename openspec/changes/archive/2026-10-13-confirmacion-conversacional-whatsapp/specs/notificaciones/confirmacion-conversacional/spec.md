# Spec Delta — `notificaciones/confirmacion-conversacional`

## Purpose

Permite que el paciente confirme, cancele o reprograme su turno con un mensaje de WhatsApp ("SÍ") 24/7 sin abrir la web — con matching estricto de remitente, intents determinísticos ES, respeto de antelación y seña, y reagendado automático de recordatorios — sin mutar jamás ante remitente desconocido o mensaje ambiguo y sin exponer PII.

## ADDED Requirements

### Requirement: Writeback "SÍ" solo con remitente coincidente

El sistema SHALL, ante un mensaje entrante verificado, normalizar el remitente a E.164 y confirmar el turno SOLO si coincide con el teléfono del turno candidato (`reservado`, sin seña pendiente o con seña acreditada, inicio futuro; desempate: inicio más cercano); SHALL responder con acuse idempotente ante "SÍ" repetido sobre turno ya `confirmado`; y SHALL, ante remitente sin candidato, responder el link de gestión genérico sin mutar turnos ni avisos y sin revelar si el número existe (R6, RN-NO-03).

#### Scenario: "SÍ" de remitente válido confirma y audita

- **WHEN** llega "SÍ" verificado del teléfono del turno `reservado` sin seña pendiente
- **THEN** el turno pasa a `confirmado`, la auditoría contiene `turno_confirmado` con `canal=whatsapp` sin PII, y el paciente recibe acuse con fecha, hora y sede

#### Scenario: "SÍ" de remitente desconocido responde link sin mutar

- **WHEN** llega "SÍ" verificado de un número sin turnos vigentes asociados
- **THEN** responde `200` con el link de gestión genérico, ningún turno ni aviso muta, y ningún log ni respuesta contiene DNI, teléfonos, HC ni tokens

#### Scenario: "SÍ" repetido es idempotente

- **WHEN** llega "SÍ" verificado dos veces (o con `wa_message_id` duplicado) para un turno ya `confirmado`
- **THEN** el estado sigue `confirmado`, no se re-audita la mutación ni se re-responde más de una vez observable

### Requirement: Intents confirmar / cancelar / reprogramar en español determinístico

El sistema SHALL interpretar texto libre ES normalizado (sin tildes, minúsculas) según tabla versionada con prioridad `cancelar > reprogramar > confirmar` (más interactivos/botones Meta mapeados al mismo vocabulario); SHALL ejecutar `cancelar` solo en término (`CANCEL_MIN_HOURS`, default 12 h, RN-AG-05) rechazando fuera de término con la política del consultorio y el turno intacto; y SHALL responder ayuda sin mutar ante mensajes ambiguos o estados terminales.

#### Scenario: "CANCELAR" en término cancela y apaga recordatorios

- **WHEN** llega "CANCELAR" verificado del remitente del turno `confirmado` con inicio a más de `CANCEL_MIN_HOURS`
- **THEN** el turno pasa a `cancelado` auditado con `canal=whatsapp` y los pendientes 24 h / 3 h quedan `cancelado` idempotentemente

#### Scenario: Cancelación tardía rechazada por chat

- **WHEN** llega "CANCELAR" verificado dentro de la ventana mínima de antelación
- **THEN** responde el rechazo con la política del consultorio, el turno conserva su estado y slot, y la auditoría refleja el intento sin PII

#### Scenario: Mensaje ambiguo responde ayuda sin mutar

- **WHEN** llega texto no clasificable ("hola", "gracias") o un intent sobre un turno en estado terminal
- **THEN** responde ayuda con las opciones válidas y ningún turno ni aviso muta

### Requirement: Reprogramación conversacional en dos pasos con slots reales

El sistema SHALL, ante intent `reprogramar` de remitente válido sobre turno `reservado|confirmado`, proponer slots reales (disponibilidad C-03) con opciones numeradas y guardar la oferta efímera `wa:conv:{remitente_hash}` con TTL (`WA_CONV_TTL_MIN`); SHALL, ante la elección de una opción vigente, delegar en el núcleo C-04 (pre-chequeo + GiST: `409` conversacional con alternativos ante colisión, token conservado, original `reprogramado`); y SHALL, ante oferta expirada, invitar a reiniciar sin mutar.

#### Scenario: "REPROGRAMAR" propone slots y confirma la elección

- **WHEN** llega "REPROGRAMAR" verificado del remitente del turno y luego elige una opción ofertada vigente
- **THEN** se crea el turno nuevo con el mismo token, el original pasa a `reprogramado` auditado, y los recordatorios se reprograman sobre el nuevo

#### Scenario: Oferta expirada no muta

- **WHEN** la elección llega tras expirar `WA_CONV_TTL_MIN`
- **THEN** responde invitación a reiniciar con slots frescos y ningún turno muta

### Requirement: Seña pendiente responde link MP sin confirmar

El sistema SHALL, cuando el turno candidato exige seña (RN-PA-01) sin pago `acreditado` (RN-PA-02, verificado C-08), responder el link de pago ante "SÍ" sin mutar el estado; y SHALL confirmar normalmente una vez acreditada la seña.

#### Scenario: Seña pendiente devuelve link MP por chat

- **WHEN** llega "SÍ" verificado para un turno `reservado` con seña requerida pendiente
- **THEN** responde el link de pago, el turno sigue `reservado`, y no se crea ningún `Pago` desde el chat

### Requirement: Reagendado de recordatorios y respuestas sin PII bajo rate-limit

El sistema SHALL, tras cada cambio conversacional, invocar el scheduler C-06 (`tras_confirmar` / `tras_cancelar` / `tras_reprogramar`) con las ventanas configuradas intactas; SHALL componer respuestas solo con `{nombre_pila?, fecha, hora, sede, link_gestion}` (jamás DNI, teléfono, HC, motivo clínico ni token crudo, R6); SHALL loguear/difundir solo `remitente_hash` (`sha256[:12]`) y `wa_message_id`, jamás texto libre; y SHALL aplicar rate-limit por remitente-hash ante ráfagas.

#### Scenario: Cambio conversacional reagenda recordatorios

- **WHEN** un turno se confirma o reprograma por chat con inicio a más de 24 h
- **THEN** `aviso_envio` contiene la secuencia reprogramada (`confirmacion` + `recordatorio_24h` + `aviso_3h` según ventanas) y la cancelación deja pendientes en `cancelado`
