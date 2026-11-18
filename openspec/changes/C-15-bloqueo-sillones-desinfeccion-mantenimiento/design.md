# Diseño Técnico C-15: Bloqueo de Sillones Odontológicos por Desinfección y Mantenimiento

* **Change:** `C-15-bloqueo-sillones-desinfeccion-mantenimiento`
* **Gobernanza:** MEDIO (modificación de reglas de agenda y esquema de disponibilidad)
* **Arquitectura:** FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL con exclusión GiST

---

## 1. Modelo de Datos y Restricciones Físicas

### 1.1. Modelo `Bloqueo` (`app/models/disponibilidad.py`)
La entidad existente se formaliza para soportar polimorfismo de recurso bloqueado (o bien profesional, o bien sillón):

```python
class Bloqueo(Base):
    __tablename__ = "bloqueo"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profesional_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("profesional.id"), nullable=True)
    sillon_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sillon.id"), nullable=True)
    desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hasta: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    motivo: Mapped[str] = mapped_column(String(200), nullable=False)  # Ej: "Desinfección de box", "Mantenimiento turbina"
    tipo: Mapped[str] = mapped_column(String(50), nullable=False, default="desinfeccion") # "desinfeccion" | "mantenimiento" | "licencia"
    creado_por: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("usuario.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

**Regla de Integridad de Entidad (CHECK constraint):**
Un bloqueo debe especificar obligatoriamente al menos uno de los dos recursos:
`CONSTRAINT chk_recurso_bloqueado CHECK (profesional_id IS NOT NULL OR sillon_id IS NOT NULL)`
Y el intervalo temporal debe ser positivo:
`CONSTRAINT chk_bloqueo_intervalo_positivo CHECK (hasta > desde)`

### 1.2. Constraint de Exclusión Física GiST (PostgreSQL)
Se agrega en la migración Alembic `014_bloqueo_sillon_exclusion.py`:
```sql
ALTER TABLE bloqueo ADD CONSTRAINT ex_bloqueo_sillon_sin_solape
EXCLUDE USING gist (
    sillon_id WITH =,
    tstzrange(desde, hasta, '[)') WITH &&
)
WHERE (sillon_id IS NOT NULL);
```
*Justificación:* Garantiza a nivel de motor de base de datos que dos solicitudes concurrentes de bloqueo para el mismo sillón físico no puedan solaparse jamás, actuando como la última línea de defensa física (Regla R3).

---

## 2. Contrato de API REST y RBAC

### 2.1. Endpoints
Prefijo: `/api/v1/bloqueos` (Tags: `["bloqueos"]`)

| Método | Ruta | Rol Autorizado | Código Exitoso | Códigos de Error |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/bloqueos` | `admin`, `recepcion` | `201 Created` | `400 Bad Request`, `401 Unauthorized`, `403 Forbidden`, `409 Conflict`, `422 Unprocessable` |
| `GET` | `/api/v1/bloqueos` | `admin`, `recepcion`, `odontologo` | `200 OK` | `401 Unauthorized`, `422 Unprocessable` |
| `DELETE` | `/api/v1/bloqueos/{id}` | `admin`, `recepcion` | `204 No Content` | `401 Unauthorized`, `403 Forbidden`, `404 Not Found` |

### 2.2. Esquemas Pydantic (`app/schemas/bloqueo.py`)
```python
class BloqueoCreate(BaseModel):
    sillon_id: uuid.UUID | None = None
    profesional_id: uuid.UUID | None = None
    desde: datetime
    hasta: datetime
    motivo: str = Field(min_length=3, max_length=200)
    tipo: Literal["desinfeccion", "mantenimiento", "licencia"]

    @model_validator(mode="after")
    def validar_recurso(self) -> Self:
        if not self.sillon_id and not self.profesional_id:
            raise ValueError("Debe especificarse sillon_id o profesional_id.")
        if self.hasta <= self.desde:
            raise ValueError("La fecha/hora de finalización debe ser posterior al inicio.")
        return self

class BloqueoResponse(BaseModel):
    id: uuid.UUID
    sillon_id: uuid.UUID | None
    profesional_id: uuid.UUID | None
    desde: datetime
    hasta: datetime
    motivo: str
    tipo: str
    creado_en: datetime
```

---

## 3. Lógica de Servicio y Reglas de Negocio

### 3.1. Creación de Bloqueo (`app/services/bloqueos.py`)
1. **Validación de Conflicto con Turnos Activos:**
   Antes de insertar el bloqueo de sillón, el servicio consulta la tabla `turno`:
   ```sql
   SELECT id FROM turno
   WHERE sillon_id = :sillon_id
     AND estado IN ('reservado', 'confirmado', 'presente')
     AND tstzrange(inicio, fin, '[)') && tstzrange(:desde, :hasta, '[)')
   ```
   - Si existen turnos coincidentes: lanza `ConflictError("El sillón posee turnos activos en esa ventana; deben reubicarse antes de bloquear.")` ➔ Respuesta HTTP `409 Conflict` con la lista de IDs de turnos afectados.
2. **Persistencia:** Si no hay turnos activos, se inserta el `Bloqueo`. Si por concurrencia extrema otro proceso insertó un bloqueo simultáneo, el constraint GiST de Postgres atrapa la colisión y genera `IntegrityError` ➔ HTTP `409 Conflict`.
3. **Auditoría (RN-AU-02 / Regla R6):** Registra el evento `bloqueo_sillon_creado` en la tabla `auditoria` con sanitización de diff (solo `sillon_id`, tipo, motivo y rango temporal; sin datos personales).

### 3.2. Integración con Disponibilidad (`app/services/disponibilidad.py`)
En el algoritmo de generación de slots libres para reserva (`C-03` / `C-10`):
- Se buscan todos los bloqueos de sillón que intersecten el día consultado.
- Un slot `[t_inicio, t_fin)` solo se considera disponible si el sillón no está solapado con ningún `Bloqueo` activo en ese rango.

---

## 4. Matriz de Seguridad y Privacidad (Leyes 25.326 y 26.529 / Reglas R0 y R6)

1. **Minimización de Datos:** Los registros de bloqueo no guardan relación con ningún paciente. El campo `motivo` debe restringirse a justificaciones operativas del box (*"Desinfección bioaerosoles post-cirugía"*, *"Avería compresor de aire"*, *"Mantenimiento autoclave"*).
2. **Cero PII en Respuestas y Logs:** No se admiten datos de identificación personal en los diffs de auditoría ni en mensajes de error.
3. **Desacoplamiento Clínico:** El motivo del bloqueo no revela la patología del paciente previo que requirió la desinfección, resguardando el secreto médico establecido por la Ley 26.529.
