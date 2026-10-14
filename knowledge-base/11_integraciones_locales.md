# Integraciones Locales (AR): WhatsApp + Mercado Pago + ARCA

Extra 1X — el dominio lo amerita: las tres integraciones son el moat local (ningún sistema combina OS + ARCA + odontograma + WhatsApp nativo + MP en precio ARS — informe §C.3).

## 1. WhatsApp Cloud API

- **Uso v1**: confirmación inmediata, recordatorios 24 h / 3 h, cancelación/reprogramación conversacional, blast de lista de espera (v1.5). Solo plantillas **utility**; marketing con opt-in aparte (RN-NO-01).
- **Flujo**: número propio por clínica → plantillas aprobadas → webhook entrante con verificación de firma → writeback a agenda (RN-NO-03).
- **Riesgos**: costo por conversación, aprobación de plantillas, dependencia Meta. Mitigación: fallback email/SMS (RN-NO-04), costos modelados en SU-04.
- **Referencias**: informe §D.2 (Doctocliq confirmación que actualiza agenda, Simples confirmación automática); state `discovery.integraciones[0]`.

## 2. Mercado Pago

- **Uso v1**: señas de primera vez / tratamientos largos y de lista de espera (link de pago + Checkout + webhooks). Moneda ARS.
- **Flujo**: preferencia con metadata (turno_id/presupuesto_id) → pago → webhook verificado por firma → idempotencia por `mp_payment_id` → acreditación + movimiento de caja (RN-PA-02/03).
- **Riesgos**: comisiones/retenciones según condición fiscal de cada consultorio. Mitigación: relevar condición fiscal en onboarding; exponer costo en reportes.
- **Referencias**: TuTurno.io (señas MP), DentalSoft (caja multi-método con MP); state `discovery.integraciones[1]`.

## 3. ARCA WSFE (fase 2 / v2)

- **Alcance**: Factura B/C + CAE + QR por sede/punto de venta; comprobantes vinculados a pagos/cierres (`ComprobanteARCA`).
- **Pre-requisitos**: CUIT, certificado fiscal, homologación WSFE, punto de venta por sede.
- **Riesgos**: homologación y cambios normativos. Mitigación: fasear después del MVP (DD-06); spike de homologación al inicio de v2.
- **Referencias**: DentalTec (único con ARCA evidenciado); micrositio https://www.arca.gob.ar/fe/; state `discovery.integraciones[2]`.

## 4. Google Calendar + fallback (v2 / v1)

- **v1**: email/SMTP + SMS gateway como fallback de notificaciones.
- **v2**: Google Calendar bidireccional (OAuth por profesional) + receta electrónica a evaluar.
