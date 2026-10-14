# Proposal — C-12 `confirmacion-conversacional-whatsapp`

## Why

Los recordatorios de C-06 bajan ausentismo pero obligan a abrir la web para gestionar el turno (US-003). El diferenciador v1.5 (US-011, RN-NO-03) cierra el loop: el paciente confirma, cancela o reprograma con un mensaje de WhatsApp ("SÍ") 24/7, sin fricción. C-06 dejó el writeback explícitamente fuera de scope (su inbound solo acusa recibo y audita) — este change lo implementa ahora, sin romper su contrato de firma.

## What Changes

- Bot conversacional sobre el webhook C-06: interpreta intents `confirmar` / `cancelar` / `reprogramar` en texto libre ES (con tolerancia a acentos/mayúsculas) y ejecuta el writeback contra la agenda.
- Writeback con matching de remitente: "SÍ" confirma SOLO si el remitente normalizado coincide con el teléfono del turno candidato; remitente desconocido o ambiguo → responde link de gestión genérico sin mutar nada (R6).
- Reutiliza el núcleo C-04/C-05 sin duplicarlo: mismas transiciones (`reservado→confirmado`, `reservado|confirmado→cancelado`, reprogramación C-04), misma antelación `CANCEL_MIN_HOURS` (RN-AG-05) y misma guarda de seña (RN-PA-02: seña pendiente → responde link MP, sin confirmar).
- Reprogramación conversacional en dos pasos: propone slots reales (reusa disponibilidad C-03) y confirma ante la elección; estado efímero en Redis con TTL (sin migración).
- Tras cada cambio reagenda los recordatorios 24 h / 3 h reutilizando los workers/scheduler C-06 (`tras_confirmar` / `tras_cancelar` / `tras_reprogramar`).
- Firma del webhook intacta: sin firma válida sigue `401` ciego sin procesar (contrato C-06 no cambia); solo con firma válida se enruta al handler conversacional, con idempotencia por `wa_message_id` (sin doble respuesta ante reintento Meta).
- Tests planeados (se ejecutan en apply, R5): "SÍ" válido → confirmado; desconocido no muta; cancelación tardía rechazada por chat; seña pendiente → link MP.

## Capabilities

### New Capabilities

- `notificaciones/confirmacion-conversacional`: bot 24/7 confirmar/cancelar/reprogramar por WhatsApp con matching de remitente, parser de intents ES, guarda de antelación y seña, estado efímero de reprogramación y respuestas sin PII.

### Modified Capabilities

- `notificaciones/recordatorios-whatsapp`: el inbound del webhook pasa de "solo acusa recibo y audita" a "verifica firma y enruta al handler conversacional"; el requisito de `401` ciego ante firma inválida y el `200` idempotente ante `wa_message_id` duplicado NO cambian.

## Impact

- Nuevo: servicio conversacional (`services/conversacion_whatsapp.py` + parser de intents), estado efímero Redis `wa:conv:{hash}` con TTL, settings `WA_CONV_*` solo por env (R7), extensión del router `webhooks/whatsapp` existente (verificación primero, enrutado después).
- Reusa sin modificar: máquina de estados y servicios C-04/C-05 (`confirmar/cancelar/reprogramar_por_token` o su núcleo — el writeback resuelve el turno por remitente y delega), scheduler/workers C-06, `FakeWhatsAppTransport` en tests (R0 sintético, jamás red real), Redis real prod + fakeredis tests (R8).
- No-objetivos explícitos: plantillas de marketing (RN-NO-01 intacto), cobro/acreditación MP (C-08 solo se enlaza con link), validación OS (C-13), lista de espera (C-14), voz/audio o IA generativa (matching por reglas determinísticas).
