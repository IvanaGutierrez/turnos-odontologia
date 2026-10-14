# Design — C-08 `sena-mercadopago-webhook`

## Context

Ver `proposal.md` (Why/What). Estado actual (solo lectura de `app/`): `Prestacion` tiene `requiere_sena: bool` + `precio_base?` pero sin monto/% de seña; no existe modelo `Pago`, ni cliente MP, ni router `/webhooks/mercadopago` (solo existe `whatsapp_webhook.py` como patrón a imitar); `reserva_publica.url_pago_para()` genera un link opaco firmado con `PAGO_LINK_SECRET` sin crear `Pago`; `autogestion.confirmar` levanta `SenaPendienteError → 422 + url_pago` cuando `requiere_sena` y no hay acreditación. Restricciones: R0 sintético + sandbox/Fake MP jamás red real; R1 hints; R2 capas + Alembic; R5 TDD con Fake MP; R6 jamás PII del pagador en logs/errores; R7 `MP_ACCESS_TOKEN`/`MP_WEBHOOK_SECRET` solo env + fail-fast; R8 stack fijo.

## Goals / Non-Goals

**Goals:**

- Link de pago real en ARS con metadata (`turno_id`/`presupuesto_id`) resoluble desde el `url_pago` opaco existente.
- Webhook que nunca acredita nada sin firma válida y nunca acredita dos veces el mismo `mp_payment_id`.
- Turno con seña requerida que solo confirma al acreditarse; pago rechazado visible con reintento y turno pendiente.
- Monto de seña configurable por prestación (fijo o % del precio base).

**Non-Goals:**

- Conciliación y cierre de caja (C-09; aquí solo se deja el evento de caja MP).
- Facturación ARCA (v2), reembolsos automáticos, cobro de OS (C-13), asignación de lista de espera (C-14).

## Decisions

