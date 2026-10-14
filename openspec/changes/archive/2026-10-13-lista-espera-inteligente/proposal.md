# Proposal — C-14 `lista-espera-inteligente`

## Why

Cada cancelación deja un hueco que hoy solo se cubre si recepción llama a mano: el slot se pierde y el paciente en espera sigue sin turno. Este change cierra el loop (US-051, Flujo 5, diferenciador v1.5): ante una cancelación, el sistema ranquea la espera, oferta el hueco por WhatsApp con seña y asigna a quien paga primero. Va sobre el camino crítico ya estable (C-05 trigger, C-06 blast, C-08 cobro) y es el ÚLTIMO change del roadmap. Governance MEDIO: toca dinero (seña con reembolso al perdedor) y concurrencia real, pero reusa los núcleos auditados de cobro, avisos y GiST sin modificarlos.

## What Changes

- Modelos nuevos: `ListaEspera` (paciente, prestación, profesional?, ventana desde/hasta, score + componentes, estado `activa|ofertada|asignada|expirada`) y `OfertaEspera` (hueco snapshot + expira_at + estado `pendiente|aceptada|expirada|desplazada`); migración **013** (la "008" que cita CHANGES.md corresponde a `008_ficha_clinica` de C-07 — verificado: `001→…→012` ocupados, head `012_validacion_os`).
- Alta/baja/consulta de espera (`POST/GET/DELETE /api/v1/lista-espera`, solo staff): la ventana es el contrato — vencida la ventana, la entrada expira sin oferta.
- Worker `hueco_liberado`: cada cancelación (staff C-04, token C-05, chat C-12) publica el hueco (profesional, sillón, inicio, fin); scoring determinístico (compatibilidad de ventana + historial de asistencia + valor del tratamiento, pesos por env, desempate por antigüedad) → blast WhatsApp top-N con oferta expirable + link de seña MP.
- Asignación atómica por pago: el webhook MP existente acepta `metadata.oferta_espera_id`; el primer acreditado reclama el slot (`FOR UPDATE` + `INSERT` del turno `canal=lista_espera` bajo el GiST intacto) → entrada `asignada`, resto a `activa`; el concurrente perdedor NO duplica turno: su pago va a `reembolsado` con auditoría. Expiración → barrido que re-oferta al siguiente.
- Caja y recepción sin cambios de schema: la seña viaja por el evento `pago_acreditado` existente (C-09 concilia igual); el turno asignado aparece en la grilla con `canal=lista_espera` + `aviso_a_recepcion` existente.
- Tests planeados (se ejecutan en apply, datos sintéticos — R0).

## Capabilities

### New Capabilities

- `agenda/lista-espera`: alta/baja/consulta de la espera con ventana, scoring determinístico del hueco, ofertas expirables con re-oferta, asignación atómica al primer pago y expiración por ventana — sin filtrar jamás otros en espera (R6).

### Modified Capabilities

- `cobros/sena-mercadopago-webhook`: el webhook resuelve avisos con `metadata.oferta_espera_id` y reclama el slot atómicamente (un solo ganador; perdedor a `reembolsado` sin duplicar turno).
- `notificaciones/recordatorios-whatsapp`: nuevo tipo utility `oferta_lista_espera` (plantilla + variables mínimas R6) y blast top-N con idempotencia por (oferta_id, tipo).
- `auditoria/registro-acciones`: se agregan los eventos `lista_espera_creada|oferta_enviada|oferta_expirada|lista_espera_asignada|pago_reembolsado`, con la misma minimización R6 (sin DNI/teléfono/HCE ni datos de otros en espera en el `diff`).

## Impact

- Nuevo: modelos `ListaEspera|OfertaEspera` + migración 013 (tablas + índices + FKs + checks de ventana/estados), servicio `lista_espera.py` (scoring puro + máquina de estados) + schemas, router `lista_espera` (staff), worker `hueco_liberado` + barredor de expiración (drena por DB, fail-open sin Redis como C-06), recurso matriz `lista_espera`, vars `.env.example` (`LISTA_ESPERA_TOP_N`, `LISTA_ESPERA_OFERTA_TTL_MIN`, `LISTA_ESPERA_PESO_*`, `WA_TEMPLATE_OFERTA`) — sin secretos nuevos (R7).
- Reusa sin modificar: cancelación C-04/C-05/C-12 como único trigger, `link_pago_para` + `procesar_aviso` C-08 (se extiende el metadata, no se reescribe), transporte/fallback/reintentos C-06, evento `pago_acreditado` → C-09, `EXCLUDE USING gist` como última defensa (R3), `sanitizar_diff()` + `registrar_auditoria()`, `require_role`/matriz.
- No-objetivos explícitos: overbooking predictivo por ausentismo, subasta del slot al mejor postor (el precio de la seña es el de la prestación, nunca puja), frontend de espera (este change es backend; la grilla existente ya muestra `canal=lista_espera`), ARCA (v2).
