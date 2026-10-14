# Actores y Roles

## Actores del sistema

| Actor | Descripción | Cómo interactúa |
|-------|-------------|-----------------|
| Paciente (público) | Persona que reserva atención; no requiere cuenta (DNI + teléfono) | Link/QR de reserva 24/7, WhatsApp (confirmar/cancelar/reprogramar), link de pago MP |
| Recepcionista | Gestiona agenda del día, confirma, cobra, reasigna huecos | SPA: agenda día/semana, check-in, caja, lista de espera |
| Odontólogo / profesional | Atiende y registra clínica | SPA: ficha, odontograma, presupuestos/planes, su agenda |
| Administrador / dueño | Configura consultorio, precios, usuarios; ve caja y reportes | SPA: configuración, usuarios, caja, reportes, auditoría |
| Obra social / prepaga (externo) | Cobertura a validar y liquidaciones a conciliar; no es usuario directo | Integración/validación preventiva (v1.5); sin login en v1 |
| Sistema / workers | Actores técnicos (recordatorios, webhooks, blasts) | Jobs Redis, webhooks entrantes |

## RBAC — Matriz de permisos

Roles internos: `admin`, `odontologo`, `recepcion`. El paciente público opera con tokens de un solo uso / vínculo DNI+teléfono, no con rol.

| Recurso | admin | odontologo | recepcion |
|---------|-------|------------|-----------|
| Usuarios y roles | CRUD | — (solo ver propio perfil) | — |
| Config. agenda (profesionales, sillones, prestaciones, horarios) | CRUD | R (propia agenda) | R |
| Turnos | CRUD | R/U (propios; check-in clínico) | CRUD (crear, confirmar, reprogramar, cancelar) |
| Pacientes | CRUD | R/U (sus pacientes) | CRUD |
| Ficha clínica / odontograma | R (auditoría) | CRUD (propios pacientes) | R (datos contacto; sin editar clínica) |
| Presupuestos / planes | CRUD | CRUD | R + generar link de pago |
| Pagos / caja / cierre diario | CRUD + cerrar | R (sus cobros) | C (cobrar) + cierre operativo |
| Lista de espera | CRUD | R | CRUD |
| OS / liquidaciones (v1.5) | CRUD | R | R/U |
| Facturación ARCA (v2) | CRUD | R | C |
| Reportes | Full | Propios | Operativos día |
| Auditoría | R | — | — |

## Rutas públicas

Sin autenticación (con protecciones anti-abuso: rate limit, token firmado, validación DNI+teléfono):

- `GET /reservar/:slug` — landing de reserva del consultorio (link/QR).
- `GET /api/v1/disponibilidad?...` — slots reales por motivo/profesional.
- `POST /api/v1/turnos/publicos` — crear turno (DNI + teléfono + token de idempotencia).
- `GET /api/v1/turnos/publicos/:token` — ver/gestionar turno propio.
- `POST /api/v1/turnos/publicos/:token/confirmar|/cancelar|/reprogramar`.
- `GET /pagar/:token` — checkout/redirección Mercado Pago de seña.
- `POST /webhooks/mercadopago`, `POST /webhooks/whatsapp` — callbacks firmados.
- Login (`/login`) y recuperación de contraseña (públicas por definición).
