# Tasks — C-12 `confirmacion-conversacional-whatsapp`

> Governance ALTO — fase PROPOSE: este archivo es el plan. Ninguna tarea se ejecuta sin aprobación explícita del usuario (`apply`). Orden TDD estricto: RED → GREEN → TRIANGULATE → REFACTOR. Todo dato sintético con prefijo `+54 9 11 15-000-XXXX` (R0); type hints siempre (R1); capas (`services/` conversacional separado de `models/`/`schemas/`/`repositories/`, webhook extendido, sin migración) (R2); GiST intacta por delegación al núcleo (R3 N/A); cada comportamiento con test en verde (R5, `FakeWhatsAppTransport`, jamás red real); desconocido jamás muta ni filtra + sin DNI/tokens en respuestas/logs (R6); secretos solo env (R7); Redis real prod + fakeredis tests, stack fijo (R8).

## 1. Tests en ROJO primero (TDD — antes de cualquier código de producción)

- [x] 1.1 Escribir `tests/integration/test_wa_conv_confirmar.py` ("SÍ"/"si"/"confirmo" de remitente válido con turno `reservado` sin seña → `confirmado` + auditoría `turno_confirmado` con `canal=whatsapp`; repetir "SÍ" → acuse idempotente sin re-auditar; freezegun `America/Argentina/Buenos_Aires`) y verificar que FALLA en rojo.
- [x] 1.2 Escribir `tests/integration/test_wa_conv_remitente.py` ("SÍ" de remitente desconocido → `200` con link de gestión genérico, cero mutaciones en turnos/avisos, cero PII en respuesta/logs; dos turnos futuros mismo día → pide elegir sin mutar) y verificar que FALLA en rojo.
- [x] 1.3 Escribir `tests/integration/test_wa_conv_cancelar.py` ("CANCELAR" en término → `cancelado` + pendientes C-06 cancelados; fuera de término → rechazo con `CANCEL_POLICY_TEXT` y turno intacto; estado terminal `atendido` → `422` conversacional sin mutar) y verificar que FALLA en rojo.
- [x] 1.4 Escribir `tests/integration/test_wa_conv_reprogramar.py` ("REPROGRAMAR" → propone slots reales con opciones numeradas y guarda oferta `wa:conv:*` con TTL; elegir opción válida → turno nuevo + original `reprogramado` + token conservado; oferta expirada → invita a reiniciar sin mutar; slot ocupado en concurrente → `409` conversacional con alternativos) y verificar que FALLA en rojo.
- [x] 1.5 Escribir `tests/integration/test_wa_conv_sena_y_reagenda.py` (turno con `requiere_sena` sin pago acreditado: "SÍ" → responde link MP sin confirmar; tras acreditar (fixture C-08) "SÍ" → `confirmado`; cada cambio reagenda 24 h/3 h vía scheduler C-06 verificando `aviso_envio` reprogramado) y verificar que FALLA en rojo.
- [x] 1.6 Escribir `tests/integration/test_wa_conv_robustos.py` (mensaje ambiguo ("hola", "gracias", texto vacío) → ayuda sin mutar; firma ausente/inválida/cuerpo alterado → `401` ciego sin procesar — regresión C-06; `wa_message_id` duplicado → `200` sin doble mutación ni doble respuesta; rate-limit por remitente-hash ante ráfaga) y verificar que FALLA en rojo.
- [x] 1.7 Fijar fixtures/`conftest.py` (Postgres real de test, `USAR_REDIS_FALSO=true` con fakeredis, `WA_TRANSPORT=fake`, turnos sintéticos `reservado/confirmado` con teléfonos `+54 9 11 15-000-XXXX`, helper de firma HMAC válida/inválida, reloj freezegun) y verificar `pytest --collect-only` lista los tests 1.1–1.6 sin ejecutarlos.

## 2. Parser de intents + matching + settings/env (GREEN mínimo para los tests 1.1–1.6)

- [x] 2.1 Implementar normalización + tabla de intents ES (`confirmar|cancelar|reprogramar|ayuda|desconocido`, prioridad `cancelar > reprogramar > confirmar`, mapeo de interactivos/botones Meta al mismo vocabulario) con type hints (R1), separado de modelos/schemas (R2), y verificar `mypy` limpio en el módulo nuevo.
- [x] 2.2 Implementar resolución por remitente (normalización E.164 AR, comparación por hash, candidatos `reservado|confirmado` con inicio futuro, desempate próximo inicio, desambiguación mismo-día sin mutar) y verificar los tests 1.1 (válido) y 1.2 (desconocido) pasan en verde.
- [x] 2.3 Extender `settings.py` + `.env.example` (`WA_CONV_TTL_MIN=60`, `WA_CONV_RATE_MAX/WINDOW`, vocabulario solo por listas versionadas en código — sin secretos nuevos, R7) y verificar la app levanta con `.env.example` como base.

## 3. Servicio conversacional + webhook extendido (GREEN de punta a punta, con sus docs)

- [x] 3.1 Implementar servicio conversacional en `services/` (orquesta intent → resolución → delegación al núcleo C-04/C-05 con `canal=whatsapp`, respuestas mínimas sin PII, oferta `wa:conv:*` con `SET NX EX` para reprogramar) y verificar los tests 1.1–1.5 pasan en verde.
- [x] 3.2 Extender `POST /webhooks/whatsapp` (firma primero → `401` intacto; luego dedupe `wa_message_id` con registro de respuesta; luego enrutado conversacional; `GET` verify sin cambios) reutilizando `FakeWhatsAppTransport` para la salida y verificar los tests 1.6 pasan en verde.
- [x] 3.3 Cablear reagendado post-cambio (`tras_confirmar` / `tras_cancelar` / `tras_reprogramar` con reloj inyectable) y verificar la reagenda 24 h/3 h de 1.3–1.5 en verde.
- [x] 3.4 Documentar los contratos nuevos en docstrings/schemas (vocabulario, prioridad, forma de respuestas, clave `wa:conv:*` y TTL, extensión de `aviso_recibido` con respuesta) y verificar que la lectura de los schemas permite operar la conversación sin mirar el código.

## 4. Auditoría + seed + respuestas (GREEN con sus docs)

- [x] 4.1 Registrar auditoría conversacional (`turno_confirmado|turno_cancelado|turno_reprogramado` con `canal=whatsapp`, `conv_ambiguo|conv_desconocido|conv_propuesta_slots` sin PII, `remitente` solo como `sha256[:12]`, reuso de `sanitizar_diff`) y verificar búsqueda por `turno_id` en 1.1–1.6 más grep de cero PII en logs.
- [x] 4.2 Extender `seed_demo.py` (1 turno ficticio `reservado` con remitente sintético + 1 conversación de ejemplo auditada marcada `demo`, idempotente) y verificar doble ejecución no duplica registros.

## 5. Verificación integral (solo checks, sin código nuevo)

- [x] 5.1 Pasar `ruff`/`black`, `mypy` limpio total, `pytest --cov --cov-fail-under=80` en verde y verificar cobertura ≥80 % en el dominio nuevo, con regresión C-01…C-11 intacta (standards fastapi/testing-patterns/supabase; Postgres real + freezegun + fakeredis; cero llamadas de red real).
- [x] 5.2 Ejecutar suite completa en verde + `openspec validate --change confirmacion-conversacional-whatsapp` y `openspec status --change confirmacion-conversacional-whatsapp`, y verificar ambos en verde antes de pedir `/opsx:archive`.
