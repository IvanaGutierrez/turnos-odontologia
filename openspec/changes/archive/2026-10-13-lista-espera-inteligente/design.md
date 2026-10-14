# Design — C-14 `lista-espera-inteligente`

## Context

Ver `proposal.md` (Why/What). Estado actual verificado por lectura de `app/` y `alembic/versions/`: no existe ningún modelo, tabla, router ni servicio de espera (la palabra solo aparece en plantillas seed y en la oferta efímera `wa:conv:*` de C-12, que es reprogramación 1-a-1 y no se toca); el trigger natural existe — `cancelar_por_token` C-05 (más `reprogramar`/staff C-04 y conversacional C-12) con hooks `tras_cancelar` C-06; `link_pago_para` + `procesar_aviso` C-08 resuelven pago→turno con idempotencia por `mp_payment_id` + reclamo `FOR UPDATE`; el worker C-06 drena por DB con fail-open; el GiST anti-solapamiento sigue mandando. Migraciones `001–012` ocupan todos los slots (head `012_validacion_os`); la "Migración 008" de CHANGES.md es `008_ficha_clinica` (C-07) — el número correcto es **013**. Restricciones: R0 sintético (pacientes/huecos/pagos ficticios, Fake WA/MP, jamás red real); R1 hints; R2 capas + Alembic; R3 GiST intacto (el slot ofertado solo se ocupa vía `INSERT` bajo exclusión); R5 TDD con concurrencia real; R6 crítico (la oferta es 1-a-1: jamás datos de otros en espera); R7 env sin secretos; R8 stack fijo.

## Goals / Non-Goals

**Goals:**

- Hueco por cancelación → oferta automática al top-N rankeado, asigna quien paga la seña primero, con re-oferta ante expiración y expiración silenciosa ante ventana vencida (US-051, Flujo 5, RN-PA-01/02/03, RN-AG).
- Un solo ganador ante doble pago concurrente, sin duplicar turno ni debilitar el GiST; perdedor reembolsado y liberado.

**Non-Goals:**

- Puja/overbooking, frontend de espera, cambios en C-04/C-05/C-06/C-08/C-09 (solo extensión de metadata + nuevo tipo utility), ARCA (v2).

## Decisions

