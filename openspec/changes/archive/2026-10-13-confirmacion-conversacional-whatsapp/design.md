# Design — C-12 `confirmacion-conversacional-whatsapp`

## Context

Ver `proposal.md` (Why/What). Estado actual verificado por solo-lectura de `app/`:

- Webhook C-06 (`routers/whatsapp_webhook.py`): `GET` verify con `hub.verify_token`, `POST` exige `X-Hub-Signature-256 = HMAC-SHA256(secret, body)` con `compare_digest` → `401` ciego sin procesar/mutar/auditar; con firma válida parsea `WebhookInbound` estricto (`wa_message_id`, `remitente_hash`, `timestamp`, `tipo`, `turno_id`), deduplica por `wa_message_id` contra `aviso_recibido` y audita sin loguear texto libre (R6).
- Núcleo reutilizable: `services/autogestion.py` (`CONFIRMABLE_DESDE={reservado}`, `CANCELABLE_DESDE={reservado,confirmado}`, `min_horas_cancelacion()` por env default 12, `SenaPendienteError` con `url_pago` sin mutar, 404 byte-idéntico anti-enumeración, `resolver_por_token` en una query); `services/agenda.py` (`REPROGRAMABLE_DESDE={reservado,confirmado}`, `reprogramar_turno` con pre-chequeo + GiST); scheduler C-06 (`services/avisos.py`: `tras_confirmar` / `tras_cancelar` / `tras_reprogramar`, veto marketing 422, `huella_destino = sha256(e164)[:12]`).
- Transporte testeable: protocolo `WhatsAppTransport` + `FakeWhatsAppTransport` (fallos programables), `RegistroFallback` email/SMS sin red; teléfono del paciente en E.164 AR (`schemas/validators_ar.py`).
- Restricciones: R0 sintético + Fake WA jamás red real; R1 hints; R2 capas + Alembic solo si hace falta (este diseño NO requiere migración); R3 N/A (no se toca el constraint, se delega en el núcleo); R5 TDD planificado aquí, ejecutado en apply; R6 crítico (desconocido jamás muta ni filtra); R7 env; R8 stack fijo.

## Goals / Non-Goals

**Goals:**

- "SÍ" por WhatsApp confirma el turno del remitente sin abrir la web, auditado con `canal=whatsapp`.
- Remitente desconocido o mensaje ambiguo jamás muta agenda ni filtra datos (link genérico + ayuda).
- Cancelación respeta antelación RN-AG-05 y responde la política del consultorio fuera de término.
- Seña pendiente (RN-PA-02) responde link MP sin confirmar.
- Cada cambio reagenda recordatorios 24 h / 3 h vía workers C-06.
- Firma inválida sigue `401` ciego (C-06 intacto); reintento Meta (`wa_message_id` duplicado) no duplica mutación ni respuesta.

**Non-Goals:**

- Cambiar la máquina de estados, el constraint GiST o las plantillas utility (se reutilizan).
- Marketing, cobro en chat, validación OS, lista de espera, audio/IA generativa.
- Migración Alembic (no hay estado durable nuevo).

## Decisions

