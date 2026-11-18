# Guion Definitivo del Video — TPI Metodología de Sistemas I
## Sistema de Gestión Odontológica (FastAPI + React + PostgreSQL + OpenSpec)

* **Asignatura:** Metodología de Sistemas I — Universidad Tecnológica Nacional (UTN)
* **Comisión:** Comisión 1
* **Equipo de Desarrollo (4 integrantes):**
  1. **Ivana Gutierrez** (Integrante 1)
  2. **Rayssa Alejo** (Integrante 2)
  3. **Julieta Chavez** (Integrante 3)
  4. **Brisa Muñoz** (Integrante 4)
* **Duración total:** Máximo 10 minutos (cronometrado bloque a bloque).
* **Cámara web:** Encendida al menos durante la presentación personal y transiciones.
* **Reglas de seguridad:** Datos 100 % sintéticos (R0), sin exponer contraseñas, tokens reales ni PII de pacientes en pantalla (R6/R7).

---

## Bloque 0: Preparación Previa a Grabar (No grabar la instalación)

> **Importante:** Este bloque se realiza antes de encender la grabación de pantalla para que el video sea fluido y conciso.

### Checklist Técnico de Arranque:
1. **Base de Datos y Backend:**
   - PostgreSQL corriendo localmente en el puerto `5432` con la base `turnos`.
   - Desde la terminal en `backend/`:
     ```bash
     .\.venv\Scripts\alembic.exe upgrade head
     .\.venv\Scripts\python.exe -m app.seed_demo
     ```
   - Servidor FastAPI corriendo en puerto `8000`:
     ```bash
     .\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
     ```
   - Verificar Swagger en: [http://localhost:8000/docs](http://localhost:8000/docs).
2. **Frontend:**
   - Servidor Vite en `frontend/`:
     ```bash
     npm run dev
     ```
   - Verificar app en: [http://localhost:5173](http://localhost:5173).
3. **Pestañas preparadas en el navegador y VS Code:**
   - Pestaña 1: Repositorio en VS Code con `CHANGES.md`, `.agents/skills/auditor-reglas-clinicas-sdd/SKILL.md` y `openspec/changes/archive/`.
   - Pestaña 2: Documentos de MCP y Skill (`docs/skills-mcp/investigacion.md`, `docs/skills-mcp/dictamen-c15.md`, `.mcp.example.json` y `docs/skills-mcp/evidencias/01_mcp_postgres_introspeccion.md`).
   - Pestaña 3: Swagger UI ([http://localhost:8000/docs](http://localhost:8000/docs)).
   - Pestaña 4: Frontend ([http://localhost:5173/login](http://localhost:5173/login) o `/agenda`).

---

## Bloque 1 (0:00 - 0:30) — Presentación del Equipo y Alcance

* **Modalidad:** Cámara encendida de las 4 integrantes al presentarse.
* **Qué mostrar en pantalla:** Portada del proyecto, archivo `CHANGES.md` o repositorio de GitHub abierto.

| Rol | Quién habla | Qué decir (Texto Guion) |
| :--- | :--- | :--- |
| **Intro general** | **Ivana Gutierrez** | *"Hola a todos. Somos Ivana Gutierrez, Rayssa Alejo, Julieta Chavez y Brisa Muñoz, integrantes del Grupo de la Comisión 1. En este video presentamos el Trabajo Práctico Integrador de Metodología de Sistemas I: nuestro Sistema de Gestión Odontológica y Agenda Clínica."* |
| **Contexto SDD** | **Rayssa Alejo** | *"Continuamos la base del proyecto del Parcial 2 aplicando una metodología ágil guiada por especificaciones, SDD y OpenSpec, sobre la misma base de código y repositorio."* |
| **Alcance C-01..14** | **Julieta Chavez** | *"El alcance alcanzado en el sistema incluye los Changes C-01 al C-14 completados, verificados con pruebas automatizadas y formalmente archivados según el roadmap."* |
| **Aclaración C-15** | **Brisa Muñoz** | *"El Change C-15 queda formalmente preparado como pendiente y no lo contamos como implementado. En este video mostraremos el avance del sistema, nuestra Skill propia, el servidor MCP, la suite de pruebas y el sistema funcionando en vivo con datos sintéticos."* |

---

## Bloque 2 (0:30 - 3:00) — Recorrido de Changes Completos (Elegidos)

* **Qué mostrar en pantalla:**
  - Archivo `CHANGES.md` mostrando los 14 changes en estado `[x] archivado`.
  - Carpeta `openspec/changes/archive/` expandiendo los 4 changes elegidos.
  - Artefactos SDD representativos (`proposal.md`, `specs/`, `tasks.md`).

| Sección / Change | Quién habla | Qué mostrar | Qué decir (Texto Guion) |
| :--- | :--- | :--- | :--- |
| **Introducción Bloque 2** | **Ivana Gutierrez** | `CHANGES.md` abierto | *"En `CHANGES.md` vemos el roadmap operativo con los 14 changes completados. Vamos a recorrer cuatro de los más representativos que cubren el ciclo SDD: C-01, C-02, C-03 y C-05. Recordamos que C-15 queda pendiente y no lo contamos como completo."* |
| **C-01: Anti-solapamiento base** | **Ivana Gutierrez** | Carpeta `openspec/changes/archive/2026-10-07-crear-turno-.../` | *"El Change C-01 fue el núcleo fundacional: crear turnos evitando solapamientos por odontólogo y por sillón físico. Su necesidad fue resolver la doble reserva concurrente. ¿Qué hicimos? Diseñamos el modelo con una garantía matemática en PostgreSQL usando restricciones de exclusión GiST con tipos de rango `tstzrange`. Fue verificado con tests automáticos de colisión y archivado en OpenSpec."* |
| **C-02: Auth JWT y Auditoría** | **Rayssa Alejo** | Carpeta `openspec/changes/archive/2026-10-07-auth-jwt-.../` | *"El Change C-02 implementó la seguridad y el control de acceso del personal. El problema era asegurar que solo usuarios autenticados operen según su rol (Admin, Recepción u Odontólogo). Implementamos autenticación JWT con rotación de refresh tokens, matriz RBAC y registro de auditoría estricto sin almacenar PII, cumpliendo la Ley 25.326. Todo verificado con tests y archivado."* |
| **C-03: Disponibilidad Real** | **Julieta Chavez** | Carpeta `openspec/changes/archive/2026-10-08-disponibilidad-.../` | *"El Change C-03 resolvió la consulta de disponibilidad real y la reserva pública online sin obligar al paciente a crearse una cuenta. El algoritmo calcula los slots libres cruzando la agenda del profesional, los sillones de la sede y los bloqueos existentes, permitiendo reservar en 3 simples pasos con datos sintéticos."* |
| **C-05: Autogestión por Token** | **Brisa Muñoz** | Carpeta `openspec/changes/archive/2026-10-10-autogestion-.../` | *"El Change C-05 agregó la autogestión para el paciente. Resuelve la necesidad de confirmar, cancelar o reprogramar un turno desde el celular sin necesidad de llamar por teléfono ni recordar contraseñas, mediante un token público seguro enviado por WhatsApp, validando estados y plazos de antelación mínima."* |
| **Cierre Bloque 2** | **Ivana Gutierrez** | Vista general de `archive/` | *"Estos changes evidencian la evolución desde la base de datos segura hasta la experiencia del paciente. Todos los demás están archivados en el repo; a continuación vemos la Skill propia, el servidor MCP, las pruebas y la demo en vivo."* |

---

## Bloque 3 (3:00 - 6:00) — Skill Propia y Servidor MCP

* **Lideran:** Rayssa Alejo (Skill Propia) y Julieta Chavez (Servidor MCP).
* **Complementan:** Ivana Gutierrez y Brisa Muñoz (evidenciando comprensión técnica).
* **Qué mostrar en pantalla:**
  1. `docs/skills-mcp/investigacion.md` (investigación de la cátedra).
  2. `.agents/skills/auditor-reglas-clinicas-sdd/SKILL.md` y registro en `.atl/skill-registry.md` y `AGENTS.md`.
  3. `docs/skills-mcp/dictamen-c15.md` (dictamen formal de auditoría sobre C-15).
  4. `.mcp.json` / `.mcp.example.json` (configuración segura con `turnos_readonly`).
  5. Terminal o `docs/skills-mcp/evidencias/01_mcp_postgres_introspeccion.md` mostrando la ejecución real de introspección MCP.

| Rol | Quién habla | Qué mostrar | Qué decir (Texto Guion) |
| :--- | :--- | :--- | :--- |
| **Explicación Skill Propia** | **Rayssa Alejo** | `docs/skills-mcp/investigacion.md` y `.agents/skills/.../SKILL.md` | *"Para este trabajo integramos una Skill Propia: `auditor-reglas-clinicas-sdd`. Nace de investigar la meta-skill oficial `skill-creator` y el estándar abierto de Agent Skills. Su propósito es auditar automáticamente las propuestas SDD antes de escribir código, verificando que respeten las reglas de bioseguridad, anti-solapamiento (RN-AG-01), la Ley 26.529 de Historia Clínica y la Ley 25.326 de Protección de Datos Personales."* |
| **Aplicación a C-15** | **Rayssa Alejo** | `docs/skills-mcp/dictamen-c15.md` | *"La aplicamos sobre el Change C-15 de preparación: 'Bloqueo de sillones por desinfección y mantenimiento'. El resultado fue el dictamen formal en `docs/skills-mcp/dictamen-c15.md`, con resultado APROBADO, validando que el bloqueo de 20 a 30 minutos por bioaerosoles esté respaldado por constraints GiST y sin exponer datos de pacientes."* |
| **Explicación Servidor MCP** | **Julieta Chavez** | `.mcp.json` y `README.md` | *"En paralelo, integramos el protocolo abierto Model Context Protocol conectando el servidor oficial `@modelcontextprotocol/server-postgres`. Lo configuramos con un usuario exclusivo de solo lectura: `turnos_readonly`, respetando el principio de mínimo privilegio y la Regla R2: el agente tiene prohibido modificar la base de datos a mano."* |
| **Uso real del MCP** | **Julieta Chavez** | `01_mcp_postgres_introspeccion.md` o terminal ejecutando MCP | *"Ejecutamos en vivo la herramienta `query` del servidor MCP sobre la tabla `bloqueo` y consultamos `pg_constraint`. El MCP nos devolvió en formato JSON-RPC la estructura exacta de columnas y los constraints GiST `ex_turno_sillon_sin_solape`. Esto le permitió al agente diseñar C-15 conociendo la realidad del motor sin asumir supuestos."* |
| **Diferenciación conceptual** | **Ivana Gutierrez** | `.atl/skill-registry.md` y `AGENTS.md` | *"Es fundamental destacar la diferencia: la Skill aporta el conocimiento y los criterios de negocio clínicos para auditar el diseño; mientras que el servidor MCP es un puente de protocolo que le otorga herramientas operativas y seguras al modelo para acceder al contexto real del sistema."* |
| **Aporte de seguridad** | **Brisa Muñoz** | Código SQL de permisos `turnos_readonly` | *"Y ese acceso es 100 % seguro: si el agente intentara mutar la base por MCP, PostgreSQL rechaza la operación por permisos insuficientes, garantizando la integridad de nuestros datos."* |

---

## Bloque 4 (6:00 - 10:00) — Pruebas Automatizadas y Demo Funcional en Vivo

* **Lidera Pruebas:** Brisa Muñoz.
* **Demostración de Endpoints:** Ivana Gutierrez, Rayssa Alejo y Julieta Chavez.
* **Qué mostrar en pantalla:**
  1. Terminal ejecutando tests de backend (`pytest`) y frontend (`npm test`).
  2. Swagger UI interactivo en [http://localhost:8000/docs](http://localhost:8000/docs).
  3. Frontend en [http://localhost:5173/login](http://localhost:5173/login) y `/agenda`.

| Sección | Quién habla | Qué mostrar en pantalla | Qué decir (Texto Guion) |
| :--- | :--- | :--- | :--- |
| **Ejecución de Tests** | **Brisa Muñoz** | Terminal ejecutando:<br>`pytest -q --tb=short`<br>y `npm test` | *"Mostramos la verificación automatizada con datos sintéticos. En el backend ejecutamos `pytest` y vemos los 305 tests pasando en verde con 0 fallos. En el frontend ejecutamos `npm test` con Vitest y vemos las 10 suites con 64 tests en verde. Esto demuestra que la base técnica es sólida y no tiene regresiones."* |
| **Swagger: Login y Auth (C-02)** | **Ivana Gutierrez** | Swagger UI (`/api/v1/auth/login`) y botón Authorize | *"Pasamos a Swagger en `/docs`. Ejecutamos `POST /api/v1/auth/login` con el usuario demo `admin.demo@consultorio.example` (sin mostrar credenciales reales). Obtenemos el JWT con código 200 OK, lo cargamos en el botón Authorize y ejecutamos `GET /api/v1/auth/me`: la API responde 200 OK con los roles del usuario, demostrando la autenticación de C-02 sobre la base de C-01."* |
| **Swagger: Disponibilidad (C-03)** | **Rayssa Alejo** | Swagger UI (`/api/v1/disponibilidad`) | *"Ahora probamos `GET /api/v1/disponibilidad` enviando la prestación demo de limpieza y el profesional A para el día `2026-12-01`. Vemos cómo el motor responde 200 OK devolviendo únicamente los slots libres reales, respetando la agenda y los tiempos de atención (C-03)."* |
| **Swagger: Autogestión (C-05)** | **Julieta Chavez** | Swagger UI (`/turnos/publicos/{token}`) | *"En `GET /api/v1/turnos/publicos/demo-token-c05-autogestion-ficticia-no-real` consultamos el turno sin autenticación. La API responde 200 OK con los datos del turno y la política de cancelación, demostrando la autogestión de C-05 sin exponer datos sensibles del paciente."* |
| **Demo Frontend / Agenda (Extra)** | **Ivana Gutierrez** | Navegador en `http://localhost:5173/agenda` | *(Opcional)* *"En el frontend vemos la Agenda Operativa de Recepción en tiempo real: los turnos se distribuyen por columnas de profesional y sillón, con estados confirmados, presentes y sobreturnos identificados con total claridad."* |
| **Cierre Formal del Video** | **Brisa Muñoz** | Pantalla final con `CHANGES.md` o repo | *"En conclusión: demostramos el alcance completo de los 14 changes fundacionales funcionando, la integración real del servidor MCP PostgreSQL en modo solo lectura, y la auditoría clínica de C-15 con nuestra Skill propia. C-15 queda formalmente documentado como pendiente para el próximo ciclo. Todo verificado con datos ficticios y sin secretos expuestos. ¡Muchas gracias!"* |

---

## Checklist Final antes de Entregar

- [x] Video con duración ≤ 10 minutos.
- [x] Participación de las 4 integrantes (Ivana Gutierrez, Rayssa Alejo, Julieta Chavez, Brisa Muñoz).
- [x] Cámara encendida en la presentación personal.
- [x] Sistema levantado y funcionando en vivo (Swagger UI y Frontend).
- [x] Pruebas automatizadas en verde (`pytest` y `npm test`).
- [x] Evidencia concreta de la Skill Propia (`auditor-reglas-clinicas-sdd`) y del dictamen de C-15.
- [x] Evidencia concreta del servidor MCP (`@modelcontextprotocol/server-postgres`) en modo `turnos_readonly`.
- [x] C-15 identificado claramente como pendiente (no implementado).
- [x] Archivo `.txt` de entrega con link de video, repo, comisión e integrantes completos.
