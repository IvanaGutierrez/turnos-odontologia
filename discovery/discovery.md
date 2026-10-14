# Discovery — Sistema de turnos odontológicos (Argentina)

**Fecha**: 2026-09-30
**Fuentes investigadas**: 21 sistemas en 3 frentes (Argentina / Latam / Internacional), solo fuentes oficiales verificadas el 30/09/2026. Informe completo: `docs/discovery/informe-discovery.md`.

## 1. Problema que resuelve

Los consultorios y clínicas odontológicas argentinas coordinan turnos por WhatsApp manual, papel o planillas, lo que genera ausentismo, huecos sin cubrir, dobles reservas y horas de gestión administrativa. La oferta existente no resuelve el cuadro completo: o integra obra social y ARCA pero sin experiencia de paciente moderna (DentalTec), o tiene marketing y turnos online pero sin OS ni facturación local (AgendaPro, Dentalink parcial), y casi nadie publica precio ARS ni política de seguridad. El producto ataca ese hueco: gestión integral de turnos + clínica + cobros pensada para Argentina desde el día 1.

## 2. Usuarios / roles

- **Paciente**: reserva, confirma, cancela, reprograma y paga seña sin llamar ni registrarse (DNI + teléfono).
- **Recepcionista**: gestiona la agenda del día, confirma turnos, cobra y reasigna huecos.
- **Odontólogo/profesional**: atiende, registra ficha y odontograma, arma presupuestos y planes.
- **Administrador/dueño**: configura agenda y precios, ve caja y reportes, gestiona usuarios.
- **Obra social / prepaga** (actor externo): cobertura a validar y liquidaciones a conciliar, no usuario directo.

## 3. Casos de uso

1. Como paciente, quiero reservar un turno online sin llamar para no depender del horario de la recepción.
2. Como recepcionista, quiero confirmar y reprogramar turnos por WhatsApp para bajar el ausentismo sin trabajo manual.
3. Como odontólogo, quiero ficha + odontograma + presupuesto en un solo flujo para no cargar dos veces.
4. Como administrador, quiero cobrar señas por Mercado Pago y ver la caja diaria para asegurar ingresos.
5. Como administrador, quiero validar la cobertura de obra social antes de atender para evitar débitos.

## 4. Competidores / soluciones existentes

| Competidor | Problema que resuelve | Pricing | Diferenciadores |
|---|---|---|---|
| Dentalink (CL/AR) | Gestión dental integral multicentro con OS AR | Cotización, sin precio público | Módulo OS AR + IA/notas por voz; opaco en precios |
| DentalTec (AR) | Facturación OS + ARCA con aval CORA | Cotización/demo | Validación OS preventiva + cierre multinivel; débil en particular |
| DentalSoft AR | PyME particular + OS con liquidaciones | No publicado | Cobertura automática + comisiones + web captación |
| AgendaPro (CL/AR) | Marketing + turno online con precio ARS | ARS 13.900–44.900 + WA extra | Retención y reserva sin registro; sin OS/ARCA |
| Doctocliq (PE/Latam) | SaaS multi-país con FE local + IA WhatsApp | USD 19 + plan gratis | FE multi-país, Soyla IA; récord a replicar en AR |
| Doctoralia | Captación de pacientes (canal) | Paciente gratis; pro sin precio AR | +110k doctores y reseñas; no gestiona clínica |
| Referencias UX | Fresha, NexHealth, Doctolib | — | Booking 3 taps, waitlist auto-fill, agenda por motivo |

Detalle completo de 18 sistemas + matriz ponderada en `docs/discovery/informe-discovery.md` (secciones A y B).

## 5. Funcionalidades necesarias

- Agenda multiprofesional y multisillón con prevención de solapamientos, vista día/semana.
- Reserva online 24/7 con link compartible, sin cuenta obligatoria (DNI + teléfono).
- Confirmación, cancelación y reprogramación por el paciente; recordatorios por WhatsApp.
- Ficha clínica + odontograma digital + presupuestos/planes de tratamiento.
- Caja con cierre diario + cobro de señas por Mercado Pago.
- Roles y permisos (administrador / odontólogo / recepción) + auditoría básica.
- Reportes operativos (ocupación, ausentismo, ingresos).

## 6. Funcionalidades opcionales

- Validación de cobertura OS preventiva y lista de espera inteligente con seña (diferenciadores v1.5).
- Facturación electrónica ARCA nativa (v2).
- Periodontograma, ortodoncia, imágenes/Rx con IA (v2+).
- Multi-sucursal, app móvil, marketplace con reseñas, API pública, Google Calendar bidireccional.

## 7. Reglas de negocio

- Un profesional/sillón no puede tener dos turnos superpuestos (propuesta a validar en KB).
- La cancelación exige una antelación mínima configurable por el consultorio.
- Primera vez y tratamientos largos requieren seña para confirmar.
- Todo turno nace de un motivo/prestación con duración asociada (base de la agenda por motivo).

## 8. Integraciones

- WhatsApp Cloud API (plantillas utility para recordatorios/confirmación; marketing con opt-in aparte).
- Mercado Pago (link de pago + Checkout + webhooks para señas).
- ARCA WSFE (fase 2: Factura B/C + CAE + QR por sede/punto de venta).
- Google Calendar bidireccional (v2); email/SMS como fallback (v1).

## 9. Restricciones

- Stack fijo: FastAPI, JWT, SQLAlchemy, PostgreSQL, Redis, Docker/Compose; React + TypeScript + Vite.
- Cumplimiento Ley 25.326 (datos personales) y Ley 26.529 (derechos del paciente e historia clínica).
- Todo en español; despliegue simple en VPS argentino (Docker Compose).
- Este Discovery alimenta a `kb-creator`; nada de lo aquí escrito es decisión de arquitectura final.

## 10. Riesgos

- **Supuesto sin probar**: que los pacientes prefieran reservar online antes que seguir escribiendo por WhatsApp por costumbre — no validado con usuarios reales.
- **Riesgo**: costo y dependencia de WhatsApp Business API (precio por mensaje, número propio por clínica, plantillas).
- **Riesgo**: complejidad de homologación ARCA y volatilidad de nomencladores/valores de obras sociales.
- **Riesgo**: comisiones y retenciones de Mercado Pago según condición fiscal de cada consultorio.
- **Supuesto sin probar**: que la validación OS preventiva sea técnicamente integrable sin acuerdos formales con cada obra social.

## 11. Preguntas abiertas

- ¿La obra social entra en el MVP o en fase 2 como diferenciador temprano?
- ¿El paciente reserva solo con DNI + teléfono o necesita cuenta con login?
- ¿Hay que soportar multi-sucursal desde el día 1 o alcanza un consultorio?
- ¿Cuál es el modelo de precio del producto (suscripción ARS por profesional, por sede, comisión)?
- ¿Se valida el cambio de hábito (online vs WhatsApp manual) con pilotos antes de construir todo?
