# Design — C-03 `disponibilidad-real-reserva-online`

## Context

Ver `proposal.md` (Why/What). Estado actual: C-01 archivada (exclusión gist por profesional/sillón, `POST /api/v1/turnos` protegido, shape `409` + alternativos, validación AR, R6) y C-02 archivada (JWT/RBAC, auditoría, Redis por app con `fakeredis` en tests, rate limit de login como patrón a reutilizar). No existen `HorarioProfesional`/`Bloqueo` ni endpoints públicos de agenda: este change los introduce. Restricciones: capas separadas + Alembic (R2), hints siempre (R1), la DB manda ante conflicto (R3), jamás PII en salidas (R6), env sin secretos (R7), stack fijo (R8).

## Goals / Non-Goals

**Goals:**

- Cálculo de slots correcto por construcción (refleja la exclusión sin duplicar su lógica de forma divergente) y performante en ventanas típicas (día/semana).
- Reserva pública segura sin cuenta: verificación anti-spam, idempotencia real bajo concurrencia, rate limit efectivo, auditoría sin PII.
- Reutilizar el camino de creación de C-01 (servicio interno compartido) para que el `409` público y el protegido nunca diverjan de shape.

**Non-Goals:**

- Autogestión con token, cancelación con antelación y máquina de estados → C-05 (aquí el turno nace `reservado` y punto).
- Cobro/acreditación MP → C-08 (aquí solo se emite el link).
- Envío programático de WhatsApp/recordatorios → C-06 (la verificación usa el emisor existente; si cae, degradación manual).
- Frontend `/reservar/:slug` → C-10 (el backend solo garantiza endpoints públicos estables).

## Decisions

