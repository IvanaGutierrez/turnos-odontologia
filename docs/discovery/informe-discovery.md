# Informe Discovery — Sistema de gestión odontológica con turnos (Argentina)

**Fecha de consulta**: 30/09/2026
**Método**: investigación web exhaustiva en tres frentes (Argentina / Latinoamérica / Internacional) con verificación en fuentes oficiales.
**Criterio de evidencia**: solo se consigna como funcionalidad aquello demostrado en fuentes públicas verificables (sitio oficial, documentación, centro de ayuda, precios publicados, marketplaces y reseñas verificadas). Lo no demostrado se consigna como **"No evidenciado"**. Se distingue siempre entre **HECHO verificado** y **afirmación comercial del proveedor**.
**Stack objetivo del producto**: Backend Python + FastAPI + JWT + SQLAlchemy + PostgreSQL + Redis + Docker/Compose · Frontend React + TypeScript + Vite.

---

## A. Tabla comparativa (18 sistemas, ordenados por relevancia para Argentina)

| # | Sistema / Empresa / País / URL | Segmento | Modalidad | Agenda y turnos | Clínico | Admin / cobros | Integraciones locales | Modelo comercial | Diferencial / limitación clave |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **DentalTec** — Tándem Digital — Argentina — https://web.dentaltec.com.ar/ | Independiente, consultorio, clínica; diferencial: Círculos/Federaciones/CORA | SaaS 100 % web | Agenda por odontólogo, turnos configurables, confirmación por WhatsApp. Multisillón/bloqueos/sobreturnos: No evidenciado | Odontograma FDI interactivo + HCE + CIE-10 (claim). Periodontograma/Rx: No evidenciado | HECHO diferencial: validación OS preventiva en tiempo real (+15 OS vía SOAP), facturación automática + ARCA, cierre multinivel Círculo→Federación→CORA, re-facturación, auditoría previa. Caja particular/MP/señas: No evidenciado | Web services OS + ARCA + WhatsApp (recordatorios). API/GCal/firma: No evidenciado | A cotizar/demo. Sin plan gratuito evidenciado | Único con flujo OS+CORA+ARCA y aval institucional (CORA 08/09/2025). Marketing auto-comparativo sin metodología pública; débil en paciente particular |
| 2 | **Dentalink** — Healthatom — Chile (fuerte AR) — https://www.softwaredentalink.com/ | Independiente a cadena/multicentro, dental exclusivo | SaaS 100 % web | Multiusuario, multicentro, evita sobreagendamiento, reserva online + link RRSS, confirmación mail/WhatsApp, reprogramación. Lista de espera: No evidenciado | Ficha/HC digital, odontograma + periodontograma, presupuestos, planes, ortodoncia y estética facial, notas por voz IA, imágenes/Rx | Pagos, caja, gastos, inventario, comisiones, informes; gestión Obras Sociales AR (art. ayuda feb-2026). Facturación ARCA y Mercado Pago nativo: No evidenciado | API oficial, WhatsApp, email (+ Contact Center IA 24/7 adicional). GCal/ARCA/firma: No evidenciado | Cotización mensual/semestral/anual; solo demo, sin plan gratuito | Gestión integral + multicentro + IA más maduro; opacidad de precios AR; claims de adopción inconsistentes entre fuentes |
| 3 | **DentalSoft** — Equipo argentino — Argentina — https://dentalsoft.com.ar/ | Consultorio 1 sillón a clínica PyME multi-profesional | SaaS 100 % nube | Agenda conectada a reserva web 24/7 (4 pasos, slots reales, DNI), multi-profesional por especialidad/OS, confirmación WhatsApp + chatbot FAQ. Cancelación/lista de espera: No evidenciado | HCE, odontograma SVG FDI 18 estados, plan con prioridades, ortodoncia/alineadores, presupuestos con cobertura OS aplicada. Periodontograma/DICOM: No evidenciado | HECHO diferencial: cobertura OS automática, separa paciente vs OS, liquidación OS agrupada con PDF, comisiones, caja multi-método (incluye MercadoPago). Facturación ARCA: No evidenciado | Mercado Pago, WhatsApp. GCal/API/ARCA/firma: No evidenciado | No publicados (demo a coordinar) | Mejor encaje PyME particular+OS; sin evidencia de seguridad/normativa ni facturación fiscal; claim 300+ clínicas sin casos nominales |
| 4 | **AgendaPro** — AgendaPro — Chile (operación AR) — https://agendapro.com/ar | Independiente a cadena; origen belleza/spa adaptado | SaaS web + app iOS/Android | Multi-profesional/especialidad, bloqueo horarios, reserva online sin registro, link RRSS, cambios/cancelaciones instantáneas, reprogramación desde WhatsApp, teleconsulta. Lista de espera automática: ausente | Ficha adaptable + odontograma básico solo en planes altos. HCE/periodonto/Rx/presupuestos digitales: débil o No evidenciado | Señas/pagos integrados, caja, inventario, comisiones, presupuestos, giftcards, reportes, marketing. OS/ARCA/liquidaciones: No evidenciado | WhatsApp add-on pago, Meta Pixel, API solo plan Pro. GCal/MP nativo/AFIP: No evidenciado | HECHO: Individual ARS 13.900 / Básico 33.900 / Premium 44.900 / Pro 314.900 (IVA incl.) + WhatsApp desde ARS 7.900/50 mensajes. Trial 7 días | Mejor marketing/retención con precio ARS público; odontología superficial; costo WhatsApp extra |
| 5 | **Doctocliq** — Doctocliq — Perú (+20 países, declara AR) — https://www.doctocliq.com/ | Independiente a consultorio mediano, multidisciplinario | SaaS online + app iOS/Android | Reserva online 24/7 con link y pago previo opcional, confirmación/cancelación desde WhatsApp/email con actualización automática, recordatorios 3d/1d, integración Google Calendar. Lista de espera: No evidenciada | HC por especialidad, odontograma + periodontograma, ortodoncia, estética, presupuestos, recetas con firma electrónica, consentimientos, laboratorio. Rx: solo adjuntos | Multicaja, comisiones, reportes; facturación electrónica PE/MX/CO/EC (adicional). Convenios odontológicos y pasarela local nombrada: No evidenciado | WhatsApp API oficial, Google Calendar, Zoom, Kommo, API de citas. MP/ARCA: No evidenciado | Plan GRATIS (1 doctor, 30 pac./citas) + trial 7 días; Individual USD 19/mes | Único multi-Latam con FE local real + IA "Soyla" 24/7; recordatorios por créditos; claims de impacto sin auditoría |
| 6 | **OdontoSoft Millennium** — GB Systems — Argentina — https://gbsystems.com/os/ | Independiente a gran clínica, todas las especialidades | Local/instalado Windows (desde 1995); híbrido solo con módulo web opcional | Agenda flexible multi-terminal con anti-superposición, acceso HC 1 clic. Reserva online/WhatsApp/sobreturnos: No evidenciado | HECHO diferencial: HC + anamnesis ilimitada, odontogramas inicial/actual, periodontograma color, endodoncia/orto/implantes/cirugía, recetas | Cuenta corriente, pagos/tarjetas, convenios, facturación, inventario, laboratorios, consolidador multi-clínica. MP/ARCA/OS detalladas: No evidenciado | Identificador de llamadas, biometría opcional. WA/GCal/MP/AFIP/firma: No evidenciado | No evidenciado (licencia aparente) | Profundidad clínica legacy máxima; arquitectura pre-nube sin turno online ni app: referencia de qué no hacer |
| 7 | **Dentario** — Dentario — Argentina — https://www.dentario.com.ar/ | Independiente y consultorio pequeño-mediano | SaaS nube; trial Pro 30 días sin tarjeta | Turnos/agenda + caja (solo Pro), recordatorios por email. Reserva online/WA/lista de espera: No evidenciado | HCE + odontograma + evolución por pieza + seguimiento fotográfico, pacientes ilimitados | Presupuestos, cuentas corrientes, caja; MP solo para pagar la suscripción. OS/ARCA/MP pacientes: No evidenciado | MP (suscripción). WA/GCal/API/AFIP: No evidenciado | HECHO transparente: Gratis (lectura) / Basic ARS 30.000 / Pro ARS 50.000 + ARS 1.500 por tomografía | Entrada más barata y transparente; agenda débil sin WhatsApp ni OS |
| 8 | **Doctoralia AR** — Docplanner — España/Polonia — https://www.doctoraliar.com/ | Profesional/centro que necesita captación (canal, no gestión) | Marketplace web + app + agenda sincronizada; paciente gratis | Reserva online, confirmación + SMS, filtro por OS (OSDE, OSECAC, OBSBA…), precios visibles, videoconsulta. Lista de espera: No evidenciado | No evidenciado (solo perfil + opiniones) | No evidenciado (solo muestra cobertura y pago en efectivo) | Sincronización con agenda propia. WA API/GCal/MP/AFIP: No evidenciado | Paciente gratis; profesional con planes (precios AR no publicados) | +110k doctores, 822 opiniones en ficha odontológica CABA: mejor vidriera, no sustituye gestión |
| 9 | **Argensoft (ArgenSalud/SITA/MisTurnos)** — Argensoft — Argentina (Córdoba) — https://argensoft.net/ | Clínicas, sanatorios, centros multidisciplinarios (no dental puro) | Híbrida: escritorio + nube + apps paciente/médico | Agenda online tiempo real multi-profesional, entreturnos, confirmación/cancelación, notificaciones. Vocabulario multisillón: No evidenciado | HCE, odontograma y presupuestos básicos. Periodonto/ortodoncia/Rx: No evidenciado | Facturación, admisión, caja, +25 módulos; facturación prepagas/OS (claim). MP/ARCA/señas: No evidenciado | No evidenciado (WA API, GCal, MP, AFIP, firma, API) | A cotizar; paciente gratis | Red multi-sede probada (+300 sucursales claim, 11+ años); genérico salud, sin odontología profunda |
| 10 | **TuTurno.io** — TuTurno.io — Argentina (La Plata) — https://www.tuturno.io/ | Independiente, consultorio/centro pequeño, estética | SaaS web app (PWA) | Agenda configurable multi-calendario, link + QR reserva 24/7, confirmación email. Bloqueos/sobreturnos/lista: No evidenciado | No evidenciado (solo recetas vía integración Recetario) | HECHO: señas online vía Mercado Pago. Caja/facturación/OS/reportes: No evidenciado | Mercado Pago, Recetario, botón web. GCal/AFIP/API: No evidenciado | No publicados; trial 30 días sin tarjeta | Agenda + señas MP simple y barata; no es software odontológico |
| 11 | **DentiDesk** — DentiDesk SpA — Chile — https://www.dentidesk.com/ | Consultorios, clínicas, redes, académico | SaaS nube + app Android (2.8★) | Agenda personalizable, widget online (web/RRSS/WA/QR, validación RUT), multisucursal. Duración variable/bloqueos/sobreturnos: No evidenciado | Fichas por especialidad (orto, endo, perio, cirugía), odontograma triple nomenclatura, presupuestos, firma digital. Periodontograma/Rx: No evidenciado | Facturación integrada SII chileno, convenios, stock, 20+ reportes, comisiones. Pagos online: No evidenciado | SII + agendamiento online. WhatsApp automático: anunciado como "próximo", hoy solo manual | Trial 15 días; precios no publicados | Odonto puro con SII nativo; gap crítico: sin WhatsApp automático |
| 12 | **Simples Dental** — Simples Dental — Brasil — https://simplesdental.com/ | Autónomo a red/franquicia, 100 % odonto | SaaS nube + apps (4.8★ iOS) + Alexa + Secretária IA WhatsApp | Agenda online, confirmación automática WhatsApp, encaixes, multi-profesional. Anti-solapamiento/duración/bloqueos: No evidenciado | Prontuario, odontograma, anamnesis, imágenes, receituario con firma electrónica válida. Periodonto/orto: No evidenciado | Financiero completo (flujo caja, boletos, Pix, cartão, comisiones, cobranza automática). NF-e/convenios: No evidenciado | WhatsApp, Alexa, Pix/boletos. GCal/API: No evidenciado | Trial 7 días; entrada ~R$149,90/mes (vía comparador) | Escala real + financiero brasileño + firma jurídica; Brasil-céntrico (portugués/Pix) |
| 13 | **SaludTools** — SaludTools S.A.S. — Colombia — https://www.saludtools.com/ | Médico general/IPS (no odontológico) | SaaS nube + telemedicina | Agenda online multi-dispositivo, portal paciente, GCal, notificaciones WhatsApp. Multisillón/bloqueos: No evidenciado | HC personalizable + IA por voz + RIPS automáticos. Odontograma/presupuestos odonto: No evidenciado (gap bloqueante) | FE DIAN + RIPS, EPS/prepagas, integración Siigo. Pagos locales: No evidenciado | GCal, WhatsApp, Siigo, Doctoralia, API (Premium). MP: No aplica | HECHO: Standard COP 89.000 / Plus 147.000 / Premium 168.000 por médico/mes | Cumplimiento CO + IA voz ejemplar; no dental: referencia de compliance, no competidor |
| 14 | **CareStack** — Good Methods (Straumann) — EEUU — https://carestack.com/ | DSO/grupos + privada + especialidades | SaaS all-in-one cloud | Self-scheduling online, recordatorios, two-way texting, kiosco, Reserve with Google, portal + forms | Charting general/perio, templates, planes con e-signature, imágenes, eRx, implantes, laboratorio, teleodontología | CS Pay, card-on-file, claims, elegibilidad, statements, financiación, payroll. Lo más completo en RCM | 27M+ API calls (programa partners). Docs abiertas: No evidenciado | No publicado (enterprise) | Vara funcional + compliance (HIPAA/SOC2/ISO/GDPR verificados); overkill y cero fit AR |
| 15 | **Curve Dental** — Curve Dental — EEUU/Canadá — https://www.curvedental.com/ | Startup, single y multi-location | SaaS cloud nativo (desde 2004) | Scheduling, GRO engagement, recare, reminders, Smart Forms, online booking, mobile | Charting, perio, imaging, planes, ePrescribe, IA en Rx. Inversión USD 200M R&D anunciada | Curve Pay, billing, insurance, membership plans | Partner list (API abierta: No evidenciado) | No publicado; "100k+ usuarios, 6.000+ sedes" (verificado en home) | Mejor referencia de SaaS puro: copiar flujo schedule→intake→care→collect→grow |
| 16 | **NexHealth** — NexHealth — EEUU — https://www.nexhealth.com/ | Capa de experiencia sobre PMS existente (no PMS) | SaaS overlay + API-first con docs públicas | HECHO mejor en clase: booking real-time (web/Google/social), Waitlist/ASAP auto-fill, reminders, recalls 1-clic, forms, mensajería unificada | Nula (sincroniza con el PMS) | Pagos que postean al ledger, elegibilidad automática 24 h antes, analytics | Synchronizer + Health Records API con docs y pricing ("20.000+ prácticas") | No publicado | Modelo a imitar en AR (ganar por UX + waitlist sin rip-and-replace); costo extra sobre PMS |
| 17 | **Open Dental** — Open Dental Software — EEUU — https://www.opendental.com/ | PyME precio bajo, alta customización | On-premise + Cloud; licencia propietaria | Web Sched, eReminders, eClipboard, Web Forms, portal, texting, Message-to-Pay | Tooth Chart 3D, perio, eRx, queries custom; conversión desde 200+ PMS | Reports, portal de pagos, statements; sin procesador nativo | Bridges documentados (no open API masiva) | HECHO: USD 199/mes por sede (12 meses, hasta 3 dentistas) | Vara costo/funcionalidad para producto AR económico; UX datada |
| 18 | **Fresha** — Fresha.com SV — UK — https://www.fresha.com/ | Salones/spa/medspa (no dental) | Marketplace + SaaS freemium | Booking 24/7 marketplace/web/Google/social, reminders, depósitos anti-no-show, rebooking, reviews | No odontológica | POS, checkout, tips, upsell; % comisión no verificado | API pública: No evidenciado | Base free + comisión marketplace; trial 7 días | Referencia UX Nº1: búsqueda→precio→slot→seña→pago→review en 3 taps (130k+ negocios, 1B+ reservas) |

