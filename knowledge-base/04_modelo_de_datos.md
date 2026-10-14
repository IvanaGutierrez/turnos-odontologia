# Modelo de Datos

## Dominios

- **Identidad y acceso**: usuarios internos, roles, sesiones/refresh, auditoría.
- **Pacientes**: datos personales (Ley 25.326), consentimientos (Ley 26.529), afiliaciones OS.
- **Agenda**: profesionales, sillones/recursos, prestaciones (motivo + duración), horarios/bloqueos, turnos, lista de espera.
- **Clínica**: fichas/HCE, odontograma por pieza/estado, evoluciones, presupuestos, planes de tratamiento.
- **Cobros**: pagos (señas MP), movimientos de caja, cierres diarios.
- **OS (v1.5)**: obras sociales, afiliados, validaciones de cobertura, liquidaciones.
- **Facturación (v2)**: comprobantes ARCA, CAE, QR por sede/punto de venta.

## ERD (textual)

```
Usuario(1)──< Turno >──(1)Paciente; Turno >──(1)Prestacion(motivo+duracion)
Turno >──(1)Profesional; Turno >──(0..1)Sillon; Profesional(1)──<Horario/Bloqueo
Paciente(1)──<Ficha──<Evolucion; Ficha(1)──<OdontogramaEntry(pieza+estado FDI)
Paciente(1)──<Presupuesto──<PresupuestoItem──(0..1)PlanTratamiento
Paciente(1)──<Pago──(0..1)Turno; Pago──(0..1)MovimientoCaja──(1)CierreDiario
Paciente(1)──<AfiliacionOS──(1)ObraSocial (v1.5); ValidacionCobertura──(1)Turno (v1.5)
ComprobanteARCA──(1)Pago/Cierre (v2); Usuario(1)──<AuditoriaLog
```

Regla física transversal: constraint de no-solapamiento por (profesional, rango) y (sillón, rango) donde aplique.

## Entidades

### Usuario
- Atributos: id (uuid), nombre, email (único), password_hash, rol (admin|odontologo|recepcion), activo, created_at.
- Relaciones: 1—N Turno (como profesional, si rol odontólogo), 1—N AuditoriaLog.
- Constraints: email único; rol en enum. Índices: email, rol+activo.

### Paciente
- Atributos: id, dni (único por consultorio), nombre, teléfono (E.164 AR), email?, fecha_nac?, obra_social_id?, nro_afiliado?, consentimiento_hc (bool + fecha), created_at.
- Relaciones: 1—N Turno, Ficha, Presupuesto, Pago, AfiliacionOS.
- Constraints: DNI válido AR; teléfono válido; consentimiento obligatorio antes de HCE (Ley 26.529). Índices: dni, teléfono.

### Profesional
- Atributos: id, usuario_id (FK, 1-1), especialidad, matricula?, duracion_default?, activo.
- Relaciones: 1—N Horario, Bloqueo, Turno.

### Sillon (recurso)
- Atributos: id, nombre, sede (v1: única), activo.

### Prestacion (motivo)
- Atributos: id, nombre (motivo), duracion_min, precio_base?, requiere_sena (bool), activa.
- Todo turno nace de una prestación (base de agenda por motivo, referencia Doctolib).

### Turno
- Atributos: id, paciente_id, profesional_id, sillon_id?, prestacion_id, inicio, fin, estado (reservado|confirmado|presente|atendido|cancelado|ausente|reprogramado), canal (web|recepcion|whatsapp|lista_espera), token_publico (único), sena_pago_id?, created_at.
- Constraints: `fin = inicio + prestacion.duracion` (salvo override justificado); exclusion de solapamiento por profesional y por sillón (Postgres `EXCLUDE USING gist`); transición de estados válida. Índices: (profesional_id, inicio), (sillon_id, inicio), token_publico, estado.

### ListaEspera
- Atributos: id, paciente_id, prestacion_id, profesional_id?, ventana_desde/hasta, score?, estado (activa|ofertada|asignada|expirada), created_at.

### Ficha (HCE)
- Atributos: id, paciente_id, profesional_id, anamnesis (jsonb), fecha, firma_profesional.
- Relaciones: 1—N Evolucion, OdontogramaEntry.

### OdontogramaEntry
- Atributos: id, ficha_id, pieza_fdi (11–48), estado (sano|cariado|obturado|endodoncia|corona|implante|extraccion|ausente|... 18 estados ref. DentalSoft), cara?, fecha.
- Índices: (ficha_id, pieza_fdi).

### Presupuesto / PresupuestoItem / PlanTratamiento
- Presupuesto: id, paciente_id, profesional_id, total, sena_requerida, estado (borrador|aprobado|rechazado|pagado_parcial|pagado), firma_paciente?, created_at.
- Item: presupuesto_id, prestacion_id/pieza, cantidad, precio_unitario.
- Plan: presupuesto_id, etapas (jsonb), estado.

### Pago
- Atributos: id, paciente_id, turno_id?, presupuesto_id?, monto, moneda (ARS), metodo (mercadopago|efectivo|transferencia|tarjeta), estado (pendiente|acreditado|rechazado|reembolsado), mp_payment_id?, mp_preference_id?, webhook_recibido_at?.
- Índices: mp_payment_id único, turno_id.

### MovimientoCaja / CierreDiario
- Movimiento: id, caja_id?, tipo (ingreso|egreso), concepto, monto, metodo, usuario_id, fecha.
- Cierre: id, fecha, sede, total_efectivo, total_mp, total_otros, diferencia, cerrado_por, cerrado_at. Constraint: un cierre abierto por día/sede.

### ObraSocial / AfiliacionOS / ValidacionCobertura (v1.5)
- ObraSocial: id, nombre, nomenclador (jsonb), topes (jsonb).
- Afiliación: paciente_id, obra_social_id, nro_afiliado, vigencia.
- Validación: turno_id, resultado (cubre|parcial|no_cubre), detalle (jsonb), fecha.

### ComprobanteARCA (v2)
- Atributos: id, tipo (B|C), punto_venta, numero, cae, cae_vto, qr_payload, pago_id?, created_at.

### AuditoriaLog
- Atributos: id, usuario_id?, accion, entidad, entidad_id, diff (jsonb), ip?, created_at. Índice: (entidad, entidad_id).

## Seed data inicial

- Roles + usuario admin inicial (credenciales a rotar en primer login).
- 1 sede "Consultorio" + 1 sillón demo.
- Catálogo mínimo de prestaciones con duración: consulta (30'), limpieza (45'), endodoncia (60'), extracción (45'), ortodoncia control (30'), urgencia (20').
- Plantillas WhatsApp utility (confirmación, recordatorio 24h, cancelación, oferta lista de espera).
- Profesional y paciente de prueba (marcados `demo`).
