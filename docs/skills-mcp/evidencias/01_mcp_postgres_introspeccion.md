# Evidencia 01: Introspección de Base de Datos con Servidor MCP PostgreSQL

* **Fecha de Ejecución:** 17 de Noviembre de 2026
* **Componente Evaluado:** Servidor MCP oficial `@modelcontextprotocol/server-postgres`
* **Entorno:** PostgreSQL 15+ local (`127.0.0.1:5432/turnos`)
* **Rol de Conexión:** `turnos_readonly` (permisos exclusivos `CONNECT`, `USAGE`, `SELECT` sobre esquema `public`)
* **Objetivo:** Inspeccionar la estructura relacional de la tabla `bloqueo` y los constraints de exclusión física GiST de `turno` para fundamentar la arquitectura del Change C-15 (`bloqueo-sillones-desinfeccion-mantenimiento`).

---

## 1. Configuración de Seguridad y Mínimo Privilegio (R0 y R2)

Para cumplir con la **Regla R2** (prohibido alterar la DB a mano; todo cambio estructural va por migración Alembic) y la **Regla R0** (integridad de datos), el servidor MCP se ejecuta sobre un rol sin privilegios de escritura:

```sql
CREATE ROLE turnos_readonly WITH LOGIN PASSWORD 'turnos_ro_pass';
GRANT CONNECT ON DATABASE turnos TO turnos_readonly;
GRANT USAGE ON SCHEMA public TO turnos_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO turnos_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO turnos_readonly;
```

*Verificación de Seguridad ejecutada:*
Un intento de mutación directa (`INSERT INTO sillon ...`) fue rechazado por el motor de base de datos con:
> `asyncpg.exceptions.InsufficientPrivilegeError: permiso denegado a la tabla sillon`

---

## 2. Inicialización del Servidor MCP (Protocolo JSON-RPC 2.0)

**Comando de inicialización:**
```bash
npx -y @modelcontextprotocol/server-postgres "postgresql://turnos_readonly:turnos_ro_pass@127.0.0.1:5432/turnos"
```

**Respuesta al handshake `initialize`:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": {
      "tools": {}
    },
    "serverInfo": {
      "name": "example-servers/postgres",
      "version": "0.1.0"
    }
  }
}
```

**Herramientas descubiertas (`tools/list`):**
* `query`: Ejecución de sentencias SQL seguras de solo lectura sobre el catálogo y las tablas del esquema.

---

## 3. Consulta de Introspección 1: Estructura Actual de la Tabla `bloqueo`

**Solicitud JSON-RPC (`tools/call`):**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "query",
    "arguments": {
      "sql": "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_name = 'bloqueo' ORDER BY ordinal_position;"
    }
  }
}
```

**Respuesta recibida:**
```json
{
  "result": {
    "content": [
      {
        "type": "text",
        "text": "[\n  {\"column_name\": \"id\", \"data_type\": \"uuid\", \"is_nullable\": \"NO\", \"column_default\": null},\n  {\"column_name\": \"profesional_id\", \"data_type\": \"uuid\", \"is_nullable\": \"YES\", \"column_default\": null},\n  {\"column_name\": \"sillon_id\", \"data_type\": \"uuid\", \"is_nullable\": \"YES\", \"column_default\": null},\n  {\"column_name\": \"desde\", \"data_type\": \"timestamp with time zone\", \"is_nullable\": \"NO\", \"column_default\": null},\n  {\"column_name\": \"hasta\", \"data_type\": \"timestamp with time zone\", \"is_nullable\": \"NO\", \"column_default\": null},\n  {\"column_name\": \"motivo\", \"data_type\": \"character varying\", \"is_nullable\": \"YES\", \"column_default\": null},\n  {\"column_name\": \"creado_por\", \"data_type\": \"uuid\", \"is_nullable\": \"YES\", \"column_default\": null},\n  {\"column_name\": \"creado_en\", \"data_type\": \"timestamp with time zone\", \"is_nullable\": \"YES\", \"column_default\": \"now()\"},\n  {\"column_name\": \"actualizado_en\", \"data_type\": \"timestamp with time zone\", \"is_nullable\": \"YES\", \"column_default\": \"now()\"}\n]"
      }
    ],
    "isError": false
  },
  "jsonrpc": "2.0",
  "id": 3
}
```

---

## 4. Consulta de Introspección 2: Constraints de Exclusión GiST (`pg_constraint`)

**Solicitud JSON-RPC (`tools/call`):**
```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "query",
    "arguments": {
      "sql": "SELECT conname AS constraint_name, conrelid::regclass AS table_name, pg_get_constraintdef(c.oid) AS constraint_definition FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace WHERE n.nspname = 'public' AND contype = 'x';"
    }
  }
}
```

**Respuesta recibida:**
```json
{
  "result": {
    "content": [
      {
        "type": "text",
        "text": "[\n  {\n    \"constraint_name\": \"ex_turno_profesional_sin_solape\",\n    \"table_name\": \"turno\",\n    \"constraint_definition\": \"EXCLUDE USING gist (profesional_id WITH =, tstzrange(inicio, fin, '[)'::text) WITH &&) WHERE ((((estado)::text <> ALL ((ARRAY['cancelado'::character varying, 'ausente'::character varying, 'reprogramado'::character varying])::text[])) AND (sobreturno IS NOT TRUE)))\"\n  },\n  {\n    \"constraint_name\": \"ex_turno_sillon_sin_solape\",\n    \"table_name\": \"turno\",\n    \"constraint_definition\": \"EXCLUDE USING gist (sillon_id WITH =, tstzrange(inicio, fin, '[)'::text) WITH &&) WHERE (((sillon_id IS NOT NULL) AND ((estado)::text <> ALL ((ARRAY['cancelado'::character varying, 'ausente'::character varying, 'reprogramado'::character varying])::text[])) AND (sobreturno IS NOT TRUE)))\"\n  }\n]"
      }
    ],
    "isError": false
  },
  "jsonrpc": "2.0",
  "id": 4
}
```

---

## 5. Conclusiones de Arquitectura para el Change C-15

Gracias a la introspección realizada mediante el servidor MCP:
1. **Estado de la tabla `bloqueo`:** Ya posee la columna `sillon_id (UUID, NULLABLE)` en la base de datos, lo que permite asociar un bloqueo directamente a un sillón físico sin requerir un rediseño de modelos base, pero carece de un constraint de exclusión propio que evite solapar dos bloqueos sobre el mismo sillón o cruzar bloqueos con turnos activos.
2. **Patrón de Exclusión GiST existente:** La tabla `turno` utiliza `tstzrange(inicio, fin, '[)'::text)` con el operador `&&` y predicados parciales `WHERE (estado NOT IN ('cancelado', 'ausente', 'reprogramado') AND sobreturno IS NOT TRUE)`.
3. **Fundamentación para C-15:** El Change C-15 debe modelar:
   - Validación en servicio para impedir crear un bloqueo si existen turnos confirmados en ese sillón.
   - Restricción de exclusión GiST sobre `bloqueo (sillon_id WITH =, tstzrange(desde, hasta, '[)') WITH &&)`.
   - Exclusión de turnos durante ventanas bloqueadas en el servicio de disponibilidad (`app/services/disponibilidad.py`).