**Referencias adicionales relevadas** (fuera de tabla por no ser competidores directos): Dentrix/Dentrix Ascend (Henry Schein, EEUU — líder instalado + IA clínica/RCM, pricing opaco, foco seguros EEUU); Eaglesoft/Fuse (Patterson, EEUU — legacy on-premise, referencia de qué no hacer); Planet DDS Denticon (EEUU — estándar oro multi-sede, Quick Fill + AI Agents, enterprise); Doctolib (Francia — gold standard EU agenda por motivo); Zocdoc (EEUU — marketplace); Dentalis (Brasil — banca integrada + BI red, portugués, opaco); DentalSoft Chile (legacy sin evidencia, no recomendable); Doctoralia Pro MX/CO (captación + Noa Booking + lista de espera inteligente, sin gestión dental).
**Pistas descartadas por falta de evidencia** (30/09/2026): Nubimed (UE sin operación AR), NubeClinic (clínica, no software), BoxMagic (fitness), Simed/Softmedic (otros rubros), Odontotech AR (instrumental), Medisso/ControllDent/OrtoManager (sin operación Latam verificable).

---

## B. Matriz de puntuación (0–5 por dimensión)

**Pesos**: Gestión de turnos y automatización 25 % · Funcionalidad odontológica clínica 20 % · Integraciones locales y WhatsApp 15 % · Administración, cobros y facturación 15 % · Experiencia del paciente 10 % · Seguridad, exportación y trazabilidad 10 % · Precio y facilidad de adopción 5 %.
**Advertencia**: el puntaje mide capacidad funcional global; la *relevancia para Argentina* (tabla A) pondera además encaje local (OS, ARCA, MP, ARS, presencia). Por eso el orden difiere.

