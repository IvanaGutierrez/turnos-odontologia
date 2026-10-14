# notificaciones/recordatorios-whatsapp Specification

## Purpose
Permite que la clínica confirme y recuerde turnos por WhatsApp sin trabajo manual — confirmación inmediata + recordatorio 24 h + aviso 3 h con plantillas utility — con reintentos idempotentes, webhook verificado por firma, fallback email/SMS y degradación a flujo manual sin perder jamás el turno.

## Requirements

### Requirement: Secuencia de confirmación + recordatorios con plantillas utility configurables

El sistema SHALL, ante turno `reservado` o `confirmado`, encolar `confirmacion` inmediata y programar `recordatorio_24h` (`inicio - RECORDATORIO_24H_MIN`, default 1440) y `aviso_3h` (`inicio - AVISO_3H_MIN`, default 180) solo si la ventana futura existe; SHALL enviar solo plantillas utility aprobadas cuyos nombres viajan por env (`WA_TEMPLATE_CONFIRM/24H/3H`) con variables mínimas `{nombre_pila?, fecha, hora, sede, link_gestion}` (jamás DNI, teléfono, HC, motivo clínico ni token crudo, R6, RN-NO-01/02); y SHALL reagendar ante `reprogramado` y cancelar pendientes ante `cancelado|ausente|atendido` de forma idempotente.

#### Scenario: Turno confirmado encola confirmación inmediata

- **WHEN** se crea o confirma un turno `reservado→confirmado` con inicio a más de 24 h
- **THEN** se encola `confirmacion` inmediata con la plantilla `WA_TEMPLATE_CONFIRM` y se programan `recordatorio_24h` y `aviso_3h`, y la auditoría contiene `aviso_encolado` por cada tipo sin PII

#### Scenario: Secuencia completa de 3 envíos en orden

- **WHEN** un turno `confirmado` atraviesa sus tres ventanas con el transporte sano (reloj controlado en test)
- **THEN** se observan `confirmacion`, `recordatorio_24h` y `aviso_3h` en ese orden, cada uno con `proveedor_msg_id` distinto y estado `enviado`

#### Scenario: Turno a 24 h recibe recordatorio y turno a 3 h recibe aviso

- **WHEN** un turno tiene `inicio - ahora ≈ 24 h` (respectivamente `≈ 3 h`)
- **THEN** el worker emite `recordatorio_24h` (respectivamente `aviso_3h`) con fecha, hora, sede y link de gestión, sin PII excedente

### Requirement: Cola Redis con reintentos e idempotencia por turno y tipo

El sistema SHALL procesar los avisos desde la cola `wa:envios` con reintentos de hasta `WA_MAX_REINTENTOS=5` con backoff exponencial + jitter solo ante errores transitorios (5xx/timeout/conexión; los 4xx van directo a `fallido`); SHALL garantizar idempotencia observable por `(turno_id, tipo_aviso)` (deduplicación `SET NX` + UNIQUE durable en `aviso_envio` + `proveedor_msg_id UNIQUE` ante duplicados del proveedor); y SHALL registrar `aviso_enviado|aviso_fallido` con solo IDs/estados/horas y `sha256(tel)[:12]` (R6).

#### Scenario: Reintento tras fallo no duplica el envío

- **WHEN** el transporte falla con 5xx dos veces y luego responde ok para el mismo `(turno_id, tipo_aviso)`, o el mismo aviso se encola dos veces en concurrente
- **THEN** existe un único envío observable (`enviado` una vez, `intentos=3`), sin duplicar el mensaje al paciente ni la auditoría de envío

### Requirement: Webhook con verificación de firma siempre

El sistema SHALL exponer `POST /webhooks/whatsapp` (más `GET` de verificación con `hub.verify_token`) que exige `X-Hub-Signature-256 = HMAC-SHA256(WHATSAPP_WEBHOOK_SECRET, body)` comparado con `compare_digest`; SHALL responder `401` con cuerpo genérico ante firma ausente, inválida o cuerpo alterado, sin procesar, sin mutar agenda, sin auditar contenido y sin loguear PII; SHALL responder `200` idempotente ante `wa_message_id` duplicado (sin re-mutar ni re-responder); y SHALL, solo con firma válida y mensaje no duplicado, enrutar al handler conversacional (`notificaciones/confirmacion-conversacional`), registrando la respuesta junto a `aviso_recibido` sin texto libre.

#### Scenario: Firma webhook inválida → 401 sin procesar

- **WHEN** llega `POST /webhooks/whatsapp` sin firma, con firma incorrecta o con cuerpo alterado tras firmar
- **THEN** responde `401` genérico, no muta ningún turno, no crea ningún aviso ni conversación, y ningún log contiene teléfonos, textos libres ni tokens

