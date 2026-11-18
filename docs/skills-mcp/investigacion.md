# Ficha de Investigación: Integración de Skill Propia y Servidor MCP

* **Asignatura**: Metodología de Sistemas I — Universidad Tecnológica Nacional (UTN)
* **Proyecto**: Sistema de Gestión Odontológica (FastAPI + React + PostgreSQL)
* **Fecha de consulta y elaboración**: 03 de Noviembre de 2026
* **Autores**: Equipo de Desarrollo / Pareja Pedagógica de Metodología I

---

## 1. Necesidad Detectada y Change Elegido

### 1.1. Problema Real en el Consultorio Odontológico
En la atención odontológica, el **sillón dental (box)** no es un recurso pasivo; constituye una unidad quirúrgica y electrohidráulica integrada con suministro de agua estéril, compresores de aire, turbinas rotatorias y sistemas de succión de alta potencia. Su disponibilidad física está condicionada por dos contingencias críticas:

1. **Bioseguridad y Tiempos de Desinfección**: Tras procedimientos invasivos (extracciones, periodoncia o cirugías que liberan bioaerosoles y fluidos), los protocolos sanitarios y de bioseguridad exigen ventanas de ventilación, desinfección química de mangueras/superficies y recambio de instrumental esterilizado de **20 a 30 minutos** antes de permitir el ingreso del siguiente paciente.
2. **Mantenimiento Técnico Preventivo y Correctivo**: Fallas mecánicas en turbinas, descalibración de lámparas polimerizadoras o averías en compresores de aire inhabilitan temporalmente el sillón, incluso si el profesional asignado está disponible.

### 1.2. Justificación del Change C-15 (`bloqueo-sillones-desinfeccion-mantenimiento`)
El proyecto completó los 14 Changes fundacionales (`C-01` a `C-14`). El modelo actual dispone de la entidad `Bloqueo` (`app/models/disponibilidad.py`), pero fue concebida exclusivamente para registrar licencias o feriados del odontólogo (`profesional_id`). 

El **Change C-15** extiende la arquitectura del sistema vinculando bloqueos directamente al recurso físico `sillon_id`:
* **Extensión de C-01 (Anti-solapamiento físico)**: Aprovecha el índice GiST con extensión `btree_gist` sobre rangos `tstzrange` en PostgreSQL para que un bloqueo de sillón actúe como una barrera matemática inviolable que impida doble agendamiento a nivel motor.
* **Extensión de C-04 (Agenda de recepción)**: Visibiliza en la grilla operativa el estado del sillón (*operativo, en desinfección, en mantenimiento*) y excluye estos intervalos en el cálculo automático de disponibilidad (`C-03`).

---

## 2. Investigación de Skills Propias: Abanico y Selección

### 2.1. Meta-Skill Creadora Oficial: `skill-creator`
Para el diseño de la skill propia se investigó la especificación estándar abierta de **Agent Skills** (adoptada por Anthropic y motores agenticos avanzados). Se utilizó la meta-skill oficial **`skill-creator`**, la cual proporciona el andamiaje, el análisis de descriptores y las reglas de diseño modular requeridas para que las instrucciones del agente sean determinísticas, libres de ambigüedad y componibles.

