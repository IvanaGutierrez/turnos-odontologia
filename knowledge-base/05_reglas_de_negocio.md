# Reglas de Negocio

Cada regla tiene código único `RN-{DOMINIO}-{NN}` para trazabilidad.

## Dominio: Agenda (RN-AG)

- **RN-AG-01**: Un profesional no puede tener dos turnos superpuestos — Exclusion constraint en DB + validación en API (origen: `discovery/discovery.md` §7, a validar en KB).
- **RN-AG-02**: Un sillón no puede tener dos turnos superpuestos cuando el turno requiere sillón.
- **RN-AG-03**: Todo turno nace de una prestación/motivo con duración asociada; `fin = inicio + duración` salvo override con motivo registrado.
- **RN-AG-04**: La reserva solo se ofrece sobre slots reales derivados de horario del profesional menos bloqueos y turnos existentes (agenda por motivo: motivo→duración→profesional→slot).
- **RN-AG-05**: La cancelación exige antelación mínima configurable por consultorio (default sugerido: 12 h; configurable).
- **RN-AG-06**: Sobreturnos solo por rol recepcion/admin y quedan marcados `sobreturno=true` con auditoría.
- **RN-AG-07**: Reprogramación conserva el token público y genera nuevo par inicio/fin; el turno original pasa a `reprogramado` (trazabilidad).

## Dominio: Paciente público (RN-PU)

- **RN-PU-01**: Reserva sin cuenta: identidad = DNI + teléfono; verificación por código WhatsApp/SMS en primera reserva (anti-spam).
- **RN-PU-02**: Token público único por turno para ver/confirmar/cancelar/reprogramar sin login; rotatable ante sospecha de fuga.
- **RN-PU-03**: Rate limit en endpoints públicos (por IP + por teléfono) para evitar scraping y spam de slots.

## Dominio: Señas y caja (RN-PA)

- **RN-PA-01**: Primera vez y tratamientos largos requieren seña para confirmar (monto/porcentaje configurable por prestación).
- **RN-PA-02**: Un turno con seña requerida solo pasa a `confirmado` cuando el pago está `acreditado` (webhook MP verificado por firma).
- **RN-PA-03**: Webhooks MP son idempotentes (mp_payment_id único); reintentos no duplican acreditación.
- **RN-PA-04**: Cierre diario único abierto por día/sede; no se registran movimientos en día cerrado salvo reapertura auditada por admin.
- **RN-PA-05**: Todo egreso/ingreso manual registra usuario y concepto (conciliación MP vs efectivo).

## Dominio: Clínica (RN-CL)

- **RN-CL-01**: Sin consentimiento informado registrado no se crea HCE (Ley 26.529).
- **RN-CL-02**: Odontograma usa nomenclatura FDI (11–48) con catálogo de estados versionado.
- **RN-CL-03**: Presupuesto aprobado con firma del paciente antes de iniciar plan con seña (trazabilidad firma+fecha).
- **RN-CL-04**: Recepción no edita datos clínicos (solo contacto); toda edición clínica registra profesional firmante.

## Dominio: Autenticación y autorización (RN-AU)

- **RN-AU-01**: JWT access corto (15') + refresh rotativo (7 d); logout invalida refresh.
- **RN-AU-02**: RBAC según matriz de `03_actores_y_roles.md`; denegar por defecto.
- **RN-AU-03**: Auditoría obligatoria en: crear/cancelar turno, sobreturno, cobro, cierre, edición clínica, cambio de roles.

## Dominio: Notificaciones (RN-NO)

- **RN-NO-01**: WhatsApp solo con plantillas utility aprobadas para recordatorios/confirmación; marketing exige opt-in aparte.
- **RN-NO-02**: Secuencia default: confirmación inmediata + recordatorio 24 h + aviso 3 h; configurable.
- **RN-NO-03**: El "SÍ" por WhatsApp confirma el turno sin intervención (writeback) solo si el remitente coincide con el teléfono del turno.
- **RN-NO-04**: Email/SMS como fallback cuando el paciente no tiene WhatsApp.

## Dominio: OS v1.5 (RN-OS)

- **RN-OS-01**: Validación preventiva antes de confirmar: cruza afiliado + nomenclador + topes → `cubre|parcial|no_cubre`.
- **RN-OS-02**: Si `no_cubre`, el turno se ofrece como particular con presupuesto antes de confirmar.
- **RN-OS-03**: Liquidaciones agrupan prestaciones por OS y período con export PDF (referencia DentalSoft).

## Dominio: Excepciones globales

- Ninguna regla de UX puede violar Ley 25.326 (datos personales: minimización, consentimiento, exportación) ni Ley 26.529 (integridad de HCE).
- Ante conflicto entre disponibilidad mostrada y constraint DB, la DB manda y el usuario recibe error de slot ocupado con alternativas.
- Todo fallo de integración externa (WA/MP/ARCA) degrada a flujo manual con notificación a recepción, nunca pierde el turno.
