# Descripción General

## Stack tecnológico

Stack fijo (restricción no negociable — `discovery/discovery.md` §9, state `discovery.restricciones`):

| Capa | Tecnologías | Versión mínima |
|------|-------------|----------------|
| Backend | Python + FastAPI + SQLAlchemy | Python 3.12, FastAPI 0.110+ |
| Auth | JWT (access + refresh) | — |
| Base de datos | PostgreSQL | 15+ |
| Caché / colas | Redis (+ workers para recordatorios, webhooks, blasts) | 7+ |
| Frontend | React + TypeScript + Vite | React 18, TS 5 |
| Deploy | Docker / Docker Compose en VPS argentino | Compose v2 |
| Idioma | Español (todo el producto) | — |

## Arquitectura general

```
Paciente (link/QR) ─┐
                    ├→ React SPA (Vite) → API REST FastAPI (JWT) → PostgreSQL
Recepción/Admin ────┘        │                        ├→ Redis + workers (recordatorios WA, webhooks MP, lista de espera)
Odontólogo ─────────────────┘                        └→ Integraciones (WhatsApp Cloud API, Mercado Pago, ARCA fase 2)
```

Monolito modular backend (no microservicios en v1): dominios agenda, pacientes, clínica, caja/cobros, OS (v1.5), facturación (v2), usuarios/auditoría. Frontend SPA con agenda en tiempo real y odontograma SVG interactivo (referencia: DentalSoft SVG FDI 18 estados). Deploy simple: un `docker-compose` (api + web + postgres + redis + worker) en VPS AR.

## Integraciones externas

| Servicio | Propósito | Tipo |
|----------|-----------|------|
| WhatsApp Cloud API | Recordatorios, confirmación/cancelación/reprogramación, blasts de lista de espera (plantillas utility) | REST + webhooks |
| Mercado Pago | Link de pago / Checkout de señas + webhooks de acreditación | REST + webhooks |
| ARCA WSFE (fase 2) | Factura electrónica B/C + CAE + QR por sede/punto de venta | SOAP (WSFE) |
| Google Calendar (v2) | Sincronización bidireccional de agenda | REST/OAuth |
| Email/SMS (v1) | Fallback de notificaciones cuando no hay WhatsApp | SMTP / gateway SMS |

Detalle operativo en `11_integraciones_locales.md`.

## API REST

Agrupada por recurso (diseño definitivo en implementación; prefijo `/api/v1`):

- `auth`: login, refresh, logout, perfil.
- `usuarios`: CRUD usuarios internos + roles.
- `pacientes`: CRUD pacientes (DNI + teléfono como identidad pública), consentimientos.
- `profesionales` / `sillones` / `prestaciones` (motivo + duración): configuración de agenda.
- `turnos`: disponibilidad por motivo/profesional/slot, crear (público con token/DNI), confirmar/cancelar/reprogramar, check-in, estados.
- `lista-espera`: alta, ofertas por hueco, aceptación con seña.
- `fichas` / `odontograma` / `presupuestos` / `planes`: historia clínica y commercial.
- `obras-sociales` (v1.5): afiliados, cobertura preventiva, liquidaciones.
- `pagos` / `caja`: señas MP + webhook, movimientos, cierre diario.
- `facturacion` (v2): comprobantes ARCA, CAE, QR.
- `reportes`: ocupación, ausentismo, ingresos.
- `auditoria`: bitácora de acciones sensibles.
- `webhooks`: `/webhooks/mercadopago`, `/webhooks/whatsapp`.
