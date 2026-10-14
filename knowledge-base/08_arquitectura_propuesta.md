# Arquitectura Propuesta

## Patrones aplicados

| Patrón | Dónde se usa | Por qué |
|--------|--------------|---------|
| Monolito modular | Backend FastAPI por dominios (agenda, clínica, caja, OS, facturación) | v1 simple, deploy único en VPS; evita overhead de microservicios |
| Repository + Service | SQLAlchemy repositories + capa servicios por dominio | Testabilidad y cambio de persistencia aislado |
| Token público firmado | Gestión de turnos por paciente sin login | UX sin cuenta + seguridad sin sesión |
| Workers + colas Redis | Recordatorios WA, webhooks MP, blasts lista de espera | Operación asíncrona, reintentos, idempotencia |
| Webhook idempotente | MP y WhatsApp | Doble entrega sin doble efecto |
| Exclusion constraint PG | No-solapamiento profesional/sillón | Garantía física contra dobles reservas concurrentes |
| RBAC + JWT rotativo | API interna | Cumplimiento mínimo de seguridad multi-rol |

## Estructura de directorios

```
turnos-odontologia/
├── backend/
│   └── app/
│       ├── main.py (FastAPI, routers /api/v1)
│       ├── core/ (config, security JWT, deps, rate-limit)
│       ├── domain/ (agenda, pacientes, clinica, caja, os, facturacion, usuarios)
│       │   └── {dominio}/ (models, schemas, service, repository, router)
│       ├── infrastructure/ (db postgres, redis/queues, whatsapp, mercadopago, arca_v2)
│       └── workers/ (recordatorios, webhooks, lista_espera)
├── frontend/
│   └── src/
│       ├── features/ (agenda, reserva-publica, clinica/odontograma, caja, reportes, admin)
│       ├── shared/ (api client, auth, ui)
│       └── pages/ (login, agenda, reservar/:slug, pagar/:token, admin/*)
├── knowledge-base/
├── docs/discovery/
├── docker-compose.yml (api + web + postgres + redis + worker)
└── .active-orchestrator-state.json
```

## Seguridad

- Autenticación: JWT access 15' + refresh rotativo 7 d, hash Argon2/bcrypt, bloqueo por intentos.
- Autorización: RBAC (admin/odontologo/recepcion) + deny-by-default; paciente con token público de un solo propósito.
- Validación de input: schemas Pydantic estrictos; DNI/teléfono E.164 AR; CSRF en web pública donde aplique.
- Secrets management: solo env vars / archivo `.env` no commiteado; webhooks verificados por firma (MP x-signature, WA verify token + firma).
- Datos sensibles: cifrado en tránsito (TLS), cifrado en reposo PG para HCE; minimización Ley 25.326; consentimiento y trazabilidad Ley 26.529; exportación de datos del paciente garantizada; backups PG diarios con retención 30 d.
- Auditoría: log inmutable de acciones sensibles (RN-AU-03).

## Variables de entorno

| Variable | Descripción | Ejemplo | Sensible |
|----------|-------------|---------|----------|
| DATABASE_URL | Conexión PostgreSQL | postgresql://user:pass@db:5432/turnos | Y |
| REDIS_URL | Cola/cache | redis://redis:6379/0 | N |
| JWT_SECRET | Firma JWT | (32+ bytes) | Y |
| JWT_ACCESS_MIN / JWT_REFRESH_DAYS | Tiempos de token | 15 / 7 | N |
| FRONTEND_URL | URL pública (links/QR) | https://turnos.ejemplo.ar | N |
| WHATSAPP_TOKEN / WHATSAPP_PHONE_ID / WHATSAPP_VERIFY_TOKEN | Cloud API | — | Y |
| MP_ACCESS_TOKEN / MP_PUBLIC_KEY / MP_WEBHOOK_SECRET | Mercado Pago | — | Y |
| ARCA_CERT / ARCA_KEY / ARCA_CUIT / ARCA_PTO_VTA (v2) | Facturación electrónica | — | Y |
| SLOT_LOCK_TTL / CANCEL_MIN_HOURS / SENA_DEFAULT_PCT | Parámetros de negocio | 300s / 12 / 30 | N |
| SMTP_URL / SMS_GATEWAY_KEY | Fallback notificaciones | — | Y |