| Sistema | Turnos 25 % | Clínica 20 % | Integrac. 15 % | Admin 15 % | Exp.pac. 10 % | Segurid. 10 % | Precio 5 % | **Total /5** |
|---|---|---|---|---|---|---|---|---|
| Doctocliq | 5 | 4 | 4 | 4 | 4 | 2 | 4 | **4.05** |
| CareStack | 4 | 5 | 2 | 5 | 4 | 5 | 1 | **4.00** |
| Dentalink | 4 | 5 | 3 | 4 | 4 | 4 | 2 | **3.95** |
| Dentrix Ascend | 4 | 5 | 1 | 4 | 3 | 4 | 1 | **3.50** |
| Simples Dental | 4 | 3 | 3 | 4 | 4 | 2 | 3 | **3.40** |
| DentalTec | 3 | 3 | 4 | 5 | 3 | 2 | 2 | **3.30** |
| DentalSoft AR | 3 | 4 | 3 | 4 | 4 | 1 | 3 | **3.25** |
| Curve Dental | 4 | 4 | 1 | 3 | 4 | 3 | 2 | **3.20** |
| DentiDesk | 3 | 4 | 2 | 4 | 3 | 2 | 3 | **3.10** |
| AgendaPro | 4 | 2 | 3 | 3 | 4 | 1 | 4 | **3.00** |
| Open Dental | 3 | 4 | 2 | 3 | 2 | 3 | 4 | **3.00** |
| NexHealth | 5 | 1 | 1 | 3 | 5 | 3 | 1 | **2.90** |
| Argensoft | 4 | 2 | 1 | 3 | 4 | 2 | 2 | **2.70** |
| Fresha | 4 | 0 | 1 | 2 | 5 | 2 | 4 | **2.35** |
| SaludTools | 3 | 0 | 2 | 4 | 3 | 2 | 3 | **2.30** |
| Dentario | 2 | 3 | 2 | 2 | 2 | 1 | 5 | **2.25** |
| OdontoSoft Mill. | 1 | 5 | 1 | 3 | 1 | 2 | 2 | **2.25** |
| Doctoralia AR | 3 | 0 | 2 | 1 | 5 | 2 | 2 | **2.00** |
| TuTurno.io | 3 | 0 | 2 | 1 | 3 | 1 | 3 | **1.75** |