#### Scenario: Mensaje verificado se enruta al bot sin doble proceso

- **WHEN** llega `POST /webhooks/whatsapp` con firma válida y `wa_message_id` nuevo con texto "SÍ"
- **THEN** responde `200`, el handler conversacional procesa el intent una sola vez observable, y un reintento Meta con el mismo `wa_message_id` devuelve `200` sin re-mutar ni re-responder

### Requirement: Fallback email/SMS y degradación graceful sin perder el turno

El sistema SHALL, cuando el paciente no tiene WhatsApp (`sin_whatsapp=true` o 4xx número inválido) o WA agota sus reintentos, enviar por la cascada email/SMTP → SMS gateway (RN-NO-04) registrando `aviso_fallback(canal)` sin PII; y SHALL, si todo canal automático falla, encolar `aviso_a_recepcion` para gestión manual con el turno intacto en su estado (excepción global KB: el fallo externo degrada a manual, nunca pierde el turno).

#### Scenario: Paciente sin WhatsApp recibe email/SMS

- **WHEN** un turno `confirmado` pertenece a un paciente con `sin_whatsapp=true`
- **THEN** no se llama a Meta, se emite fallback por email y/o SMS con los mismos datos mínimos, y la auditoría contiene `aviso_fallback` sin PII

#### Scenario: WhatsApp caído → fallback + aviso a recepción, turno intacto

- **WHEN** el transporte WA falla de forma total (5xx/timeout en los 5 reintentos) para un turno `confirmado`
- **THEN** el aviso queda `fallido`, se registra `aviso_fallback` y `aviso_a_recepcion`, recepción ve el pendiente en la agenda del día, y el turno conserva `estado=confirmado` con su slot intacto

### Requirement: Configuración, privacidad y observabilidad de los avisos

El sistema SHALL leer toda configuración y secreto por env (`WHATSAPP_TOKEN/PHONE_ID/VERIFY_TOKEN/WEBHOOK_SECRET`, `WA_TEMPLATE_*`, `RECORDATORIO_24H_MIN`, `AVISO_3H_MIN`, `WA_TIMEOUT_S`, `WA_MAX_REINTENTOS`, `WA_BACKOFF_BASE_S`, `SMTP_URL`, `SMS_GATEWAY_KEY`; R7, jamás hardcodeados); SHALL rechazar con `422` cualquier tipo fuera de `confirmacion|recordatorio_24h|aviso_3h` (marketing exige opt-in aparte, RN-NO-01); y SHALL exponer el estado de cada aviso (`pendiente|enviando|enviado|reintentar|fallido|fallback|cancelado`, intentos, horas) consultable por `turno_id` para recepción, sin PII en cuerpos, diffs ni logs (R6, Ley 25.326).

#### Scenario: Tipo marketing fuera de scope → rechazado

- **WHEN** se intenta encolar un aviso de tipo `promocion` o cualquier otro fuera de los 3 utility
- **THEN** el servicio lo rechaza sin encolar ni llamar al proveedor, y la auditoría no registra ningún envío

### Requirement: Tipo utility oferta de lista de espera y blast top-N

El sistema SHALL admitir el tipo utility `oferta_lista_espera` (plantilla `WA_TEMPLATE_OFERTA`, variables R6: `nombre_pila?, fecha, hora, sede, link_gestion/seña` — jamás datos de otros en espera) junto a los 3 existentes, manteniendo el veto marketing (cualquier otro tipo → `422`); y SHALL enviar el blast del hueco al top-N rankeado con idempotencia por oferta (una oferta = un envío; reintentos y fallback email/SMS reusean la cascada C-06 con `destino_hash`, sin llamar a Meta en `WA_DRY_RUN`).

#### Scenario: Blast de oferta con plantilla y variables mínimas

- **WHEN** el worker oferta un hueco al top-N
- **THEN** cada ofertado recibe UN mensaje `oferta_lista_espera` con solo su slot (fecha, hora, sede, link de seña) y `destino_hash` en el registro

#### Scenario: Veto marketing intacto con el tipo nuevo

- **WHEN** se intenta encolar cualquier tipo fuera de los 4 utility (3 existentes + oferta)
- **THEN** se rechaza con `422` sin encolar ni llamar al proveedor

#### Scenario: Fallo de WA en blast degrada a recepción sin perder el hueco

- **WHEN** el transporte WA falla o el paciente no tiene WhatsApp durante el blast
- **THEN** aplica la cascada fallback + `aviso_a_recepcion` existentes, la oferta queda registrada igual (el TTL corre) y el hueco sigue libre
