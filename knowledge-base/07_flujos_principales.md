# Flujos Principales

## Flujo 1: Reserva online (paciente sin cuenta)
**Disparador**: paciente abre link/QR. **Actor**: paciente.

**Pasos**:
1. Frontend muestra prestaciones (motivo) → paciente elige motivo.
2. Frontend pide disponibilidad (motivo→duración→profesional→slot) a la API.
3. Paciente elige slot e ingresa DNI + teléfono (+ código de verificación si primera vez).
4. API valida solapamiento y crea turno `reservado` con token público; si la prestación exige seña, crea preferencia MP y devuelve link de pago.
5. Worker envía confirmación por WhatsApp con botones/links (confirmar, pagar seña, cancelar).

**Casos de error**:
- Slot tomado en concurrente → DB rechaza (exclusion), API devuelve 409 + slots alternativos.
- Verificación fallida → reintento limitado + bloqueo temporal.
- MP caído → turno queda `reservado` pendiente de seña + aviso a recepción.

## Flujo 2: Confirmación por WhatsApp (writeback)
**Disparador**: mensaje del paciente. **Actor**: paciente.

**Pasos**:
1. Webhook WhatsApp recibe mensaje + valida firma.
2. API identifica turno por remitente + contexto; interpreta confirmar/cancelar/reprogramar.
3. Si confirma y no exige seña (o ya acreditada) → `confirmado`; si exige seña pendiente → responde con link MP.
4. Agenda se actualiza sin intervención; worker agenda recordatorios 24 h / 3 h.

**Casos de error**:
- Remitente desconocido → respuesta con link de gestión, sin mutar nada.
- Cancelación fuera de antelación → rechazo con política del consultorio.

## Flujo 3: Atención clínica (odontólogo)
**Disparador**: check-in en recepción (`presente`). **Actor**: odontólogo.

**Pasos**:
1. Odontólogo abre ficha del paciente (verifica consentimiento Ley 26.529).
2. Registra anamnesis/evolución + odontograma FDI por pieza/estado.
3. Genera presupuesto desde hallazgos + plan por etapas; paciente firma (táctil/registro).
4. Si aplica, genera link de seña MP del plan; turno pasa a `atendido`.

## Flujo 4: Cobro de seña Mercado Pago
**Disparador**: seña requerida o plan aprobado. **Actor**: paciente + sistema.

**Pasos**:
1. API crea preferencia MP (monto, concepto, metadata turno_id) → link al paciente.
2. Paciente paga en MP; webhook `mercadopago` llega con firma.
3. API verifica firma, idempotencia por mp_payment_id, marca pago `acreditado`, turno → `confirmado`, movimiento de caja MP.
4. Worker envía comprobante por WhatsApp.

```
Paciente → Frontend → API → Mercado Pago
Paciente → MP (paga) → Webhook → API (verifica) → DB (acredita) → WhatsApp (comprobante)
```

**Casos de error**:
- Webhook duplicado → 200 sin doble acreditación.
- Pago rechazado → estado visible + reintento; turno sigue pendiente.

## Flujo 5: Lista de espera inteligente (v1.5)
**Disparador**: cancelación libera hueco. **Actor**: sistema + recepción.

**Pasos**:
1. Worker detecta hueco y ranquea espera (distancia, historial, valor tratamiento).
2. Blast WhatsApp al top-N con oferta expirable + link de seña.
3. Quien paga primero toma el slot (`asignada`); resto vuelve a `activa`.
4. Caja registra seña; agenda notifica a recepción.

## Flujo 6: Cierre de caja diario
**Disparador**: fin de jornada. **Actor**: recepción/admin.

**Pasos**:
1. Recepción lista movimientos (efectivo + MP + otros) del día.
2. Sistema compara totales vs pagos acreditados; marca diferencias.
3. Admin/recepción cierra; día queda bloqueado; reapertura solo admin con auditoría.