*Lectura*: el pelotón internacional lidera en clínica y seguridad pero colapsa en integraciones locales; el pelotón argentino lidera en encaje OS/ARCA pero pierde en automatización, transparencia de precios y seguridad declarada. La brecha entre ambos pelotones es el espacio del producto.

---

## C. Análisis competitivo

### C.1. Funcionalidades estándar de mercado (lo que el producto DEBE tener día 1 para no correr de atrás)

1. Agenda multi-profesional con vista día/semana y reserva online 24/7 con link compartible.
2. Confirmación, cancelación y reprogramación por el paciente sin llamar.
3. Recordatorios automáticos (al menos email/SMS; WhatsApp es el estándar esperado en Latam).
4. Ficha clínica + odontograma digital + presupuestos/planes de tratamiento.
5. Caja con cierre diario, cuentas corrientes y reportes básicos.
6. Roles y permisos mínimos (admin / profesional / recepción).
7. Reserva con seña o pago anticipado para bajar el no-show (Fresha, AgendaPro, TuTurno.io lo normalizaron).

### C.2. Diferenciadores reales (los tiene uno o pocos, verificados)

1. **Validación de cobertura OS preventiva** (DentalTec): cruza afiliado/nomenclador/topes antes de atender; ataca los débitos, el dolor Nº1 de quien factura OS.
2. **Lista de espera inteligente con auto-reasignación** (NexHealth Waitlist/ASAP, Denticon Quick Fill, Noa Booking): hueco libre → reasignación automática. En Latam solo existe manual.
3. **Confirmación que actualiza la agenda desde el mensaje** (Doctocliq, Simples): el "sí" del paciente por WhatsApp confirma sin intervención.
4. **Planes de tratamiento con firma electrónica + pago en el mismo flujo** (CareStack e-sign + CS Pay, Simples firma con validez jurídica).
5. **Facturación electrónica local embebida** (SII/SUNAT/SAT/DIAN según país; ARCA en AR solo DentalTec): elimina el sistema paralelo de facturación.
6. **IA aplicada real**: notas por voz (Dentalink, SaludTools), agentes que agendan 24/7 (Noa, Soyla), IA en Rx (Ascend, Pearl/Overjet vía Planet DDS).

