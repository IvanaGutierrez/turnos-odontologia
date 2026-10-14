# Design — C-05 `autogestion-paciente-confirmar-cancelar-reprogramar`

## Context

Ver `proposal.md` (Why/What). Estado actual: C-04 archivada aporta el enlace de reprogramación (original → `reprogramado` + nuevo con mismo `token_publico` vía `reprogramado_de_id`), el índice único parcial de `token_publico` (`WHERE estado NOT IN (inactivos)`), la máquina mínima (`reservado→confirmado→presente`, check-in escribe `presente`) y `en_sala` conservado como alias transitorio con consolidación diferida a este change. No existe ningún endpoint público por token (solo `POST /turnos/publicos` de C-03), ni cancelación con antelación, ni rotación de token. Restricciones: R0 sintético, R1 hints, R2 capas + Alembic, R3 GiST intacta, R5 TDD, R6 crítico aquí (anti-enumeración + minimización Ley 25.326), R7 env, R8 stack.

## Goals / Non-Goals

**Goals:**

- Autogestión completa por token sin login, con la misma garantía anti-doble-reserva del camino normal.
- Cancelación con antelación configurable y mensaje de política accionable.
- Máquina de estados completa y consolidada (`en_sala` eliminado físicamente).
- Rotación de token operativa ante fuga sin romper trazabilidad.

**Non-Goals:**

- Cobrar la seña o acreditar pagos → C-08 (aquí solo se respeta `requiere_sena`: sin pago acreditado no se confirma).
- Escribir recordatorios o el writeback "SÍ" de WhatsApp → C-06/C-12 (aquí solo se audita para que esos workers reaccionen).
- Recurrencias, multi-sede, validación OS → fuera de scope (C-13/v1.5).

## Decisions

1. **Endpoints públicos sin JWT bajo router separado con rate limit por IP (standard fastapi).** `GET /:token`, `POST /:token/confirmar|/cancelar|/reprogramar` viven en un router `turnos_autogestion` separado del protegido (patrón C-03), sin `require_role`, con el mismo rate limit por IP de C-03 (`RATE_PUBLIC_IP_MAX/WINDOW`, reusa el helper Redis). El token viaja en path, nunca en query (evita que quede en logs de proxy). Alternativa descartada: reutilizar `POST /turnos/<id>/...` protegido con el token como query param — mezcla auth staff con acceso paciente y expone el token en logs.
2. **Migración 005 SÍ, mínima y no destructiva salvo el alias.** (a) `turno.motivo_cancelacion TEXT NULL` + `turno.cancelado_at TIMESTAMPTZ NULL` (trazabilidad de la cancelación del paciente; NULL salvo `cancelado`); (b) consolidación `en_sala→presente`: `UPDATE turno SET estado='presente' WHERE estado='en_sala'` + reescritura de `ck_turno_estado` sin `'en_sala'`; (c) sin cambios en GiST ni en el índice parcial de token (ya sirven a reprogramación y rotación). Rollback: `downgrade -1` revierte columnas y check (el backfill `en_sala→presente` no se deshace — documentado, sin pérdida semántica porque el servicio ya escribe `presente`). Alternativa descartada: no migrar y mantener `en_sala` para siempre — perpetúa la divergencia KB/código señalada en C-04.
3. **Cancelación con antelación por servicio con reloj inyectable.** `CANCEL_MIN_HOURS` (default 12, env) + `CANCEL_POLICY_TEXT` (env, texto del consultorio). Regla: `inicio - ahora >= CANCEL_MIN_HOURS` → cancela (`cancelado`, `cancelado_at=ahora`, slot liberado por el predicado de inactivos); si no → `422` con `{problema: "fuera_de_termino", horas_restantes, politica: CANCEL_POLICY_TEXT}`. `ahora` se obtiene de un proveedor de reloj inyectable para que los tests usen freezegun sin tocar producción. Cancelar un turno ya `cancelado` es idempotente (`200`, sin re-auditar). Alternativa descartada: calcular la antelación en el router — duplica lógica entre endpoints y rompe R2.
4. **Reprogramación pública = mismo núcleo de C-04, sin bifurcar.** El servicio de autogestión delega en `reprogramar_turno` existente (pre-chequeo + GiST + enlace `reprogramado_de_id` + token conservado + `409` con alternativos mismo shape C-01), añadiendo solo la resolución por token y la guarda de estados (`reservado|confirmado`). La seña pendiente no bloquea reprogramar (solo bloquea confirmar, RN-PA-02). Alternativa descartada: duplicar la lógica de slots en el servicio público — dos fuentes de verdad para R3.
5. **Rotación solo por staff protegido, nunca implícita.** `POST /api/v1/turnos/<id>/rotar-token` con `require_role("turnos")` genera `secrets.token_urlsafe(32)`, invalida el anterior (el índice parcial hace que el viejo quede inerte en un turno inactivo o inexistente) y audita `token_rotado` con ambos IDs de turno si aplica, sin PII. Los endpoints públicos jamás rotan solos: la reprogramación conserva el token (RN-AG-07) y la sospecha de fuga la declara una persona. Alternativa descartada: rotar en cada uso público — rompe los links de WhatsApp/C-06 y el QR impreso.
6. **Anti-enumeración total + minimización Ley 25.326 (R6).** Token desconocido o inválido → `404` con cuerpo idéntico (`{problema: "no_encontrado", detalle: genérico}`), mismo tiempo de respuesta aparente (una sola query por token, sin ramas que delaten existencia) y sin distinguir "token malformado" de "turno inexistente". `GET /:token` devuelve solo `{estado, inicio, fin, prestacion_nombre, profesional_nombre, sede, puede_cancelar_en_termino, horas_limite, url_pago?}` — jamás DNI, teléfono, HC, hashes ni el propio token en el cuerpo. Diffs de auditoría con IDs/horarios/estados (reusa `sanitizar_diff`). Alternativa descartada: `403` para token inválido — confirma existencia del recurso al atacante.
7. **Confirmar idempotente, seña respetada.** `POST /:token/confirmar` sobre `reservado` → `confirmado` + `turno_confirmado`; sobre `confirmado` → `200` idempotente con el mismo estado (sin duplicar auditoría); sobre terminal → `422`. Si `prestacion.requiere_sena` y no hay pago acreditado → `422` con `{problema: "sena_pendiente", url_pago}` (el cobro es C-08; aquí no se crea `Pago`). Transición `presente→atendido` y `→ausente` quedan solo en staff (este change las declara en la máquina pero no expone endpoints públicos para ellas; intentarlas por token → `422`). Alternativa descartada: confirmar con seña pendiente pasando igual a `confirmado` — viola RN-PA-02.
8. **Testing (plan, se ejecuta en apply):** pytest sobre Postgres real (GiST parcial e índice parcial no existen en SQLite), freezegun para la antelación, fakeredis para el rate limit público (patrón C-03), AAA, `--cov-fail-under=80` en el dominio nuevo; concurrencia: doble confirmación simultánea (una confirma, otra idempotente sin duplicar auditoría) y doble cancelación del mismo token.