1. **Migración 009 `pago_senia_mp` (CHANGES.md decía 005 — obsoleto).** `alembic history` verificado: cadena `001→…→008_ficha_clinica (head)`; 005–008 ocupadas. La 009 crea tabla `pago` + columnas de seña en `prestacion` (`sena_monto_fijo NUMERIC NULL`, `sena_porcentaje NUMERIC NULL CHECK 0–100`), sin tocar GiST ni tablas de agenda/C-06/C-07. Tabla `pago(id, paciente_id FK, turno_id FK NULL, presupuesto_id FK NULL, monto NUMERIC, moneda='ARS' CHECK, metodo='mercadopago' CHECK, estado CHECK pendiente|acreditado|rechazado|reembolsado, mp_payment_id TEXT UNIQUE NULL, mp_preference_id TEXT UNIQUE NULL, webhook_recibido_at NULL, created_at)` + índices `(turno_id)`, `(estado)`. Alternativa descartada: reutilizar "005 libre" — no está libre; renumerar rompería el historial aplicado.
2. **Cliente MP tras protocolo mockeable + Fake en tests (standards fastapi/testing-patterns).** `MercadoPagoClient` (prod, `httpx` con `MP_TIMEOUT_S`, crea preferencia con `metadata={turno_id, presupuesto_id}` y `currency_id='ARS'`) vs `FakeMercadoPagoClient` (tests/dev: preferencias y pagos en memoria con resultados programables ok/rechazado/duplicado). Servicios solo conocen el protocolo; selección por settings (`MP_CLIENT=fake` en tests). Jamás red real ni credenciales reales en tests (R0): sandbox solo para validación manual fuera de la suite. Alternativa descartada: SDK oficial directo en el servicio — imposible probar duplicados/rechazos sin red.
3. **Resolución `GET /pagar/:token` sobre el link opaco existente (sin romper C-03/C-05).** El `:token` es el firmado por `url_pago_para` (`PAGO_LINK_SECRET`); el endpoint lo verifica, localiza el turno y busca/crea idempotentemente el `Pago pendiente` del turno (UNIQUE parcial un pendiente por turno), crea (o reutiliza) la preferencia MP y devuelve `{init_point, monto, estado}` o redirige. El shape `201 + url_pago` de reserva y el `422 + url_pago` de autogestión no cambian. Alternativa descartada: crear la preferencia al reservar — genera preferencias huérfanas por cada slot mirado y expone `preference_id` antes de necesitarlo.
4. **Cálculo de seña por prestación: fijo gana a porcentaje.** Si `sena_monto_fijo NOT NULL` se usa; si no, `precio_base * sena_porcentaje/100`; si ninguno está configurado y `requiere_sena=true` → se bloquea la creación de preferencia con `422` de configuración (falla visible a recepción, nunca monto cero silencioso). Primera vez y tratamientos largos se marcan con `requiere_sena=true` (RN-PA-01). Alternativa descartada: default global silencioso — oculta errores de catálogo y genera señas arbitrarias.
5. **Webhook `POST /webhooks/mercadopago` con verificación `x-signature` y 401 ciego (standard fastapi + R6).** MP firma con `x-signature: ts=...,v1=...` donde `v1 = HMAC-SHA256(MP_WEBHOOK_SECRET, "id:{data.id};request-id:{x-request-id};ts:{ts};")`; se compara con `hmac.compare_digest`. Ausente/inválida/cuerpo alterado → `401` genérico, sin procesar, sin mutar, sin auditar contenido. Tras verificar, el handler obtiene el pago desde la API MP (o del cuerpo si trae `data.id`) y aplica la transición en UNA transacción: `UPDATE pago ... WHERE mp_payment_id=:id` con reclamo por estado (`pendiente→acreditado|rechazado`); duplicado del mismo `mp_payment_id` → `200` sin efectos (RN-PA-03). Solo entonces: turno con seña requerida `reservado→confirmado` (reusa máquina C-05 + auditoría), evento de caja MP y encolado de comprobante WA. Alternativa descartada: acreditar desde el cuerpo sin consultar a MP — el cuerpo es falsificable; la firma solo autentica el aviso, el estado se confirma contra MP (Fake en tests).
6. **Máquina de estados del pago + visibilidad del rechazo.** `pendiente → acreditado | rechazado`; `acreditado → reembolsado` solo manual (flujo fuera de scope, estado modelado para C-09). `GET /pagar/:token` y `GET turno público` exponen `estado_pago` (`pendiente|rechazado`) sin PII para mostrar "pago rechazado, reintentá" con el mismo link (reintento = nueva preferencia o la misma vigente, jamás dos `Pago pendiente` por turno). Turno con pago rechazado sigue `reservado` (Flujo 4: "turno sigue pendiente"). Alternativa descartada: cancelar el turno ante rechazo — viola el flujo KB y pierde la reserva por un fallo del medio de pago.
7. **Evento de caja MP como interfaz hacia C-09 (decisión de alcance).** Este change NO crea `MovimientoCaja` (es de C-09, migración 010+). Al acreditar, registra auditoría `pago_acreditado` con `{pago_id, turno_id, monto, moneda ARS, metodo=mercadopago, mp_payment_id}` — payload suficiente para que C-09 concilie sin releer MP. Riesgo documentado: si C-09 cambia el formato, necesita migración de lectura; mitigación: el evento es append-only y versionado (`v:1`).
8. **Comprobante por WhatsApp reutilizando C-06 (sin modificar sus specs).** Al acreditar, el servicio encola un aviso tipo `comprobante_pago` con variables mínimas `{nombre_pila?, fecha, hora, sede, monto, link_gestion}` vía el scheduler/transporte C-06 (extensión de tipo permitida por env, no cambia sus REQUIREMENTS de secuencia). Si WA cae, rige la degradación C-06 (fallback + aviso a recepción) y el pago SIGUE acreditado (el dinero manda sobre la notificación). Alternativa descartada: enviar el comprobante sincrónico en el webhook — acopla la acreditación a Meta y retrasa el `200` que MP exige rápido.
9. **Privacidad y secretos (R6/R7, Ley 25.326, governance CRITICO).** Logs/diffs solo con `{pago_id, turno_id, monto, estado, mp_payment_id, mp_preference_id}`; JAMÁS email del pagador, datos de tarjeta/cuenta, DNI, teléfono, ni tokens MP. `MP_ACCESS_TOKEN` y `MP_WEBHOOK_SECRET` sin default: fail-fast al arrancar si `MP_CLIENT=http` sin ellos (como `JWT_SECRET`); `.env.example` solo placeholders `cambiar-*-no-real`. `PAGO_LINK_SECRET` existente se mantiene para el token opaco.
10. **Testing (plan, se ejecuta en apply — R5, AAA, cov 80):** pytest sobre Postgres real + `FakeMercadoPagoClient`; casos: preferencia con metadata round-trip + ARS; webhook válido acredita (pago + turno + evento caja + comprobante encolado); webhook duplicado mismo `mp_payment_id` → `200` sin doble acreditación/movimiento/comprobante; firma ausente/inválida/cuerpo alterado → `401` sin mutar; pago rechazado → visible + reintento con turno `reservado`; confirmar con seña pendiente sigue `422` (regresión C-05); seña sin monto configurado → `422` de configuración. Todo monto/pagador sintético (R0).