### C.3. Vacíos frecuentes del mercado argentino

1. Ningún sistema combina validación OS preventiva + ARCA + odontograma avanzado + WhatsApp nativo incluido + Mercado Pago en un precio ARS público.
2. WhatsApp es add-on pago o email-only en casi todos; falta agendamiento conversacional con reprogramación, lista de espera y seña dentro del chat, en pesos.
3. Seguridad y normativa AR opacas: casi nadie publica postura sobre Ley 25.326, consentimiento Ley 26.529, cifrado, backup, auditoría, exportación y SLA.
4. Interoperabilidad nula: sin Google Calendar bidireccional, sin API abierta, sin receta electrónica odontológica ni firma digital evidenciadas.

### C.4. Oportunidades de innovación para el nuevo sistema

1. **Lista de espera inteligente con seña por Mercado Pago**: scoring (distancia, historial, valor del tratamiento) → blast por WhatsApp → quien paga la seña toma el slot → comprobante/CAE automático. Nadie en Latam lo hace.
2. **Pre-cita con IA + riesgo de no-show**: formularios + foto/Rx previa → resumen clínico + score de ausentismo → sobreturno sugerido + recordatorio diferenciado. Piezas sueltas en EEUU, nadie las une con WhatsApp + cobro en Latam.
3. **Plan de tratamiento firmable y financiable en un flujo**: odontograma → PDF con firma táctil + QR fiscal + link de Mercado Pago en cuotas + recordatorio de saldo + pedido de reseña automático. CareStack marca la vara; replicarlo con MP + FE + WhatsApp es diferencial vendible en AR.
4. **Transparencia radical como estrategia**: precio ARS público, política de privacidad y seguridad publicada, exportación de datos garantizada. Todo lo que la competencia oculta.

