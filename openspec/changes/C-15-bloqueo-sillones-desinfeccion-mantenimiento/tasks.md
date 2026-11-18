# Plan de Tareas C-15: Bloqueo de Sillones por Desinfección y Mantenimiento

* **Change:** `C-15-bloqueo-sillones-desinfeccion-mantenimiento`
* **Gobernanza:** MEDIO
* **Estado:** `[ ]` Planificado (Ciclo SDD / Sin implementar)

---

## 1. Capa de Base de Datos y Persistencia
- [ ] 1.1 Crear migración Alembic `014_bloqueo_sillon_exclusion.py`:
  - Agregar CHECK constraint `chk_recurso_bloqueado` en tabla `bloqueo`.
  - Crear constraint de exclusión física `ex_bloqueo_sillon_sin_solape` usando `btree_gist` con `EXCLUDE USING gist (sillon_id WITH =, tstzrange(desde, hasta, '[)') WITH &&) WHERE (sillon_id IS NOT NULL)`.
- [ ] 1.2 Actualizar modelo SQLAlchemy `Bloqueo` en `app/models/disponibilidad.py` con campo `tipo` y relaciones a `Sillon`.

## 2. Capa de Esquemas y Validación (Pydantic)
- [ ] 2.1 Crear `app/schemas/bloqueo.py`:
  - `BloqueoCreate` con validaciones de fechas (`hasta > desde`), presencia obligatoria de recurso y sanitización de motivos.
  - `BloqueoResponse` sin exposición de campos internos ni PII.

## 3. Capa de Lógica de Negocio (Servicios)
- [ ] 3.1 Implementar `app/services/bloqueos.py`:
  - Función `crear_bloqueo()`: valida que no existan turnos activos en el sillón antes de persistir (lanza `409` si hay conflicto).
  - Manejo de excepción de base de datos `IntegrityError` sobre constraint GiST para traducirla a `409 Conflict`.
  - Auditoría del evento `bloqueo_sillon_creado` con sanitización estricta (sin PII, Ley 25.326).
- [ ] 3.2 Modificar `app/services/disponibilidad.py`:
  - Integrar filtro de exclusión de franjas horarias bloqueadas por sillón al calcular slots libres para reserva.

## 4. Capa de Endpoints y Control de Acceso (FastAPI)
- [ ] 4.1 Crear router `app/routers/bloqueos.py`:
  - `POST /api/v1/bloqueos`: protegido por RBAC (roles `admin` y `recepcion`).
  - `GET /api/v1/bloqueos`: listado de bloqueos con filtro por fecha.
  - `DELETE /api/v1/bloqueos/{id}`: desactiva o elimina un bloqueo programado.
- [ ] 4.2 Registrar el nuevo router en `app/main.py`.

## 5. Pruebas Automatizadas y Verificación de Escenarios (TDD)
- [ ] 5.1 Implementar test suite `tests/integration/test_bloqueo_sillones.py` cubriendo los 3 escenarios obligatorios del spec:
  - **Verificación Escenario 1 (Happy Path - Desinfección 30 min):**
    - Enviar POST con rol `recepcion` para bloquear sillón libre.
    - Assert: Código HTTP `201 Created`.
    - Assert: `GET /api/v1/disponibilidad` no devuelve slots dentro de la ventana de desinfección.
    - Assert: Registro de auditoría emitido sin PII.
  - **Verificación Escenario 2 (Error de Negocio - Turnos confirmados preexistentes):**
    - Crear turno confirmado previo en el sillón de prueba.
    - Intentar POST de bloqueo que solape dicho turno.
    - Assert: Código HTTP `409 Conflict`.
    - Assert: Detalle informa `sillon_con_turnos_activos` y no muta el turno ni crea el bloqueo.
  - **Verificación Escenario 3 (Caso de Borde - Límite de cierre y colisión GiST):**
    - Crear bloqueo en franja 19:30 a 20:00 (límite de cierre). Assert: `201 Created`.
    - Enviar segundo bloqueo concurrente solapado parcialmente (19:45 a 20:15).
    - Assert: El motor de base de datos activa el constraint GiST y la API responde `409 Conflict`.
- [ ] 5.2 Ejecutar suite de regresión completa garantizando que los tests existentes sigan en verde.
