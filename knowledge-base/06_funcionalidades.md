# Funcionalidades

Organizadas por **épica** y luego por **historia de usuario** (formato US-NNN).

## Épica 1: Agenda y reserva online

### US-001 — Ver disponibilidad real
**Como** paciente **Quiero** ver slots reales por motivo/profesional **Para** elegir sin llamar.
**Criterios de aceptación**:
- [ ] CA-1: Slots derivan de horario − bloqueos − turnos (sin huecos fantasma).
- [ ] CA-2: Link compartible web/redes/QR funciona sin login.
**Reglas relacionadas**: RN-AG-04, RN-PU-03.

### US-002 — Reservar sin cuenta
**Como** paciente **Quiero** reservar con DNI + teléfono **Para** no registrarme.
**Criterios de aceptación**:
- [ ] CA-1: Primera reserva exige verificación por código.
- [ ] CA-2: Recibo token público para gestionar mi turno.
**Reglas relacionadas**: RN-PU-01, RN-PU-02, RN-AG-03.

### US-003 — Confirmar / cancelar / reprogramar (paciente)
**Como** paciente **Quiero** autogestionar mi turno **Para** no depender de recepción.
**Criterios de aceptación**:
- [ ] CA-1: Confirmar/cancelar/reprogramar desde link o WhatsApp.
- [ ] CA-2: Cancelación respeta antelación mínima configurable.
**Reglas relacionadas**: RN-AG-05, RN-AG-07, RN-NO-03.

### US-004 — Agenda día/semana (recepción)
**Como** recepcionista **Quiero** ver y operar la agenda del día/semana **Para** gestionar el flujo del consultorio.
**Criterios de aceptación**:
- [ ] CA-1: Vista día/semana multiprofesional y multisillón.
- [ ] CA-2: Crear, confirmar, reprogramar, check-in y sobreturno auditado.
**Reglas relacionadas**: RN-AG-01, RN-AG-02, RN-AG-06.

## Épica 2: Notificaciones WhatsApp

### US-010 — Recordatorios automáticos
**Como** recepcionista **Quiero** que el sistema envíe confirmación + recordatorios **Para** bajar ausentismo sin trabajo manual.
**Criterios de aceptación**:
- [ ] CA-1: Secuencia inmediata + 24 h + 3 h con plantillas utility.
- [ ] CA-2: Fallback email/SMS si no hay WhatsApp.
**Reglas relacionadas**: RN-NO-01, RN-NO-02, RN-NO-04.

### US-011 — Confirmación conversacional
**Como** paciente **Quiero** confirmar con un "SÍ" por WhatsApp **Para** no abrir la web.
**Criterios de aceptación**:
- [ ] CA-1: El "SÍ" actualiza el estado sin intervención.
- [ ] CA-2: Remitente validado contra teléfono del turno.
**Reglas relacionadas**: RN-NO-03.

## Épica 3: Clínica

### US-020 — Ficha + odontograma + presupuesto en un flujo
**Como** odontólogo **Quiero** registrar ficha, odontograma FDI y presupuesto en una sesión **Para** no cargar dos veces.
**Criterios de aceptación**:
- [ ] CA-1: Odontograma SVG interactivo por pieza/estado.
- [ ] CA-2: Presupuesto nace del odontograma con firma del paciente.
**Reglas relacionadas**: RN-CL-01, RN-CL-02, RN-CL-03.

## Épica 4: Cobros y caja

### US-030 — Seña por Mercado Pago
**Como** administrador **Quiero** cobrar señas con link MP **Para** asegurar ingresos y bajar no-show.
**Criterios de aceptación**:
- [ ] CA-1: Link de pago + webhook con verificación de firma.
- [ ] CA-2: Turno con seña requerida confirma solo al acreditarse.
**Reglas relacionadas**: RN-PA-01, RN-PA-02, RN-PA-03.

### US-031 — Caja con cierre diario
**Como** recepcionista/admin **Quiero** registrar movimientos y cerrar caja **Para** conciliar el día.
**Criterios de aceptación**:
- [ ] CA-1: Ingresos/egresos por método con usuario registrado.
- [ ] CA-2: Un cierre abierto por día/sede; reapertura solo admin auditada.
**Reglas relacionadas**: RN-PA-04, RN-PA-05.

## Épica 5: Administración y reportes

### US-040 — Roles y auditoría
**Como** admin **Quiero** gestionar usuarios/roles y ver auditoría **Para** controlar accesos.
**Criterios de aceptación**:
- [ ] CA-1: RBAC según matriz 03.
- [ ] CA-2: Bitácora de acciones sensibles consultable.
**Reglas relacionadas**: RN-AU-02, RN-AU-03.

### US-041 — Reportes operativos
**Como** admin **Quiero** ver ocupación, ausentismo e ingresos **Para** decidir.
**Criterios de aceptación**:
- [ ] CA-1: Ocupación por profesional/sillón, ausentismo, ingresos por método.
- [ ] CA-2: Exportación CSV.

## Épica 6 (v1.5): Diferenciadores

### US-050 — Validación OS preventiva
**Como** admin **Quiero** validar cobertura antes de atender **Para** evitar débitos.
**Criterios de aceptación**:
- [ ] CA-1: Resultado cubre/parcial/no_cubre con detalle.
- [ ] CA-2: Si no cubre, ofrece flujo particular.
**Reglas relacionadas**: RN-OS-01, RN-OS-02.

### US-051 — Lista de espera inteligente con seña
**Como** recepcionista **Quiero** que un hueco oferte automáticamente a la espera **Para** cubrirlo sin llamar.
**Criterios de aceptación**:
- [ ] CA-1: Scoring + blast WhatsApp + asignación a quien paga seña.
- [ ] CA-2: Expiración de oferta con re-oferta al siguiente.
