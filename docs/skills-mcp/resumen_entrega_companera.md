# Guía de Traspaso e Implementación: Skill Propia y Servidor MCP
## Trabajo Práctico de Metodología de Sistemas I — UTN (Entrega: Miércoles 18)

> **Destinataria:** Compañera de equipo / Su Agente de IA  
> **Proyecto:** Sistema de Gestión Odontológica (FastAPI + React + PostgreSQL + OpenSpec)  
> **Objetivo:** Implementar la Parte 2 (Materialización de Skill Propia y Servidor MCP) para grabar el video demostrativo.

---

## 1. Contexto Rápido del Proyecto y del TP

* **De qué trata el sistema:** Es un software de gestión clínica y turnos odontológicos para Argentina, con arquitectura limpia (FastAPI en backend, PostgreSQL con constraints de exclusión `btree_gist`, y React con TypeScript en frontend).
* **Consigna del Profesor:** 
  1. **Parte 1 (Investigación y Planificación):** Elegir un Change nuevo (C-15), investigar una meta-skill creadora (`skill-creator`), diseñar un abanico de skills del dominio y comparar servidores MCP eligiendo uno con justificación de seguridad (documentado en `docs/skills-mcp/investigacion.md`).
  2. **Parte 2 (Implementación y Video):** Instalar y configurar el servidor MCP elegido, crear los archivos físicos de la Skill Propia en el repositorio, actualizar la gobernanza (`CHANGES.md`, `AGENTS.md`) y grabar un video demostrando ambos funcionando en vivo.

---

## 2. Decisiones Tomadas en la Parte 1 (Ya Aprobadas)

| Componente | Elección | Justificación Pedagógica y Técnica |
| :--- | :--- | :--- |
| **Change Seleccionado** | **C-15:** `bloqueo-sillones-desinfeccion-mantenimiento` | Resuelve un problema real de bioseguridad: ventanas de 20-30 min para desinfección de bioaerosoles entre pacientes y mantenimiento de sillones, bloqueando el sillón físico en la DB. |
| **Skill Propia Elegida** | **`auditor-reglas-clinicas-sdd`** | Actúa como auditor automático de arquitectura: revisa las propuestas (`proposal.md`, `design.md`) antes de codear, garantizando que respeten las reglas odontológicas (RN-AG-01 anti-solapamiento) y las Leyes de Salud 26.529 y 25.326 (privacidad de datos del paciente / PII). |
| **Servidor MCP Elegido** | **`@modelcontextprotocol/server-postgres`** | Permite al agente inspeccionar directamente en la base PostgreSQL las tablas, tipos de rangos `tstzrange` y constraints GiST en **modo solo lectura (`readonly`)**, sin violar la regla de no alterar la DB a mano. |

---

## 3. Plan de Acción para la Parte 2 (Paso a Paso)

Tu agente debe ejecutar estas 4 tareas concretas en el repositorio:

### Paso 1: Configurar el Servidor MCP de PostgreSQL (Solo Lectura)

1. **Crear usuario de solo lectura en PostgreSQL:**
   En una consola de PostgreSQL (`psql` o pgAdmin con usuario `postgres` o `turnos`):
   ```sql
   -- Crear rol con permisos estrictos de SELECT (R0 y R2)
   CREATE ROLE turnos_readonly WITH LOGIN PASSWORD 'turnos_ro_pass';
   GRANT CONNECT ON DATABASE turnos TO turnos_readonly;
   GRANT USAGE ON SCHEMA public TO turnos_readonly;
   GRANT SELECT ON ALL TABLES IN SCHEMA public TO turnos_readonly;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO turnos_readonly;
   ```

2. **Registrar el MCP en el entorno del Agente:**
   En la configuración de MCP de tu cliente de IA (por ejemplo en el archivo de configuración de Claude Desktop, Antigravity, Cursor o `.mcp.json`):
   ```json
   {
     "mcpServers": {
       "postgres-odontologia": {
         "command": "npx",
         "args": [
           "-y",
           "@modelcontextprotocol/server-postgres"
         ],
         "env": {
           "DATABASE_URL": "postgresql://turnos_readonly:turnos_ro_pass@127.0.0.1:5432/turnos"
         }
       }
     }
   }
   ```
   *Herramientas que gana el agente:* `query`, `describe-table`, `list-tables` (todas limitadas por el usuario `turnos_readonly` para garantizar seguridad).

---

### Paso 2: Materializar la Skill Propia (`auditor-reglas-clinicas-sdd`)

Crear la carpeta `.agents/skills/auditor-reglas-clinicas-sdd/` y el archivo `SKILL.md` con las instrucciones que el agente cargará automáticamente:

* **Ruta:** `.agents/skills/auditor-reglas-clinicas-sdd/SKILL.md`
* **Contenido obligatorio:**
  - Frontmatter con `name: auditor-reglas-clinicas-sdd` y descripción clara.
  - Reglas de verificación:
    1. **Chequeo Anti-solapamiento:** Verificar que todo bloqueo afecte a `sillon_id` con rango `tstzrange` y no permita colisiones.
    2. **Chequeo Legal (Ley 26.529 y 25.326):** Prohibir la inclusión de DNI, nombres de pacientes o datos médicos en URLs, respuestas públicas o logs.
    3. **Chequeo RBAC:** Confirmar que solo el rol `admin` o `recepcion` pueda registrar bloqueos de sillones.
  - Formato del Dictamen: Salida estructurada con `[APROBADO]`, `[ADVERTENCIA]` o `[BLOQUEANTE]`.

---

### Paso 3: Registrar el Change C-15 y Actualizar Gobernanza