1. **Migración 013 (verificado, no 008).** `001→…→012` encadenados con head en `012_validacion_os`; CHANGES.md arrastra el número viejo. 013 crea `lista_espera` (paciente, prestación, profesional?, ventana `tstzrange`, score + componentes `jsonb`, estado) + `oferta_espera` (espera, hueco snapshot —`profesional_id/sillon_id/inicio/fin` congelados + `hueco_origen_id`—, `expira_at`, estado, `mp_preference_id`) con índices `(estado, ventana)`, `(hueco_origen_id, estado)` y checks (`desde < hasta`, estados en enum). Alternativa descartada: reutilizar 008 — rompería la cadena Alembic.
2. **Sin fila `Turno` hasta que alguien paga (decisión madre).** La oferta NO reserva el slot: el hueco sigue libre y visible para reserva normal. Recién el primer webhook acreditado inserta el `Turno canal=lista_espera` bajo el GiST; si el slot se ocupó por otro canal entre medio, el `INSERT` choca con la exclusión → el pagador va a `reembolsado` y la entrada vuelve a `activa` (nunca se pierde dinero ni se duplica). Alternativa descartada: pre-crear el turno `reservado` al ofertar — bloquearía el slot durante el TTL y regalaría overbooking encubierto.
3. **Scoring determinístico, explicable y por env.** Elegibles: `activa` + ventana que cubre el hueco + misma `prestacion_id` (+ `profesional_id` si la entrada lo fija). `score = 100*(P_VENT*w_vent + P_HIST*w_hist + P_VALOR*w_valor)` con `w_*` por env (default 40/35/25): `P_VENT` = cercanía del hueco al inicio de la ventana del paciente; `P_HIST` = 1 − tasa de ausentismo propia (`ausente/(confirmado+presente+atendido+ausente)`, sin historia = 0.5 neutro); `P_VALOR` = seña de la prestación normalizada contra el máximo del catálogo. Desempate: `created_at` ASC. Se persisten `score` + componentes `jsonb` (auditable, sin PII). Alternativa descartada: ML/caja negra — impredecible y no explicable ante reclamo.
4. **Trigger único: toda cancelación publica `hueco_liberado`.** Staff (C-04), token (C-05) y chat (C-12) llaman al mismo hook post-`cancelado` con el snapshot del slot; el worker ranquea y oferta. Solo huecos futuros y re-ofertables (inicio > ahora + margen por env); reprogramaciones NO publican (el slot viejo lo absorbe la cadena, RN-AG-07). Degradación: sin Redis el worker drena por DB (patrón C-06); si WA cae, la oferta queda `pendiente` + `aviso_a_recepcion` y el hueco sigue libre — nunca se pierde ni se regala.
5. **Blast top-N con TTL y re-oferta en cascada.** `LISTA_ESPERA_TOP_N` (default 3) ofertas `pendiente` con `expira_at = ahora + LISTA_ESPERA_OFERTA_TTL_MIN` (default 30) + mensaje utility `oferta_lista_espera` (variables R6: nombre_pila, fecha, hora, sede, link de seña — jamás otros en espera). Entradas ofertadas → `ofertada`. Barredor periódico: `pendiente` vencida → `expirada`, su entrada → `activa`, y re-oferta al siguiente elegible aún no ofertado para ese hueco (historial por `hueco_origen_id`); si no quedan elegibles, el hueco queda libre sin ruido. Idempotencia del blast por `(oferta_id, tipo_aviso)` sobre el `UNIQUE (turno_id, tipo_aviso)` existente reuseando `AvisoEnvio` con `turno_id=NULL`? No — `AvisoEnvio.turno_id` es NOT NULL: el blast usa inserción directa en `oferta_espera` + envío vía transporte C-06 sin pasar por `aviso_envio` (oferta ≠ recordatorio de turno existente).
6. **Asignación atómica en el webhook (un solo ganador).** `metadata.oferta_espera_id` (fijada al crear la preferencia de la oferta) → `procesar_aviso` reclama la oferta `FOR UPDATE`: si sigue `pendiente` y vigente → `aceptada`, inserta el turno (GiST manda), entrada → `asignada`, hermanas → `desplazada` + entradas → `activa`, eventos `lista_espera_asignada` + `pago_acreditado` (C-09 concilia igual) + comprobante WA + `aviso_a_recepcion`. Si ya está `aceptada/expirada` (doble pago) → pago a `reembolsado` (refund MP; Fake en tests) + `pago_reembolsado` auditado, sin turno nuevo. `mp_payment_id` único sigue frenando el duplicado exacto (C-08 intacto). Alternativa descartada: "el primero que abre el link gana" — el click no es dinero; solo el acreditado reclama.
7. **RBAC y privacidad: la oferta es 1-a-1.** `lista_espera: {admin, recepcion}` full, `odontologo` lectura (ver demanda de su agenda); endpoints públicos: ninguno (el paciente solo recibe su oferta y paga por el link firmado C-08). Mensaje/auditoría/diffs: solo slot propio + IDs; barrido anti-fuga (DNI, teléfonos, HCE, datos de otros en espera) en tests. Ventana vencida o baja manual → `expirada` sin oferta ni ruido.
8. **Testing (plan, se ejecuta en apply — R5).** pytest sobre Postgres real + Fake WA/MP, datos sintéticos (R0): cancelación dispara scoring+blast top-N; orden de scoring exacto (ventana/historial/valor + desempate antigüedad); oferta aceptada → `asignada` + turno `canal=lista_espera` + `pago_acreditado` + recepción notificada; doble pago concurrente real (threads) → un solo turno y un `reembolsado`; expiración → re-oferta al siguiente + resto a `activa`; ventana vencida → `expira` sin blast; slot ocupado por otro canal → pagador reembolsado; barrido PII en mensajes/diffs/logs; cov ≥ 80 % en el módulo nuevo; regresión C-04/C-05/C-06/C-08/C-09 intacta.

## Risks / Trade-offs

- [Riesgo] Carrera pago-vs-reserva normal por el mismo slot → Mitigación: el GiST decide (decisión 2); el perdedor-pagador se reembolsa automáticamente, nunca queda con cargo sin turno.
- [Riesgo] Blast molesto (top-N que nunca paga) → Mitigación: N y TTL por env + historial por hueco (nadie recibe dos ofertas del mismo hueco) + ventana como consentimiento implícito.
- [Riesgo] Fuga de datos entre en espera (R6) → Mitigación: oferta 1-a-1 con solo slot propio + test de barrido con PII marcada.
- [Trade-off] Sin reserva del slot durante la oferta: un ofertado puede perder el hueco ante reserva normal más rápida. Se acepta (el slot libre maximiza ocupación, que es el objetivo US-051); la expiración corta (30') acota la ventana de decepción.

## Migration Plan

Migración 013 adelante-atrás (`upgrade` crea 2 tablas + índices + checks; `downgrade` las elimina — sin datos reales que migrar). Deploy: solo backend + `.env.example` (6 vars nuevas, sin secretos). Rollback: revert del change + `alembic downgrade -1` (ningún change previo depende de estas tablas; C-08/C-06/C-09 solo leen el metadata/evento nuevo de forma tolerante).

## Open Questions

Ninguna que cambie specs, enfoque o tasks — es el último change del roadmap y no deja deuda prevista salvo el frontend de espera (change futuro explícito en No-objetivos).
