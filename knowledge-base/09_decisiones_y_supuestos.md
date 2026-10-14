# Decisiones y Supuestos

## Decisiones documentadas

### DD-01 — Stack fijo FastAPI + JWT + SQLAlchemy + PostgreSQL + Redis + Docker/Compose; React + TS + Vite
**Decisión**: stack cerrado, sin alternativas en v1.
**Contexto**: restricción del TPI/discovery (`discovery/discovery.md` §9).
**Alternativas consideradas**: Next.js fullstack, Django, Node/Nest.
**Justificación**: encaje directo con el MVP (JWT roles, PG exclusion constraints, Redis workers, deploy simple en VPS AR).
**Trade-offs aceptados**: sin SSR (SEO de reserva depende de landing simple); sin ORM multi-DB.

### DD-02 — Reserva sin cuenta (DNI + teléfono + token público)
**Decisión**: el paciente no se registra; identidad = DNI + teléfono verificado.
**Contexto**: fricción de registro mata conversión (referencia AgendaPro reserva sin registro, Fresha 3 taps).
**Alternativas consideradas**: cuenta con login obligatorio; login social.
**Justificación**: conversión + simplicidad; seguridad vía token de un solo propósito + rate limit.
**Trade-offs aceptados**: menor vínculo longitudinal; riesgo de spam mitigado con verificación.

### DD-03 — Monolito modular, no microservicios
**Decisión**: un deploy backend con módulos por dominio.
**Contexto**: equipo chico, VPS único, v1.
**Justificación**: velocidad y operabilidad; modularidad permite extraer OS/facturación después.
**Trade-offs aceptados**: escalado vertical en v1; disciplina de módulos a enforcing por code review.

### DD-04 — WhatsApp Cloud API como canal primario, email/SMS fallback
**Decisión**: recordatorios y confirmación conversacional por WhatsApp (plantillas utility).
**Contexto**: estándar esperado en Latam; email-only es debilidad de la competencia.
**Alternativas consideradas**: solo email/SMS; proveedor BSP intermedio.
**Justificación**: Cloud API directa = menor costo y control; opt-in marketing separado (cumplimiento).
**Trade-offs aceptados**: dependencia Meta (costos de conversación, plantillas); número propio por clínica.

### DD-05 — Mercado Pago para señas (link + webhook), no procesador genérico
**Decisión**: MP como única pasarela v1.
**Contexto**: normalizado en AR (TuTurno.io, DentalSoft lo usan); pesos + cuotas locales.
**Justificación**: adopción inmediata; comisiones/retenciones según condición fiscal (riesgo conocido).
**Trade-offs aceptados**: lock-in MP; condición fiscal por consultorio a relevar.

### DD-06 — ARCA en fase 2, no en MVP
**Decisión**: facturación electrónica nativa post-MVP (v2).
**Contexto**: solo DentalTec la tiene; homologación compleja.
**Justificación**: prioriza agenda+clínica+cobros que generan valor día 1; evita bloquear MVP en homologación.
**Trade-offs aceptados**: sistema paralelo de facturación durante v1; diseño DB ya prevé comprobantes.

### DD-07 — OS preventiva y lista de espera en v1.5 como moat
**Decisión**: diferenciadores justo después del MVP.
**Contexto**: validación OS (DentalTec) y waitlist auto-fill (NexHealth) son los diferenciales verificados que nadie combina en Latam.
**Justificación**: MVP parity + moat rápido; narrativa comercial clara.
**Trade-offs aceptados**: integración OS sin acuerdos formales es supuesto de riesgo (ver SU-02).

## Supuestos inferidos

### SU-01 — Pacientes prefieren online sobre WhatsApp manual
**Supuesto**: el cambio de hábito ocurrirá si la reserva es simple.
**Origen**: state `discovery.riesgos[0]`, `discovery/discovery.md` §10.
**Riesgo si es falso**: baja adopción del canal online; MVP pierde su apuesta central.
**Cómo validar**: piloto en 2–3 consultorios midiendo % online vs WhatsApp manual antes de v1.5.

### SU-02 — Validación OS integrable sin acuerdos formales
**Supuesto**: se puede consultar afiliado/nomenclador/topes técnicamente.
**Origen**: state `discovery.riesgos[4]`.
**Riesgo si es falso**: US-050 inviable; moat v1.5 se cae.
**Cómo validar**: spike técnico con 2–3 OS grandes en semana 1 de v1.5.

### SU-03 — Un consultorio/sede alcanza para v1
**Supuesto**: multi-sucursal puede esperar a v2.
**Origen**: `10_preguntas_abiertas.md` (pregunta crítica); modelo de datos ya deja `sede` como campo.
**Riesgo si es falso**: refactor de caja/reportes/permisos.
**Cómo validar**: confirmar con primer cliente piloto antes del sprint 1.

### SU-04 — Costos WA + comisiones MP son trasladables
**Supuesto**: el pricing ARS del producto absorbe/traslada costos variables.
**Origen**: riesgos de costo WA y comisiones MP (state `discovery.riesgos`).
**Riesgo si es falso**: margen negativo a escala.
**Cómo validar**: modelo de costos por turno (mensaje + comisión) antes de fijar precio público.