1. **Matching de remitente por E.164 normalizado + hash, contra turnos vigentes del número (standard fastapi + R6).** Normalización determinística (solo dígitos, tolera `+54 9 11…` vs `11…` AR) y comparación contra `sha256` del teléfono de turnos candidatos en estado `reservado|confirmado` con inicio futuro, eligiendo el próximo (desempate: inicio más cercano). Sin candidato → respuesta genérica con link de gestión, sin mutar, sin revelar si el número existe (filosofía del 404 idéntico de C-05 llevada al chat). Alternativa descartada: exigir el token por chat — fricción que mata US-011; y matcheo difuso/fuzzy — filtra turnos ajenos.
2. **Parser de intents determinístico ES por reglas, normalizado (sin tildes, minúsculas, puntuación recortada).** Tabla: `confirmar` (`si`, `sí`, `confirmo`, `confirmar`, `ok`, `dale`, variantes con tildes/errores de tipeo acotados por lista explícita, NO distancia de edición abierta); `cancelar` (`cancelar`, `cancela`, `baja`, `no puedo ir`, `no voy`); `reprogramar` (`reprogramar`, `cambiar`, `mover`, `otro día/horario`). Prioridad ante solape: `cancelar` > `reprogramar` > `confirmar` (la acción destructiva exige la señal más explícita; ante duda → ayuda, nunca mutar). Solo texto + botones/interactivos de Meta mapeados al mismo vocabulario. Alternativa descartada: modelo ML/LLM — no determinístico, imposible de cubrir con TDD al 80 % y riesgo de PII a terceros.
3. **Estado conversacional SÍ, pero efímero en Redis con TTL — sin migración (decisión R2: NO hay Alembic).** `confirmar`/`cancelar` son single-shot stateless e idempotentes (repetir "SÍ" con turno ya `confirmado` → acuse idempotente, como `confirmar_por_token`). Solo `reprogramar` guarda oferta pendiente `wa:conv:{remitente_hash}` = `{turno_id, slots_iso, expira}` con `WA_CONV_TTL_MIN` (default 60) + `SET NX`; al elegir (número de opción o fecha/hora libre que resuelva a un slot ofertado) delega en `reprogramar_turno`; expirado → invita a reiniciar, sin mutar. Nada durable: el historial vive en `AuditoriaLog` existente. Alternativa descartada: tabla nueva — costo de migración para estado transitorio; y fully-stateless — obligaría a pegar tokens/slots por chat (fricción + PII).
4. **Delegación total en el núcleo C-04/C-05 (standard capas).** El handler conversacional resuelve el turno por remitente y llama a los mismos servicios (confirmar con guarda de seña, cancelar con antelación, reprogramar con GiST): mismos `409`/`422`, mismos eventos de auditoría con `canal=whatsapp` (`turno_confirmado|turno_cancelado|turno_reprogramado`), mismos diffs sanitizados sin PII. Ninguna regla de negocio se reimplementa en la capa conversacional. Alternativa descartada: lógica propia en el webhook — divergencia garantizada con C-05.
5. **Reagendado vía hooks C-06 existentes.** Post-confirmar → `tras_confirmar`; post-cancelar → `tras_cancelar`; post-reprogramar → `tras_reprogramar` (cancela pendientes del original + programa el nuevo). Ventanas `RECORDATORIO_24H_MIN` / `AVISO_3H_MIN` intactas; reloj inyectable (freezegun `America/Argentina/Buenos_Aires` en tests).
6. **Privacidad R6 en cada respuesta (Ley 25.326).** Respuestas con solo `{nombre_pila?, fecha, hora, sede}` + links; jamás DNI, teléfono ajeno, HC, motivo clínico ni token crudo. Remitente desconocido → link de gestión genérico (el mismo para todos, sin confirmar ni negar existencia). Logs/diffs solo con `remitente_hash` (`sha256[:12]`) y `wa_message_id`; el texto libre entrante jamás se loguea (extiende el contrato C-06). Rate-limit por remitente-hash (reusa esquema `INCR+EXPIRE` C-03/C-05) contra spam de "SÍ".
7. **Firma primero, enrutado después; idempotencia de respuesta (C-06 intacto).** El `POST` mantiene el orden: verificar firma → `401` ciego si falla (sin tocar nada) → dedupe por `wa_message_id` → parsear intent → ejecutar. La respuesta saliente se registra con el `wa_message_id` (extensión de `aviso_recibido` con `respuesta` hasheada por tipo, sin texto libre) para que un reintento Meta devuelva `200` sin re-mutar ni re-responder. Degradación: si WA saliente cae, el turno ya mutado manda (auditoría lo refleja) y se encola `aviso_a_recepcion`; si cae la DB, `5xx` sin acuse falso.
8. **Testing (plan, se ejecuta en apply — R5, AAA, cov 80).** Pytest sobre Postgres real + fakeredis + `FakeWhatsAppTransport` + freezegun; teléfonos sintéticos `+54 9 11 15-000-XXXX` (R0). Casos: SÍ válido → `confirmado` + auditoría `canal=whatsapp`; SÍ desconocido → `200` con link, cero mutaciones (cuenta de turnos intacta); CANCELAR en término → `cancelado`; tardía → rechazo con política; REPROGRAMAR → propone slots y elige uno válido (token conservado, original `reprogramado`); seña pendiente → link MP sin confirmar; cambio reagenda 24 h/3 h; ambiguo → ayuda sin mutar; firma inválida/ausente → `401` sin procesar (regresión C-06); `wa_message_id` duplicado → sin doble mutación/respuesta.

## Risks / Trade-offs

- [Riesgo] Variantes de escritura no cubiertas ("sip", "confirmadísimo") → Mitigación: lista explícita versionada por env/código + fallback a ayuda sin mutar; métrica `conv_ambiguo` en auditoría para ampliar vocabulario con datos reales anonimizados.
- [Riesgo] Dos turnos futuros del mismo remitente (¿cuál confirma "SÍ"?) → Mitigación: el próximo por inicio + respuesta que nombra fecha/hora/sede para desambiguar; si hay dos el mismo día, se pide elegir sin mutar.
- [Riesgo] Redis caído pierde ofertas `wa:conv:*` → Mitigación: TTL corto + reconstrucción trivial (el paciente reenvía REPROGRAMAR); la DB manda, ningún turno muta por ello.
- [Trade-off] Reglas determinísticas vs NLU. Aceptadas las reglas: auditable, testeable al 80 %, sin PII a terceros; el vocabulario crece por datos, no por modelo.