---

## D. Recomendación final

### D.1. Cinco competidores prioritarios para demo

1. **Dentalink** (https://www.softwaredentalink.com/) — Observar: módulo OS AR, multicentro, IA/notas por voz, onboarding. Preguntar: precio AR real, costo del Contact Center IA, exportación y SLA.
2. **DentalTec** (https://web.dentaltec.com.ar/) — Observar: validación OS preventiva, flujo CORA, facturación ARCA. Preguntar: precio, reglas exactas de validación, qué pasa con paciente particular.
3. **DentalSoft AR** (https://dentalsoft.com.ar/) — Observar: cobertura OS automática, liquidaciones, comisiones, web de captación. Preguntar: precio, seguridad/backup, roadmap ARCA.
4. **Doctocliq** (https://www.doctocliq.com/) — Observar: confirmación por WhatsApp que actualiza agenda, Soyla IA, FE multi-país, plan gratuito como adquisición. Preguntar: cobertura AR real, costo de créditos WhatsApp a escala.
5. **AgendaPro** (https://agendapro.com/ar) — Observar: marketing/retención, reserva sin registro, doble confirmación, pricing ARS transparente. Preguntar: costo total con WhatsApp, profundidad real del odontograma.

### D.2. Tres productos de referencia para experiencia de usuario

1. **Fresha** (https://www.fresha.com/) — booking en 3 taps + seña anti-no-show + marketplace que trae demanda.
2. **NexHealth** (https://www.nexhealth.com/) — waitlist ASAP con auto-fill + recalls en 1 clic + inbox único + writeback sin doble carga.
3. **Doctolib** (https://www.doctolib.com/) — agenda por motivo (motivo→duración→profesional→slot) + recordatorios + cancelación transparente en entorno regulado (GDPR).

### D.3. MVP sugerido

**Imprescindibles (v1)**:
- Agenda multiprofesional y multisillón con prevención de solapamientos, vista día/semana.
- Reserva online 24/7 con link compartible (web/redes/QR); el paciente reserva sin cuenta (DNI + teléfono).
- Confirmación, cancelación y reprogramación por el paciente; recordatorios por WhatsApp (Cloud API, plantillas utility).
- Ficha clínica + odontograma digital + presupuestos/planes de tratamiento.
- Caja con cierre diario + cobro de señas por Mercado Pago (link de pago + webhook).
- Roles y permisos (administrador / odontólogo / recepción) + auditoría básica.
- Reportes operativos básicos (ocupación, ausentismo, ingresos).

**Diferenciadores (v1.5, el moat)**:
- Validación de cobertura de obra social preventiva (afiliado/nomenclador/topes) antes de confirmar.
- Lista de espera inteligente con seña: hueco → oferta por WhatsApp → paga seña → slot asignado.
- Confirmación conversacional 24/7 (bot que entiende confirmar/cancelar/reprogramar).
- Precio ARS público y política de seguridad/exportación publicada desde el día 1.

**Etapas posteriores (v2+)**:
- Facturación electrónica ARCA nativa (Factura B/C + CAE + QR) por sede/punto de venta.
- Periodontograma, ortodoncia, imágenes/Rx con IA de apoyo.
- Multi-sucursal y gestión de red/franquicia.
- App móvil nativa; marketplace con reseñas verificadas; API pública; Google Calendar bidireccional; receta electrónica.

**Notas de stack**: el MVP mapea directo al stack fijo — FastAPI + JWT (roles), PostgreSQL (agenda/HC/auditoría), Redis + workers (recordatorios, webhooks MP, blasts de lista de espera), Docker/Compose (deploy simple en VPS AR), React + TS + Vite (agenda en tiempo real, odontograma SVG interactivo).

---

## Verificación de fuentes

**Método**: búsquedas web el 30/09/2026 con verificación directa en páginas oficiales (home, planes/precios, funcionalidades, centros de ayuda, fichas de app stores y marketplaces). Cada URL abajo fue consultada el **30/09/2026**. Los porcentajes, conteos de clientes y claims citados como "afirmación comercial" provienen de los propios proveedores y no fueron auditados.

**Fuentes oficiales consultadas**:
- https://web.dentaltec.com.ar/ · https://web.dentaltec.com.ar/funcionalidades · https://web.dentaltec.com.ar/casos-de-exito · https://web.dentaltec.com.ar/software-odontologos-argentina · https://cora.org.ar/actualidad/481-dentaltec-gestion-de-consultorios
- https://www.softwaredentalink.com/ · https://www.softwaredentalink.com/es/planes · https://ayuda.softwaredentalink.com/es/articles/13862710-obras-sociales · https://www.capterra.co/software/196361/dentalink · https://linkedin.com/company/dentalinksoftware
- https://dentalsoft.com.ar/
- https://gbsystems.com/os/ · https://gbsystems.com/os/producto.htm · https://gbsystems.com/os/version.htm
- https://www.dentario.com.ar/
- https://argensoft.net/ · https://www.argensalud.com/ · https://www.misturnosmovil.com.ar/ · https://www.misturnos.com.ar/
- https://www.tuturno.io/ · https://www.tuturno.io/ayuda/pf · https://linkedin.com/company/tuturno-io
- https://agendapro.com/ar · https://agendapro.com/ar/dental/software-odontologico · https://agendapro.com/ar/planes · https://agendapro.com/ar/agenda-medica · https://ayuda.agendapro.com/es/articles/5754192-como-funciona-el-envio-de-recordatorio-mediante-whatsapp
- https://www.doctoraliar.com/ · https://pro.doctoralia.com/ar/guias/configuracion-de-la-reserva-de-cita · https://apps.apple.com/ar/app/doctoralia-argentina/id1471977166 · https://www.doctoraliar.com/odontologo/buenos-aires
- https://www.dentidesk.com/ · https://www.dentidesk.cl/dentidesk · https://www.dentidesk.cl/dentidesk/feature · https://www.dentidesk.com/dentidesk/detail/40 · https://www.dentidesk.com/dentidesk/blog · https://app.dentidesk.cl/ · https://play.google.com/store/apps/details?id=com.dentidesk.app
- https://www.doctocliq.com/ · https://www.doctocliq.com/planes-y-precios · https://www.doctocliq.com/funcionalidades · https://www.doctocliq.com/funcionalidades/agenda-medica-digital · https://www.doctocliq.com/funcionalidades/caja-y-facturacion-electronica · https://www.doctocliq.com/pe/software-dental · https://www.doctocliq.com/doctocliq-vs-doctoralia-alternativas-a-doctoralia
- https://www.saludtools.com/ · https://www.saludtools.com/precios · https://www.saludtools.com/software-historia-clinica · https://www.saludtools.com/software-de-historia-clinica · https://www.saludtools.com/articulo/telemedicina-automatizada-doctoralia-saludtools
- https://simplesdental.com/ · https://www.simplesdental.com/planos-e-precos · https://www.dentalcremer.com.br/simples-dental · https://www.codental.com.br/simples-dental-vs-codental · https://www.codental.com.br/blog/software-odontologico-preco
- https://www.dentalis.com.br/ · https://www.dentalis.com.br/solucoes/dentalmax/ · https://www.dentalis.com.br/blog/atendimento-digital/
- https://www.doctoralia.com.mx/ · https://www.doctoralia.co/app-pacientes · https://pro.doctoralia.com.mx/precios/medicos-y-especialistas · https://pro.doctoralia.com.mx/precios/clinicas · https://pro.doctoralia.com.mx/productos/funcionalidades · https://pro.doctoralia.co/precios/para-especialistas · https://pro.doctoralia.cl/precios · https://pro.doctoralia.co/historias-de-exito
- https://www.dentrixascend.com/ · https://www.henryscheinone.com/dental-solutions/api-exchange/
- https://www.pattersondental.com/ · https://www.eaglesoft.net/ (verificación parcial: fetch directo fallido el 30/09/2026)
- https://www.opendental.com/ · https://www.opendental.com/site/order.html · https://www.opendental.com/site/fees.html · https://www.opendental.com/site/programbridges.html
- https://www.curvedental.com/ · https://www.curvedental.com/pricing · https://www.curvedental.com/partner-list
- https://carestack.com/
- https://planetdds.com/solutions/denticon/
- https://www.nexhealth.com/ · https://docs.nexhealth.com/
- https://www.fresha.com/ · https://www.fresha.com/for-business
- https://www.dentalsoft.cl/ (evidencia mínima) · https://www.dentalis.com.br/
- https://www.mercadopago.com.ar/ · https://developers.mercadopago.com/ (comisiones exactas no verificables por fetch el 30/09/2026: no se citan cifras)
- https://www.arca.gob.ar/fe/ (micrositio de factura electrónica vigente; detalle WSFE a verificar en homologación)
- https://developers.facebook.com/docs/whatsapp/ (marco público Cloud API; tarifas por conversación 2026 no verificadas: no se citan cifras)

**Limitaciones conocidas de esta investigación**: (1) el buscador web devolvió rate-limit parcial el 30/09/2026 en el frente internacional — se compensó con fetch directo a páginas oficiales; donde el fetch falló se marcó "No evidenciado"; (2) ningún proveedor publica auditorías independientes de sus conteos de clientes: todas las cifras de adopción son afirmaciones comerciales; (3) precios en USD/BRL/COP/CLP corresponden a lo publicado por cada proveedor y varían sin aviso; verificar antes de usar en decisiones comerciales.
