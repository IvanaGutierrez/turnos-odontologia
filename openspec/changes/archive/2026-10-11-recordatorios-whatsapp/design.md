# Design — C-06 `recordatorios-whatsapp`

## Context

Ver `proposal.md` (Why/What). Estado actual (solo lectura de `app/`): FastAPI con routers bajo `/api/v1`, sin ningún router `/webhooks`; Redis existe solo como `app.state.redis` para rate-limit/blacklist con degradación fail-open (`redis_client.py`) y `fakeredis` en tests (`conftest.py`, patrón C-02/C-03); no hay cola de envíos, ni cliente WhatsApp, ni tabla de avisos; el servicio `worker` de compose corre `python -m app.workers.ping` como placeholder. Restricciones: R0 sintético (números de prueba, jamás reales), R1 hints, R2 capas + Alembic, R3 GiST intacta (este change no toca agenda), R5 TDD con doble de WA y jamás red real, R6 crítico (plantillas mínimas, firma siempre, logs sin teléfonos), R7 secretos solo env, R8 Redis real prod / fakeredis tests.

## Goals / Non-Goals

**Goals:**

- Secuencia observable inmediata + 24 h + 3 h con plantillas utility configurables, encolada desde crear/confirmar y reagendada ante reprogramación/cancelación.
- Envío exactamente-una-vez observable por `(turno_id, tipo_aviso)` aunque el worker reintente o el proveedor duplique el webhook.
- Webhook que nunca procesa nada sin firma válida.
- Paciente sin WhatsApp igualmente avisado (email/SMS) y clínica operativa aunque WA caiga (manual + aviso a recepción, turno intacto).

**Non-Goals:**

- Interpretar mensajes entrantes para mutar agenda ("SÍ" conversacional → C-12; aquí el inbound solo se verifica, audita y responde con el link de gestión).
- Cobrar señas o acreditar pagos (C-08), marketing masivo (opt-in aparte), Google Calendar (v2).

## Decisions