### 2.2. Abanico de Skills Diseñadas por Capa Arquitectónica

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       ABANICO DE SKILLS PARA EL DOMINIO                     │
├───────────────────────────────┬─────────────────────────────────────────────┤
│ auditor-reglas-clinicas-sdd   │ Capa Arquitectura / SDD y Gobernanza Legal  │
│ interprete-odontograma-fdi    │ Capa Clínica / Datos Anatómicos FDI         │
│ redactor-postoperatorio-wa    │ Capa Paciente / Comunicación WhatsApp       │
└───────────────────────────────┴─────────────────────────────────────────────┘
```

1. **`auditor-reglas-clinicas-sdd`** *(Capa Arquitectura/Gobernanza)*: Audita artefactos OpenSpec (`proposal.md`, `design.md`, esquemas) confrontándolos con las reglas de negocio odontológicas (`knowledge-base/05_reglas_de_negocio.md`) y el marco legal argentino (Leyes 26.529 y 25.326).
2. **`interprete-odontograma-fdi`** *(Capa Clínica/Datos)*: Valida la notación FDI de dos dígitos (piezas 11 a 48 adultos, 51 a 85 niños) y sus 5 caras dentales (*Vestibular, Oclusal, Mesial, Distal, Lingual/Palatina*), verificando consistencia anatómica (ej. un incisivo carece de cara oclusal) y generando las coordenadas de dibujo SVG para el frontend de Ficha Clínica (`C-07`).
3. **`redactor-postoperatorio-wa`** *(Capa Paciente/Comunicación)*: Traduce prescripciones médicas complejas a indicaciones postoperatorias claras en español rioplatense (ej. *"no tomar mate con bombilla ni fumar por 48 h"* tras una extracción), sanitizando PII y formateando el mensaje para la pasarela de WhatsApp (`C-06`/`C-12`).

### 2.3. Elección y Especificación de la Skill: `auditor-reglas-clinicas-sdd`
Se selecciona `auditor-reglas-clinicas-sdd` para liderar la preparación de **C-15**, garantizando que el diseño de los bloqueos de sillones no viole ninguna política de agenda ni normativa de privacidad:

* **Propósito**: Auditar automáticamente propuestas de software para evitar desvíos en reglas de agenda clínica (RN-AG), acceso por roles (RBAC) y exposición de datos de pacientes (PII).
* **Cuándo se activa (Trigger)**:
  - Al formular o revisar artefactos de diseño de un change (`/opsx:propose C-15`).
  - Durante revisiones arquitectónicas previas a la escritura de código (`/opsx:apply`).
* **Entradas Requeridas**:
  1. Artefactos del Change (`openspec/changes/<change-name>/proposal.md`, `design.md`, `specs/`).
  2. Base de Conocimiento (`knowledge-base/05_reglas_de_negocio.md`, `04_modelo_de_datos.md`).
* **Procedimiento Paso a Paso**:
  1. *Extracción de Impacto*: Mapea qué tablas y endpoints modifica la propuesta (`Sillon`, `Bloqueo`, `Turno`).
  2. *Cruce Matricial*: Contrasta el diseño contra las reglas RN-AG-01 (anti-solapamiento estricto) y RN-AG-04 (intervalos mínimos entre turnos).
  3. *Control Legal y Privacidad*: Verifica el cumplimiento de la **Ley 26.529** (reserva de historia clínica) y la **Ley 25.326** (minimización: no exponer DNI ni teléfono en URLs, logs o responses públicas — Reglas R0 y R6).
  4. *Emisión de Dictamen*: Genera un informe Markdown clasificado en `APROBADO`, `ADVERTENCIA` o `BLOQUEANTE`, con sugerencias precisas de remediación.
* **Criterios de Control**: Cero tolerancia a propuestas que degraden el constraint GiST a validaciones exclusivas en software; veto mandatorio ante fugas de PII.

---

## 3. Comparación de Servidores MCP: Diversificación y Selección

### 3.1. Tabla Comparativa Técnica Multidominio

| Criterio | **PostgreSQL MCP** | **Playwright MCP** | **Docker MCP** | **Memory MCP (Grafo)** |
| :--- | :--- | :--- | :--- | :--- |
| **Familia / Capa** | Persistencia y Datos (SQL) | Presentación y UI (E2E Web) | Infraestructura (DevOps) | Cognitiva y Continuidad |
| **Herramientas Expuestas** | `query`, `describe-table`, `list-tables`. | `browser_navigate`, `browser_click`, `browser_snapshot`. | `list_containers`, `inspect_container`, `container_logs`. | `create_entities`, `search_nodes`, `open_nodes`. |
| **Requisitos Locales** | Node.js, `npx`, PostgreSQL local (`localhost:5432`). | Node.js, navegador Chromium headless. | Docker Daemon activo (`docker.sock`). | Entorno Node.js, archivo de almacenamiento local. |
| **Naturaleza de Permisos** | Limitado por credenciales del rol PostgreSQL asignado. | Sandbox cerrado en el proceso del navegador. | Privilegios de acceso al socket de Docker. | Restringido al espacio de trabajo local del agente. |
| **Riesgos Operativos** | Mutación involuntaria de datos si se otorga permiso de escritura. | Sobrecarga de memoria RAM por instancias huérfanas de Chrome. | Detención accidental de servicios en ejecución (`docker stop`). | Persistencia de alucinaciones o premisas obsoletas en el grafo. |
| **Mitigación de Seguridad** | Conexión obligatoria con **rol de solo lectura (`readonly`)**. | Timeouts estrictos (10 s) y navegación aislada sin cookies reales. | Conexión en modo `--read-only` sobre el socket Docker. | Curaduría y confirmación de observaciones clave. |
| **Aporte al Proyecto** | **Máximo para C-15**: Inspección de constraints GiST y tablas de bloqueo. | **Alto para C-03/C-10**: Validación visual del stepper de reserva pública. | **Medio**: Monitoreo de contenedores (Postgres/Redis) en Docker Compose. | **Transversal**: Retención de contexto entre sesiones del agente. |

### 3.2. Justificación de la Elección de `@modelcontextprotocol/server-postgres`
Para la preparación y diseño del Change C-15, se selecciona **`@modelcontextprotocol/server-postgres`**:
1. **Introspección real de constraints GiST**: La garantía anti-doble reserva del sistema reside en el motor de base de datos (`001_agenda_exclusion.py`). Para modelar el bloqueo de sillones por desinfección, el agente necesita examinar la definición exacta de `pg_constraint`, las funciones de rango y las columnas de `bloqueo` en la base de desarrollo.
2. **Alineación con las Reglas R0 y R2**: Conectado mediante un rol exclusivo de lectura, el servidor permite al agente inspeccionar la realidad operativa del motor **sin violar la Regla R2** (está prohibido alterar la DB a mano; todo cambio estructural debe nacer en una migración Alembic) y **sin riesgo para la Regla R0** (integridad y datos sintéticos).

### 3.3. Configuración e Instalación Reproducible (Sin Secretos)

Para instanciar el servidor MCP garantizando mínimo privilegio, se siguen estos pasos sin exponer credenciales en el repositorio:

1. **Creación de Rol de Solo Lectura en PostgreSQL** (ejecutado por el DBA en PostgreSQL):
   ```sql
   CREATE ROLE turnos_readonly WITH LOGIN PASSWORD 'turnos_ro_pass';
   GRANT CONNECT ON DATABASE turnos TO turnos_readonly;
   GRANT USAGE ON SCHEMA public TO turnos_readonly;
   GRANT SELECT ON ALL TABLES IN SCHEMA public TO turnos_readonly;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO turnos_readonly;
   ```
2. **Definición en la Configuración del Cliente MCP** (ej. `.gemini/antigravity/mcp/postgres.json` o configuración de entorno):
   ```json
   {
     "mcpServers": {
       "postgres-turnos": {
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
   *Nota*: La contraseña reside en variables de entorno locales o en `.env`, jamás commiteada al control de versiones (Regla R7).

---

## 4. Impacto en la Fundación y Fuentes Oficiales

### 4.1. Archivos de la Fundación a Actualizar en la Parte 2
Cuando la cátedra apruebe esta planificación, la Fase 2 impactará de manera controlada en:
* **`CHANGES.md`**: Incorporación de `C-15` en la fase operativa, estableciendo dependencias críticas con `C-01` y `C-04`, y fijando su nivel de gobernanza en **MEDIO**.
* **`.agents/skills/auditor-reglas-clinicas-sdd/SKILL.md`**: Materialización física de la skill diseñada con sus directivas operativas.
* **`.atl/skill-registry.md`**: Registro formal de la skill, especificando sus *triggers* de activación y *compact rules*.
* **`AGENTS.md` / `CLAUDE.md`**: Actualización de la matriz de habilidades de los agentes para reflejar la disponibilidad de la nueva herramienta de auditoría y del servidor MCP.

### 4.2. Fuentes Oficiales Consultadas

* **Model Context Protocol (Anthropic)**:
  - *Especificación del Protocolo y Arquitectura*: [https://modelcontextprotocol.io/introduction](https://modelcontextprotocol.io/introduction) (Consultado: 03/11/2026).
  - *Repositorio de Servidores de Referencia MCP*: [https://github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) (Consultado: 03/11/2026).
  - *Servidor PostgreSQL MCP*: [https://github.com/modelcontextprotocol/servers/tree/main/src/postgres](https://github.com/modelcontextprotocol/servers/tree/main/src/postgres) (Consultado: 03/11/2026).
* **Agent Skills Standard**:
  - *Anthropic Quickstarts & Agent Skills Pattern*: [https://github.com/anthropics/anthropic-quickstarts](https://github.com/anthropics/anthropic-quickstarts) (Consultado: 03/11/2026).
* **PostgreSQL Documentation**:
  - *Extension btree_gist y Exclusion Constraints*: [https://www.postgresql.org/docs/current/btree-gist.html](https://www.postgresql.org/docs/current/btree-gist.html) (Consultado: 03/11/2026).
* **Marco Normativo Argentino**:
  - *Ley 26.529 — Derechos del Paciente en su Relación con los Profesionales e Instituciones de la Salud*: [http://servicios.infoleg.gob.ar/infolegInternet/anexos/160000-164999/160432/norma.htm](http://servicios.infoleg.gob.ar/infolegInternet/anexos/160000-164999/160432/norma.htm) (Consultado: 03/11/2026).
  - *Ley 25.326 — Protección de los Datos Personales*: [http://servicios.infoleg.gob.ar/infolegInternet/anexos/60000-64999/64790/norma.htm](http://servicios.infoleg.gob.ar/infolegInternet/anexos/60000-64999/64790/norma.htm) (Consultado: 03/11/2026).