## Risks / Trade-offs

- [Riesgo] Token en URL queda en logs de acceso del proxy → Mitigación: token solo en path (nunca query), ningún log de app registra el path con token (se loguea `token_hash_prefix` de 6 chars si hace falta correlacionar), rotación staff ante fuga.
- [Riesgo] Carrera doble cancelación / confirmar-vs-cancelar simultáneos → Mitigación: transacción por endpoint con `SELECT ... FOR UPDATE` del turno; el segundo ve el estado ya mutado y responde idempotente/`422` sin doble auditoría; test de concurrencia en apply.
- [Riesgo] Reloj y TZ en el borde de las 12 h (DST, naive vs aware) → Mitigación: todo `timestamptz`, `inicio` aware obligatorio, comparación en UTC, tests freezegun en `America/Argentina/Buenos_Aires`.
- [Riesgo] Respuesta 404 con timing distinto delata existencia → Mitigación: una sola query indexada por token en todos los casos; sin reintentos ni ramas previas; sin mensajes diferenciados.
- [Trade-off] Rotación manual por staff vs automática. Aceptada la manual: la automática invalida links legítimos en circulación (WhatsApp, QR) y genera más soporte que la fuga que pretende mitigar.

## Migration Plan

1. `apply` ejecuta migración 005 sobre DB con datos C-01…C-04: columnas anulables con defaults NULL (sin backfill salvo `en_sala→presente`), reescritura del check de estados en transacción breve, GiST e índice parcial intactos.
2. Deploy: `docker compose up --build`; solo env nuevas en `.env.example` (`CANCEL_MIN_HOURS=12`, `CANCEL_POLICY_TEXT`); sin cambios en Compose.
3. Rollback: `alembic downgrade -1` (revierte columnas y check; el backfill de `presente` persiste sin daño).
4. Seed demo: 1 turno ficticio `reservado` con token conocido `demo-...` marcado `demo` para ejercitar la autogestión en dev (R0).

## Open Questions

- Ninguna que cambie specs, enfoque o tasks: el texto exacto de `CANCEL_POLICY_TEXT` y el valor piloto de `CANCEL_MIN_HOURS` se ajustan por env sin tocar código.