1. **Transporte mockeable tras protocolo `WhatsAppTransport` (standard fastapi).** `HttpWhatsAppTransport` (prod, `httpx` con `WA_TIMEOUT_S`) vs `FakeWhatsAppTransport` (tests, cola en memoria con fallos programables: ok / 5xx / timeout). Servicios y workers solo conocen el protocolo; la inyección se resuelve por settings (`WA_TRANSPORT=fake` en tests). Jamás red real en tests (R5). Alternativa descartada: llamar a `httpx` directo en el servicio — imposible probar reintentos/backoff sin red.
2. **Reintentos con backoff exponencial + jitter y DLQ en Redis (standard job-queues).** Cola lista `wa:envios` + `wa:reintentos` (sorted-set por `not_before`) + `wa:muertos`. Política: `WA_MAX_REINTENTOS=5`, `backoff = WA_BACKOFF_BASE_S * 2^n + jitter`, solo reintenta errores transitorios (5xx/timeout/conexión); 4xx de Meta (plantilla inexistente, número inválido) van directo a `fallido` + fallback sin reintentar. Tras agotar: `fallido` + aviso a recepción + auditoría, turno intacto. Alternativa descartada: reintento infinito — satura la cola y retrasa los avisos de 3 h.
3. **Idempotencia en dos niveles: Redis + tabla `aviso_envio` (decisión R2: SÍ hay migración).** Nivel rápido: `SET aviso:{turno_id}:{tipo} NX EX` para deduplicar encolados concurrentes. Nivel durable: tabla `aviso_envio(turno_id, tipo_aviso UNIQUE, estado, intentos, proveedor_msg_id UNIQUE NULL, payload_hash, created_at, sent_at)`; el worker reclama con `UPDATE ... WHERE estado IN (pendiente, reintentar)` en transacción y guarda `proveedor_msg_id` para que un reintento del proveedor no duplique. Migración Alembic pequeña, anulable, sin tocar GiST. Alternativa descartada: solo Redis — se pierde ante reinicio del worker y no deja auditoría consultable.
4. **Webhook `POST /webhooks/whatsapp` con verificación doble y 401 ciego (standard fastapi + R6).** `GET` valida `hub.verify_token == WHATSAPP_VERIFY_TOKEN` (suscripción Meta). `POST` exige `X-Hub-Signature-256 = HMAC-SHA256(WHATSAPP_WEBHOOK_SECRET, body)` con `hmac.compare_digest`; ausente/inválida → `401` con cuerpo genérico, sin procesar, sin auditar contenido, sin distinguir causas. Cuerpo parseado con schemas Pydantic estrictos; solo se extraen `wa_message_id`, `remitente_hash`, `timestamp` y `tipo`; el texto libre jamás se loguea. Alternativa descartada: aceptar sin firma en dev — abre un vector que algún deploy olvida cerrar.
5. **Fallback en cascada + degradación graceful (RN-NO-04 + excepción global KB).** Orden: WhatsApp → email SMTP (`SMTP_URL`) → SMS gateway (`SMS_GATEWAY_KEY`) si el paciente no tiene WA (`sin_whatsapp=true` o 4xx número inválido) o WA cae tras reintentos. Cada rama registra `aviso_fallback(canal)` sin PII y, si todo canal automático falla, encola `aviso_a_recepcion` (visible en agenda del día) para gestión manual. El turno jamás muta por un fallo de notificación. Alternativa descartada: fallar silencioso — viola la regla "nunca se pierde el turno".
6. **Plantillas mínimas y logs hasheados (R6, Ley 25.326).** Variables permitidas: `{nombre_pila?, fecha, hora, sede, link_gestion}` — jamás DNI, teléfono, HC, motivo clínico ni token crudo. Logs y diffs de auditoría usan `sha256(e164)[:12]` y `token_hash_prefix` de 6 chars; sin cuerpos de request/response del proveedor en logs. Marketing fuera: el scheduler solo emite los 3 tipos utility; cualquier otro tipo → rechazado en servicio con `422`.
7. **Scheduler dirigido por eventos de dominio, ventanas configurables.** Al `reservado/confirmado`: encola `confirmacion` inmediata + programa `recordatorio_24h` (`inicio - RECORDATORIO_24H_MIN`, default 1440) + `aviso_3h` (`inicio - AVISO_3H_MIN`, default 180) solo si `inicio - ahora > ventana + margen`; ante `reprogramado`: cancela pendientes del turno y reprograma; ante `cancelado/ausente/atendido`: cancela pendientes (idempotente, sin error si no existen). Reloj inyectable para tests con freezegun en `America/Argentina/Buenos_Aires`.
8. **Testing (plan, se ejecuta en apply — R5, AAA, cov 80):** pytest sobre Postgres real + fakeredis (streams/listas soportadas) + `FakeWhatsAppTransport`; freezegun para las ventanas 24 h/3 h; casos: secuencia completa de 3 envíos en orden con `proveedor_msg_id` distintos; fallo 5xx → 5 reintentos con backoff sin duplicar (un solo `enviado`); firma inválida/ausente → 401 sin procesar ni auditar contenido; paciente `sin_whatsapp` → email/SMS y `aviso_fallback`; WA caído total → `fallido` + aviso a recepción con turno intacto; doble encolado concurrente → un solo envío. Toda fixture con números `+54 9 11 15-000-0000` sintéticos (R0).

## Risks / Trade-offs

- [Riesgo] Aprobación de plantillas Meta pendiente al deploy → Mitigación: nombres de plantilla por env (`WA_TEMPLATE_CONFIRM/24H/3H`) + modo `WA_DRY_RUN` que encola y audita sin llamar a Meta; fallback email/SMS cubre el piloto.
- [Riesgo] Costo por conversación / spam de reintentos → Mitigación: tope de 5 reintentos, DLQ, y programar solo si la ventana futura existe (no se encola el 24 h de un turno en 2 h).
- [Riesgo] Redis caído en prod → Mitigación: degradación fail-open documentada (los eventos se auditan como `aviso_encolado_pendiente_redis` y un job de reconciliación los re-encola al volver; la DB manda).
- [Riesgo] Duplicado del proveedor (mismo `wa_message_id` dos veces) → Mitigación: `proveedor_msg_id UNIQUE` + respuesta `200` idempotente en webhook.
- [Trade-off] Tabla `aviso_envio` vs solo Redis. Aceptada la tabla: costo de una migración pequeña a cambio de idempotencia durable y auditoría consultable por recepción.