## Status pin (apply C-08 parte 2)

- **MP caído → `503` pinneado** (el RED aceptaba 200/502/503): el webhook y
  `GET /pagar/:token` responden `503` genérico ante `MP caído`
  (`FakeMPError` en tests, timeout/red/5xx en prod), sin acreditar por
  defecto; el turno sigue `reservado` + auditoría `pago_mp_no_disponible`
  (aviso a recepción) y el mismo link reintenta. `503` = reintentable por
  MP/cliente, a diferencia de `200` (que MP leería como "aviso procesado").
- **Migración `010_pago_comprobante`** (además de la 009): `pago.init_point`
  (reuso del link vigente sin duplicar preferencias) + `ck_aviso_tipo`
  extendido con `comprobante_pago` (seam RED; el veto marketing C-06 intacto).
- **Vinculación sin metadata** (el Fake no la porta; MP real sí vía
  `metadata`/`external_reference`): fallback a UNICO candidato
  (`reservado` + seña + sin acreditado) con gate de monto exacto; ante
  cero/múltiples candidatos o monto distinto → `200` + auditoría
  `pago_sin_turno` (jamás atribuye dinero a ciegas). Idempotencia sin
  excepciones: `ON CONFLICT DO NOTHING` + `FOR UPDATE` + reclamo por estado.

## Risks / Trade-offs

- [Riesgo] MP caído o firma rotada al cobrar → Mitigación: turno queda `reservado` pendiente de seña + aviso a recepción (Flujo 1, excepción global KB: degrada a manual, nunca pierde el turno); reintento con el mismo link.
- [Riesgo] Webhook llega antes que el `Pago pendiente` exista (carrera pagar→aviso) → Mitigación: el handler crea el `Pago` desde `metadata` si no existe (upsert por `mp_payment_id`), marcando `origen=webhook`.
- [Riesgo] Doble acreditación concurrente (dos workers/threads) → Mitigación: UNIQUE `mp_payment_id` + reclamo transaccional por estado; la DB manda.
- [Riesgo] Comisiones/retenciones MP según condición fiscal → Mitigación (KB §2): relevar en onboarding; exponer costo en reportes (C-11); fuera de scope del cálculo aquí.
- [Trade-off] Evento de caja en auditoría vs tabla `MovimientoCaja` ya. Se acepta el evento: evita invadir C-09; costo: C-09 debe leer auditoría para conciliar (contrato explícito en §7).
