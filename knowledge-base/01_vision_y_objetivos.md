# Visión y Objetivos

## Propósito del sistema

Sistema integral de gestión odontológica con turnos para Argentina que elimina la coordinación manual por WhatsApp, papel o planillas.

Los consultorios y clínicas argentinas pierden ingresos por ausentismo, huecos sin cubrir, dobles reservas y horas de gestión administrativa, mientras la oferta existente no cubre el cuadro completo: o integra obra social + ARCA sin experiencia de paciente moderna (DentalTec), o tiene turnos online y marketing sin OS ni facturación local (AgendaPro, Dentalink parcial). Este producto ocupa ese hueco: agenda + clínica + cobros pensado para Argentina desde el día 1 (Fuente: `docs/discovery/informe-discovery.md` §C.3, `discovery/discovery.md` §1).

## Objetivos por actor

| Actor | Objetivo principal | Objetivos secundarios |
|-------|--------------------|-----------------------|
| Paciente | Reservar, confirmar, cancelar y reprogramar sin llamar | Pagar seña online; recibir recordatorios; consultar prestaciones |
| Recepcionista | Gestionar la agenda del día sin trabajo manual repetitivo | Confirmar por WhatsApp; cobrar; reasignar huecos liberados |
| Odontólogo / profesional | Atender con ficha + odontograma + presupuesto en un solo flujo | Evitar doble carga; dar seguimiento clínico por pieza |
| Administrador / dueño | Asegurar ingresos (señas, caja diaria, reportes) | Configurar agenda y precios; gestionar usuarios y permisos |
| Obra social / prepaga (externo) | Cobertura validada antes de atender (v1.5) | Liquidaciones conciliables sin débitos |

## Alcance v1.0 (MVP)

- Agenda multiprofesional y multisillón con prevención de solapamientos, vista día/semana.
- Reserva online 24/7 con link compartible (web/redes/QR); paciente sin cuenta obligatoria (DNI + teléfono).
- Confirmación, cancelación y reprogramación por el paciente; recordatorios por WhatsApp (Cloud API, plantillas utility).
- Ficha clínica + odontograma digital FDI + presupuestos/planes de tratamiento.
- Caja con cierre diario + cobro de señas por Mercado Pago (link de pago + webhook).
- Roles y permisos (administrador / odontólogo / recepción) + auditoría básica.
- Reportes operativos básicos (ocupación, ausentismo, ingresos).

## Alcance v1.5 (diferenciadores / moat)

- Validación de cobertura de obra social preventiva (afiliado/nomenclador/topes) antes de confirmar.
- Lista de espera inteligente con seña: hueco libre → oferta por WhatsApp → paga seña → slot asignado.
- Confirmación conversacional 24/7 (bot que entiende confirmar/cancelar/reprogramar).
- Precio ARS público y política de seguridad/exportación publicada desde el día 1.

## Alcance v2+

- Facturación electrónica ARCA nativa (Factura B/C + CAE + QR por sede/punto de venta).
- Periodontograma, ortodoncia, imágenes/Rx con IA de apoyo.
- Multi-sucursal y gestión de red/franquicia; app móvil; marketplace con reseñas; API pública; Google Calendar bidireccional; receta electrónica.

## Fuera de alcance

- No es un marketplace de captación (ese rol lo cubre Doctoralia; el producto gestiona la clínica).
- No incluye facturación ARCA nativa en v1 (fase 2).
- No incluye periodontograma/ortodoncia/imágenes con IA en v1.
- No incluye multi-sucursal/red/franquicia ni app móvil nativa en v1.
- No incluye validación OS preventiva en v1.0 (diferenciador v1.5).
- No incluye marketing automation masivo (solo plantillas utility + opt-in aparte).
- No sustituye el software contable del estudio.

## Métricas de éxito

- Ausentismo mensual < 8 % (línea base manual típica a relevar por consultorio).
- Ocupación de sillón ≥ 80 % en horario pico.
- ≥ 70 % de turnos confirmados sin intervención de recepción.
- 0 dobles reservas por solapamiento en 90 días.
- Cierre de caja diario conciliado al 100 % (efectivo + MP).
- Tiempo atención-con-registro: ficha + odontograma + presupuesto en una sola sesión sin doble carga.