1. **Cálculo de slots en servicio `disponibilidad` (aplicativo) + exclusión DB como verdad final.** El servicio expande el `HorarioProfesional` vigente en ranuras de `prestacion.duracion_min` y resta `Bloqueo`s y turnos activos (mismas queries de solape que `repositories/agenda`, extendidas con filtro de rango). Racional: la exclusión gist no enumera huecos, solo veta colisiones; el servicio propone y la DB dispone (R3). Descartado: vista materializada de slots — se desincroniza y complica la migración 003.
2. **Modelos mínimos en migración 003: `HorarioProfesional` + `Bloqueo` (+ `ClaveIdempotencia`).** `HorarioProfesional(profesional_id, dia_semana 0–6, hora_inicio, hora_fin, vigente_desde, vigente_hasta NULL, activo)`; `Bloqueo(profesional_id NULL-able para bloqueos de sillón/sede, sillon_id NULLable, desde, hasta, motivo, creado_por)`. `ClaveIdempotencia(clave única, turno_id NULL, respuesta_json, expira_en)`. Racional: cubre horario semanal + excepciones puntuales sin sobrediseñar calendarios recurrentes complejos (llegan si C-04 los pide). Índices btree `(profesional_id, dia_semana)`, `(desde, hasta)` y gist opcional en rango de bloqueo si el volumen lo justifica (decisión en apply tras `EXPLAIN`).
3. **Idempotencia con clave persistida + ventana de expiración.** Header `Idempotency-Key` obligatorio en `POST /api/v1/turnos/publicos`; primera escritura inserta la clave en la misma transacción que el turno (conflicto único → devolver el turno ya creado, nunca duplicar). TTL configurable (`IDEMPOTENCIA_TTL_H`, default 24 h). Racional frente a alternativa "solo Redis": la DB sobrevive a reinicios y participa de la transacción; Redis queda solo para rate limit. Claves distintas con mismo slot compiten normal por la exclusión → una gana con `201`, la otra `409`.
4. **Verificación por código solo en primera reserva del par DNI + teléfono.** Tabla `VerificacionPublica(dni_hash, telefono_hash, codigo_hash, intentos, expira_en, verificada_en)` — se almacenan hashes, jamás el código ni el teléfono en claro (R6). Emisión con TTL corto (`VERIF_TTL_MIN`, default 10'), máximo N intentos (`VERIF_MAX_INTENTOS`, default 5) + bloqueo temporal (`VERIF_LOCK_S`). Respuestas idénticas exista o no el par (anti-enumeración). Racional frente a "verificar siempre": fricción mínima para reservantes recurrentes sin debilitar el anti-spam del primer contacto.
5. **Rate limit en Redis con dos llaves independientes (IP y teléfono normalizado E.164).** Reutiliza la capa `redis_client` de C-02 + `fakeredis` en tests; topes por env (`RATE_PUBLIC_IP_MAX/WINDOW_S`, `RATE_PUBLIC_TEL_MAX/WINDOW_S`). El `429` lleva `Retry-After` y mensaje genérico. Racional: dos dimensiones porque el atacante puede rotar una (IP vía red móvil, teléfono vía numeración) pero rara vez ambas a escala sin costo.
6. **Routers públicos separados de los protegidos.** `routers/disponibilidad.py` y `routers/turnos_publicos.py` sin `require_role`, montados en el mismo `api_router` (`/api/v1`); los protegidos no se tocan. Racional (standard fastapi): la superficie pública queda auditable de un vistazo y un error de dependencia no abre accidentalmente un endpoint interno.
7. **`409` público = mismo handler y shape que C-01.** La reserva pública llama al núcleo de creación compartido; la violación de exclusión (carrera GET→POST) fluye al `slot_ocupado_handler` existente con `problema` + `slots_alternativos` recalculados sobre el recurso en conflicto. Sin PII (R6 ya verificado en C-01).
8. **Link de seña como dato opaco.** Si `requiere_sena`, la respuesta incluye `url_pago` construida con el token/strategy que definirá C-08 (placeholder firmado con secreto de env, nunca el secreto en claro); este change NO crea `Pago` ni webhook. Racional: evita un medio-modelo de pagos que C-08 tendría que migrar.
9. **Testing (plan, se ejecuta en apply):** pytest, Postgres real de test (el gist no existe en SQLite), `fakeredis`, AAA, `--cov-fail-under=80` en el dominio nuevo; concurrencia con doble POST simultáneo (patrón C-01).

## Risks / Trade-offs

- [Riesgo] Explosión combinatoria de slots en ventanas largas → Mitigación: ventana máxima configurable (`DISPON_MAX_DIAS`, default 30), paginación por `desde/hasta`, límite N slots; `422` ante ventana excesiva.
- [Riesgo] Zona horaria (slots al borde del día, DST) → Mitigación: todo `timestamptz`, Pydantic exige offset aware, seed/tests en `America/Argentina/Buenos_Aires`.
- [Riesgo] Bloqueos que solapan horario fuera de vigencia → Mitigación: predicado de vigencia en la query (`vigente_desde/hasta`, `activo`); sin bloqueos sin `desde < hasta` (check constraint).
- [Riesgo] Enumeración de pares DNI + teléfono vía tiempos de respuesta → Mitigación: mensajes idénticos + hash + tiempo de respuesta normalizado (costo fijo de hash).
- [Riesgo] Abuso del emisor de códigos (SMS/WA) → Mitigación: rate limit de emisión más estricto que el de reserva + bloqueo por teléfono; degradación a aviso a recepción si el proveedor cae (el turno no se pierde, queda pendiente de verificación).
- [Trade-off] Horario semanal simple vs calendarios recurrentes ricos (feriados, rotaciones). Aceptado: `Bloqueo` puntual cubre feriados/vacaciones; recurrencias complejas van a C-04 si se piden.

## Migration Plan

1. `apply` ejecuta migración 003 en DB con datos C-01/C-02 (tablas nuevas vacías, sin backfill; `HorarioProfesional` se siembra solo en demo/dev).
2. Deploy: `docker compose up --build`; sin cambios en Compose salvo nuevas env documentadas en `.env.example`.
3. Rollback: `alembic downgrade -1` (elimina las 3 tablas + índices; no toca turnos existentes).
4. Seed demo extiende el de C-01 con 1 horario semanal ficticio + 1 bloqueo ficticio (R0, marcados `demo`).

## Open Questions

- ¿El slug `/reservar/:slug` identifica consultorio/sede (multi-sede futura) o es único global? No bloquea: el backend no lo interpreta en este change (lo consume el frontend C-10); se registra para C-04/C-10.
- Tope exacto de rate limit público y TTL de idempotencia: defaults propuestos (`RATE_PUBLIC_IP_MAX=60/min`, `TEL=10/min`, `IDEMPOTENCIA_TTL_H=24`); el apply los deja en env para ajuste en piloto sin cambiar specs.