1. **En `CHANGES.md`:**
   Agregar la ficha de C-15:
   ```markdown
   ### C-15: Bloqueo de sillones por desinfección y mantenimiento
   - **Estado:** `[ ]` (Listo para propuesta)
   - **Gobernanza:** MEDIO
   - **Dependencias:** C-01 (anti-solapamiento motor), C-04 (agenda de recepción)
   - **Alcance:** Modelo de `Bloqueo` con clave foránea a `sillon_id`, validación en motor y visualización en grilla.
   ```
2. **En `AGENTS.md` / `CLAUDE.md`:**
   Agregar la nueva skill a la tabla de skills disponibles bajo el rol de Arquitectura/Transversal.

---

### Paso 4: Probar la Skill con el Agente (Simulación de Auditoría)

Pedirle al agente que ejecute una auditoría sobre el borrador de propuesta de C-15:
* El agente debe leer `knowledge-base/05_reglas_de_negocio.md`, cargar la skill `auditor-reglas-clinicas-sdd` y emitir un dictamen formal aprobando la arquitectura del bloqueo de sillones.

---

## 4. Prompt Maestro para Copiar y Pegar en el Agente de tu Compañera

Copiá y pegale este prompt textual a tu agente:

```text
Hola. Estamos realizando el Trabajo Práctico de Metodología de Sistemas I (UTN) para integrar una Skill Propia y un servidor MCP en nuestro proyecto "Sistema de Gestión Odontológica".

La investigación teórica de la Parte 1 ya está lista y aprobada en docs/skills-mcp/investigacion.md. Ahora necesitamos implementar la Parte 2 en el código:

1. MATERIALIZAR LA SKILL PROPIA:
   - Creá el archivo `.agents/skills/auditor-reglas-clinicas-sdd/SKILL.md` siguiendo el estándar oficial de Agent Skills.
   - Definí sus directivas: auditar propuestas confrontando contra knowledge-base/05_reglas_de_negocio.md (RN-AG-01 anti-solapamiento físico), RN-AU (auditoría), y las leyes argentinas 26.529 (historia clínica) y 25.326 (protección de datos personales / R6 sin PII).
   - Incluí la plantilla del dictamen de salida (APROBADO, ADVERTENCIA, BLOQUEANTE).

2. REGISTRAR C-15 Y GOBERNANZA:
   - Agregá en CHANGES.md el Change C-15: "bloqueo-sillones-desinfeccion-mantenimiento" (Gobernanza MEDIO, dependiente de C-01 y C-04).
   - Registrá la nueva skill en AGENTS.md y CLAUDE.md dentro de las skills disponibles.

3. CONFIGURAR EL SERVIDOR MCP POSTGRESQL:
   - Generá el archivo de configuración `.mcp.json` (o el formato correspondiente) configurando `@modelcontextprotocol/server-postgres` apuntando a `postgresql://turnos_readonly:turnos_ro_pass@127.0.0.1:5432/turnos`.
   - Explicame cómo ejecutar el script SQL para crear el rol turnos_readonly con permisos exclusivos de SELECT.

4. EJECUTAR UNA DEMOSTRACIÓN EN VIVO:
   - Usá la skill recién creada para auditar la especificación del Change C-15 y mostrame el dictamen emitido.
   - Verificá que la base de datos y los tests sigan en verde.
```

---

## 5. Estructura y Guión para la Grabación del Video (3 a 5 Minutos)

El video debe ser dinámico y dividirse en 3 partes claras:

### Minuto 0:00 a 1:00 — Introducción y Problema
* **Qué decir:** *"Para este trabajo de Metodología I, integramos una Skill Propia y el protocolo MCP al sistema odontológico. Detectamos la necesidad del Change C-15: en odontología, tras cirugías o limpiezas que liberan bioaerosoles, el sillón requiere 20-30 minutos de desinfección obligatoria antes del siguiente paciente, o paradas por mantenimiento técnico."*
* **Qué mostrar:** El archivo `docs/skills-mcp/investigacion.md` o el diagrama de arquitectura.

### Minuto 1:00 a 2:30 — Demostración del Servidor MCP
* **Qué decir:** *"Para que el agente pueda razonar sobre la disponibilidad física real sin violar las reglas de seguridad, conectamos el servidor oficial `@modelcontextprotocol/server-postgres`. Usamos un rol de solo lectura (`turnos_readonly`), respetando el principio de mínimo privilegio y asegurando que ninguna modificación a la DB se haga a mano."*
* **Qué mostrar:** La configuración del MCP y al agente ejecutando una herramienta del MCP (como `describe-table` o `list-tables` sobre la tabla `sillon` o `bloqueo`).

### Minuto 2:30 a 4:30 — Demostración de la Skill Propia
* **Qué decir:** *"Diseñamos la skill `auditor-reglas-clinicas-sdd`. Su rol es auditar automáticamente las propuestas de cambio. Cuando formulamos el Change C-15, la skill analiza que el bloqueo de sillón esté respaldado por los constraints matemáticos GiST de PostgreSQL y valida que no se exponga información confidencial del paciente según la Ley 25.326."*
* **Qué mostrar:** El archivo `.agents/skills/auditor-reglas-clinicas-sdd/SKILL.md` y la ejecución en vivo del agente generando el dictamen `[APROBADO]` para C-15.

### Minuto 4:30 a 5:00 — Conclusión
* **Qué decir:** *"Con el MCP y la Skill Propia, logramos un flujo de desarrollo asistido por IA donde el agente cuenta con ojos sobre la base de datos y un marco de gobernanza estricto para no cometer errores clínicos ni legales."*
