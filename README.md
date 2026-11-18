# Sistema de Gestión Odontológica (Argentina)

Sistema de gestión odontológica integral desarrollado para consultorios y clínicas en Argentina. Combina agenda online sin cuenta previa, notificaciones nativas por WhatsApp, historia clínica electrónica (HCE) con odontograma digital (norma FDI), presupuestos, cobranza de señas mediante Mercado Pago, validación preventiva de obras sociales y lista de espera inteligente.

* **Stack Backend**: Python 3.12+ / FastAPI / SQLAlchemy 2.0 (async) / PostgreSQL 15+ / Alembic / Redis 7+
* **Stack Frontend**: React 18 / TypeScript 5 / Vite / Vitest / Playwright
* **Arquitectura**: Arquitectura Limpia basada en Especificaciones (SDD / OpenSpec) con gobernanza estricta.

---

## Integración MCP y Agent Skills

El proyecto incorpora el estándar abierto **Model Context Protocol (MCP)** y **Agent Skills** para dotar a los asistentes de inteligencia artificial de herramientas operativas y reglas de gobernanza clínica sin comprometer la seguridad ni la integridad de la base de datos.

### 1. Servidor MCP PostgreSQL (`@modelcontextprotocol/server-postgres`)

El servidor MCP permite al agente realizar introspección en tiempo real de la base de datos de desarrollo (consultar tablas, columnas, relaciones e índices GiST con extensiones de rango `tstzrange`), facilitando el diseño y la verificación arquitectónica de los Changes de persistencia (como C-01 y C-15).

#### Requisitos
* **Node.js**: v18+ instalado localmente (con `npx`).
* **PostgreSQL**: Instancia en ejecución (puerto 5432 o según Docker Compose).
* **Rol de solo lectura**: Usuario dedicado con permisos estrictos de lectura (R0/R2).

#### Variables de Entorno Necesarias
Para evitar hardcodear secretos (Regla R7), se utilizan las siguientes variables (definidas en tu entorno o en `.env` local):
* `DB_USER_RO`: Usuario de solo lectura (por defecto: `turnos_readonly`).
* `DB_PASSWORD_RO`: Contraseña del usuario de solo lectura (por defecto: `turnos_ro_pass`).
* `DB_HOST`: Host de la base de datos (`127.0.0.1` o `localhost`).
* `DB_PORT`: Puerto de PostgreSQL (`5432`).
* `DB_NAME`: Base de datos de desarrollo (`turnos`).

#### Pasos de Configuración
1. **Creación del rol seguro en PostgreSQL (una sola vez):**
   ```sql
   CREATE ROLE turnos_readonly WITH LOGIN PASSWORD 'turnos_ro_pass';
   GRANT CONNECT ON DATABASE turnos TO turnos_readonly;
   GRANT USAGE ON SCHEMA public TO turnos_readonly;
   GRANT SELECT ON ALL TABLES IN SCHEMA public TO turnos_readonly;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO turnos_readonly;
   ```
2. **Configuración en el cliente MCP:**
   Copiar `.mcp.example.json` a `.mcp.json` (o agregarlo a la configuración de tu cliente Claude Desktop, Antigravity o Cursor):
   ```json
   {
     "mcpServers": {
       "postgres-odontologia": {
         "command": "npx",
         "args": ["-y", "@modelcontextprotocol/server-postgres"],
         "env": {
           "DATABASE_URL": "postgresql://turnos_readonly:turnos_ro_pass@127.0.0.1:5432/turnos"
         }
       }
     }
   }
   ```

#### Comando de Comprobación
Para verificar que el servidor MCP se inicia e interactúa correctamente con PostgreSQL:
```bash
npx -y @modelcontextprotocol/server-postgres "postgresql://turnos_readonly:turnos_ro_pass@127.0.0.1:5432/turnos"
```
O ejecutando una consulta de prueba vía el agente solicitando:
`"Listá las tablas de la base de datos usando el servidor MCP postgres-odontologia"`

#### Solución de Problemas Comunes
* **Error `permission denied for table ...` ante un INSERT/UPDATE**: Comportamiento esperado. El rol `turnos_readonly` tiene restringida cualquier mutación (Regla R2). Todo cambio estructural debe realizarse a través de migraciones Alembic.
* **Error de conexión `ECONNREFUSED 127.0.0.1:5432`**: Asegurarse de que el servicio de PostgreSQL esté levantado (`docker compose up -d postgres` o servicio local activo).
* **Error `npx command not found`**: Verificar que Node.js esté instalado y añadido al `PATH` del sistema.

---

### 2. Skill Propia: `auditor-reglas-clinicas-sdd`

* **Ubicación**: `.agents/skills/auditor-reglas-clinicas-sdd/SKILL.md`
* **Propósito**: Auditar propuestas de cambio (`proposal.md`, `design.md`, `specs/`, `tasks.md`) antes de su implementación en código.
* **Garantías que audita**:
  1. **Anti-solapamiento estricto (RN-AG-01)**: Imposibilidad matemática de doble reserva de profesional o sillón.
  2. **Bioseguridad y Desinfección (RN-AG-04)**: Tiempos muertos obligatorios (20-30 min) para desinfección de bioaerosoles entre pacientes.
  3. **Marco Legal y Privacidad**: Ley 26.529 (Derechos del Paciente) y Ley 25.326 (Protección de Datos Personales / Regla R6 sin PII).
  4. **Persistencia Robusta**: Validación obligatoria de constraints de exclusión GiST (`btree_gist`) en PostgreSQL.
* **Dictamen emitido**: `[APROBADO]`, `[ADVERTENCIA]` o `[BLOQUEANTE]`.
