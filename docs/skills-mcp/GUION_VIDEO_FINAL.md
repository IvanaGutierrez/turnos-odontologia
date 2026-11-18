# Guion Oficial de Grabación de Video — TPI Metodología de Sistemas I

> **Proyecto:** Sistema de Gestión Odontológica y Agenda Clínica (FastAPI + React + PostgreSQL + OpenSpec / SDD)  
> **Comisión:** Comisión 1 | **Materia:** Metodología de Sistemas I (UTN)  
> **Modalidad:** 4 Bloques Secuenciales continuos de 2 minutos y 30 segundos por integrante (Duración total: **10:00 exactos**).  
> **Equipo:**  
> 1. **Integrante 1:** Ivana Gutierrez (00:00 a 02:30 — 2m 30s continuos)  
> 2. **Integrante 2:** Rayssa Alejo (02:30 a 05:00 — 2m 30s continuos)  
> 3. **Integrante 3:** Julieta Chavez (05:00 a 07:30 — 2m 30s continuos)  
> 4. **Integrante 4:** Brisa Muñoz (07:30 a 10:00 — 2m 30s continuos)  

---

## ⚠️ Reglas de Seguridad y Criterios Obligatorios de Cátedra

1. **Cámara encendida:** Cada integrante debe encender su cámara (o tenerla visible en recuadro) al menos durante los primeros 15-20 segundos de su bloque al presentarse.
2. **Regla R0 y R6 (Protección de Datos):** Solo se muestran datos 100% sintéticos/ficticios. Prohibido exponer DNI, teléfonos o historias clínicas reales de pacientes.
3. **Regla R7 (Seguridad):** Nunca mostrar contraseñas reales, variables `.env` ni tokens de producción. Se muestra `.env.example` y `.mcp.example.json`.
4. **C-15 Pendiente:** Destacar enfáticamente que los Changes **C-01 al C-14 están completados y archivados**, y que **C-15 queda formalmente preparado como pendiente `[ ]`**, sin contar como implementado.
5. **Ritmo de voz:** Hablar a ritmo claro y pausado (aprox. 120-130 palabras por minuto). El texto de cada bloque está calibrado en ~300 palabras para durar exactamente **2 minutos y 30 segundos**.

---

## 🛠️ Checklist Técnico Previo (Tener listo antes de grabar)

- [ ] **Backend levantado en puerto 8000:** `cd backend; .\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000`
- [ ] **Frontend levantado en puerto 5173:** `cd frontend; npm run dev`
- [ ] **Swagger UI abierto en el navegador:** `http://localhost:8000/docs`
- [ ] **Frontend abierto en el navegador:** `http://localhost:5173/agenda`
- [ ] **Pestañas de VS Code preparadas:**
  - `CHANGES.md` (con C-01 a C-14 en `[x]` y C-15 en `[ ]`).
  - `.agents/skills/auditor-reglas-clinicas-sdd/SKILL.md`.
  - `docs/skills-mcp/dictamen-c15.md`.
  - `docs/skills-mcp/evidencias/01_mcp_postgres_introspeccion.md`.
  - `.mcp.example.json` y `README.md` (sección MCP).

---

# 🎬 Guion Paso a Paso por Integrante (2m 30s por persona)

---

### 🔹 BLOQUE 1: Ivana Gutierrez — Integrante 1
⏱️ **Tiempo asignado:** `00:00 a 02:30` (2 minutos y 30 segundos continuos)  
🎯 **Temas:** Presentación grupal + Contexto y Changes completados (C-01 a C-14) + Fundamentación del problema real y preparación de C-15.

| Minuto | Qué mostrar en pantalla | Qué decir palabra por palabra (Diálogo de Ivana) |
| :--- | :--- | :--- |
| **00:00 – 00:30**<br>*(30 seg)* | **Cámara encendida en primer plano.**<br>De fondo: Portada del repositorio GitHub (`IvanaGutierrez/turnos-odontologia`). | “Hola a todos, mi nombre es **Ivana Gutierrez** y junto a mis compañeras **Rayssa Alejo**, **Julieta Chavez** y **Brisa Muñoz**, conformamos el equipo de la Comisión 1 de Metodología de Sistemas I.<br><br>En este video presentamos nuestro Trabajo Práctico Integrador: el **Sistema de Gestión Odontológica y Agenda Clínica**, desarrollado sobre la base del Parcial 2 con FastAPI, React y PostgreSQL, aplicando una metodología guiada por especificaciones mediante OpenSpec y SDD.” |
| **00:30 – 01:25**<br>*(55 seg)* | **Compartir pantalla:** Abrir `CHANGES.md` en VS Code mostrando la tabla de changes.<br>Luego desplegar la carpeta `openspec/changes/archive/`. | “Como vemos en `CHANGES.md`, nuestro roadmap operativo cuenta con los **14 changes iniciales (C-01 al C-14) completamente terminados, testeados y formalmente archivados** en OpenSpec.<br><br>Entre ellos, el **Change C-01** fue el núcleo fundacional de la agenda, resolviendo el problema de la doble reserva concurrente con restricciones físicas de exclusión GiST en PostgreSQL.<br><br>Sobre esa base construimos la seguridad con JWT y roles en **C-02**, el motor de cálculo de disponibilidad en **C-03**, la agenda de recepción en **C-04**, la autogestión de turnos por token público en **C-05**, y los módulos de cobros, odontograma, obras sociales y recordatorios hasta C-14.” |
| **01:25 – 02:25**<br>*(60 seg)* | **Pantalla:** Abrir `openspec/changes/C-15-bloqueo-sillones-desinfeccion-mantenimiento/proposal.md`.<br>Mostrar sección de justificación y `CHANGES.md` con C-15 en `[ ]`. | “Para esta entrega se nos solicitó investigar e incorporar una necesidad real del consultorio. Detectamos que los tratamientos odontológicos invasivos generan bioaerosoles, requiriendo un **tiempo de desinfección y ventilación de 20 a 30 minutos** entre pacientes; y además los sillones requieren **mantenimiento técnico preventivo**.<br><br>Por eso diseñamos el **Change C-15: Bloqueo de sillones por desinfección y mantenimiento**, como extensión natural de C-01 y C-04.<br><br>Queremos enfatizar la regla de cátedra: **C-15 queda formalmente especificado y preparado en estado pendiente `[ ]`**, y no lo contamos como implementado en código para este video.” |
| **02:25 – 02:30**<br>*(5 seg)* | Cámara o foco en el código de C-15. | “A continuación, mi compañera **Rayssa Alejo** presentará la integración de nuestro servidor MCP y cómo inspecciona la base de datos de forma segura.” |

---

### 🔹 BLOQUE 2: Rayssa Alejo — Integrante 2
⏱️ **Tiempo asignado:** `02:30 a 05:00` (2 minutos y 30 segundos continuos)  
🎯 **Temas:** Servidor MCP PostgreSQL (`@modelcontextprotocol/server-postgres`) + Seguridad `turnos_readonly` (R0/R2/R7) + Introspección real JSON-RPC.

| Minuto | Qué mostrar en pantalla | Qué decir palabra por palabra (Diálogo de Rayssa) |
| :--- | :--- | :--- |
| **02:30 – 03:15**<br>*(45 seg)* | **Cámara encendida 15 seg**, luego pantalla en `README.md` (sección *Integración MCP y Agent Skills*) y archivo `.mcp.example.json`. | “Hola a todos, soy **Rayssa Alejo**. En este segundo bloque voy a explicar la integración de nuestro servidor MCP y mostrar la introspección técnica de la base de datos.<br><br>Lo primero que debemos clarificar conceptualmente es que **un servidor MCP NO es una skill**. Model Context Protocol es un protocolo abierto y estándar que conecta a los modelos de IA con herramientas operativas desacopladas.<br><br>En nuestro proyecto conectamos el servidor oficial `@modelcontextprotocol/server-postgres`, el cual expone herramientas nativas como `query`, `describe-table` y `list-tables`.” |
| **03:15 – 04:10**<br>*(55 seg)* | **Pantalla:** Mostrar terminal o archivo de configuración mostrando los permisos del rol `turnos_readonly`.<br>Mostrar `.gitignore` donde figura `.mcp.json`. | “Para garantizar la seguridad de la información y cumplir estrictamente nuestras **Reglas de Oro R0, R2 y R7**, la configuración se diseñó bajo el principio de mínimo privilegio:<br><br>Primero, creamos en PostgreSQL un usuario exclusivo llamado `turnos_readonly`, otorgándole únicamente permisos de `CONNECT`, `USAGE` y `SELECT` sobre el esquema público.<br><br>Esto hace cumplir la **Regla R2**: el agente tiene físicamente prohibido mutar datos a mano mediante el MCP; cualquier intento de `INSERT` o `UPDATE` es rechazado por el motor con `InsufficientPrivilegeError`.<br><br>Y bajo la **Regla R7**, los secretos nunca se commitean: `.mcp.json` está en `.gitignore` y versionamos únicamente `.mcp.example.json`.” |
| **04:10 – 04:55**<br>*(45 seg)* | **Pantalla:** Abrir `docs/skills-mcp/evidencias/01_mcp_postgres_introspeccion.md`.<br>Hacer scroll por la respuesta JSON-RPC con las columnas de `bloqueo` y constraints GiST de `turno`. | “En este archivo de evidencias vemos la ejecución real de la herramienta `query` del servidor MCP sobre PostgreSQL.<br><br>El servidor nos devolvió en formato estándar JSON-RPC la estructura exacta de la tabla `bloqueo` —con sus columnas `motivo`, `fecha_inicio` y `fecha_fin`— y los constraints de exclusión GiST de la tabla `turno`.<br><br>Este aporte fue fundamental: le brindó al agente el contexto real de la base de datos para planificar la extensión de C-15 con la columna `sillon_id`, sin necesidad de adivinar estructuras ni comprometer datos.” |
| **04:55 – 05:00**<br>*(5 seg)* | Volver brevemente a la portada de Skills. | “Ahora, mi compañera **Julieta Chavez** explicará nuestra Skill propia y la auditoría clínica de C-15.” |

---

### 🔹 BLOQUE 3: Julieta Chavez — Integrante 3
⏱️ **Tiempo asignado:** `05:00 a 07:30` (2 minutos y 30 segundos continuos)  
🎯 **Temas:** Skill propia `auditor-reglas-clinicas-sdd` + Estándar de Agent Skills + Auditoría y Dictamen `[APROBADO]` de C-15 (Leyes 26.529 y 25.326).

| Minuto | Qué mostrar en pantalla | Qué decir palabra por palabra (Diálogo de Julieta) |
| :--- | :--- | :--- |
| **05:00 – 05:45**<br>*(45 seg)* | **Cámara encendida 15 seg**, luego pantalla en `.agents/skills/auditor-reglas-clinicas-sdd/SKILL.md`.<br>Mostrar también `.atl/skill-registry.md` y `AGENTS.md`. | “Hola a todos, mi nombre es **Julieta Chavez**. En este tercer bloque voy a presentar nuestra **Skill propia: `auditor-reglas-clinicas-sdd`**.<br><br>A diferencia del MCP, una Skill es una unidad empaquetada de instrucciones especializadas y conocimiento de dominio que guía el razonamiento del agente.<br><br>Diseñamos esta skill investigando la meta-skill oficial `skill-creator` y siguiendo el estándar de Agent Skills: cuenta con frontmatter YAML con su nombre y descripción, triggers de activación automáticos para cambios de agenda y bioseguridad, y está debidamente registrada en nuestro `skill-registry.md` y `AGENTS.md`.” |
| **05:45 – 06:40**<br>*(55 seg)* | **Pantalla:** Navegar por el cuerpo de `SKILL.md`, mostrando las secciones de RN-AG-01, Ley 26.529 y Ley 25.326 (Regla R6). | “El propósito de nuestra skill es actuar como un **auditor de gobernanza clínica y legal** antes de que se escriba una sola línea de código en la fase Apply.<br><br>La skill analiza los artefactos de la propuesta confrontándolos contra tres pilares fundamentales:<br><br>1. **Reglas de negocio del consultorio:** En especial RN-AG-01 de anti-solapamiento y los protocolos de bioseguridad.<br>2. **Marco legal de salud (Ley 26.529):** Derechos del paciente, consentimientos informados y trazabilidad inalterable de auditoría médica.<br>3. **Protección de datos (Ley 25.326 y Regla R6):** Prohibición terminante de exponer DNI, teléfonos o historias clínicas en logs, URLs o respuestas de error.<br><br>La skill evalúa cada punto y emite un dictamen formal clasificado en Aprobado, Advertencia o Bloqueante.” |
| **06:40 – 07:25**<br>*(45 seg)* | **Pantalla:** Abrir `docs/skills-mcp/dictamen-c15.md` y `docs/skills-mcp/evidencias/02_skill_auditoria_c15.md`.<br>Resaltar el veredicto `[APROBADO]` y la matriz de control. | “Ejecutamos la auditoría sobre la propuesta de C-15 y el resultado fue el dictamen formal que vemos en pantalla, con resultado **APROBADO**.<br><br>La skill validó que el bloqueo de 20 a 30 minutos por bioaerosoles se resuelva mediante un constraint GiST sobre `sillon_id` y rangos `tstzrange`, garantizando que ningún turno pueda ocupar un sillón en desinfección; y certificó que los endpoints RBAC no expongan PII.<br><br>Así demostramos cómo la Skill protege la calidad arquitectónica y legal del producto.” |
| **07:25 – 07:30**<br>*(5 seg)* | Foco en terminal lista para tests. | “A continuación, mi compañera **Brisa Muñoz** ejecutará la suite de pruebas y la demo del sistema en vivo.” |

---

### 🔹 BLOQUE 4: Brisa Muñoz — Integrante 4
⏱️ **Tiempo asignado:** `07:30 a 10:00` (2 minutos y 30 segundos continuos)  
🎯 **Temas:** Ejecución de tests automatizados (Pytest + Vitest) + Demostración funcional en vivo (Swagger UI y Frontend) + Cierre formal de la defensa.

| Minuto | Qué mostrar en pantalla | Qué decir palabra por palabra (Diálogo de Brisa) |
| :--- | :--- | :--- |
| **07:30 – 08:20**<br>*(50 seg)* | **Cámara encendida 15 seg**, luego terminal en VS Code.<br>1. Ejecutar: `pytest -q --tb=short`<br>*(mostrar los 305 tests en verde)*.<br>2. Ejecutar: `npm test` en frontend<br>*(mostrar las 10 suites y 64 tests en verde)*. | “Hola a todos, soy **Brisa Muñoz**. En este último bloque vamos a verificar la estabilidad de la plataforma mediante pruebas automatizadas y demostrar el sistema funcionando en vivo.<br><br>Primero corremos en el backend la suite completa con `pytest`. Vemos cómo se ejecutan y aprueban los **305 tests en verde con 0 fallos**, validando las restricciones GiST anti-solapamiento, autenticación JWT, estados de turnos y reglas clínicas.<br><br>En el frontend corremos `npm test` con Vitest y comprobamos las **10 suites y 64 tests pasando en verde**. Todas las pruebas corren con datos 100% sintéticos cumpliendo la Regla R0.” |
| **08:20 – 09:25**<br>*(65 seg)* | **Pantalla en navegador:**<br>1. Swagger UI (`http://localhost:8000/docs`):<br>• `POST /api/v1/auth/login` con `admin.demo@consultorio.example`. Pegar token en `Authorize`.<br>• `GET /api/v1/auth/me` (200 OK con roles).<br>• `GET /api/v1/disponibilidad` (200 OK slots libres).<br>2. Pestaña de Frontend (`http://localhost:5173/agenda`): Grilla de turnos y check-in. | “Pasamos a la demostración interactiva en **Swagger UI**.<br><br>Ejecutamos el login en `POST /api/v1/auth/login` con el usuario demo de recepción. Obtenemos el JWT, lo autorizamos y ejecutamos `GET /api/v1/auth/me`: la API responde 200 OK con los roles del usuario, demostrando la seguridad implementada en C-02.<br><br>Luego consultamos `GET /api/v1/disponibilidad`: el motor calcula en milisegundos los slots libres cruzando la agenda del profesional y los sillones físicos (C-03).<br><br>Y en el frontend vemos la **Agenda de Recepción en tiempo real** en el puerto 5173, donde se visualizan los turnos organizados por columnas de sillón y profesional con estados y check-in en vivo.” |
| **09:25 – 10:00**<br>*(35 seg)* | **Pantalla:** Volver a `CHANGES.md` mostrando los 14 changes en `[x]` y C-15 en `[ ]`.<br>Cámara en primer plano para la despedida grupal. | “En conclusión: hemos demostrado el funcionamiento real del sistema con sus **14 changes fundacionales completados y testeados**.<br><br>Presentamos la integración de nuestro **servidor MCP PostgreSQL** en modo solo lectura para introspección segura, y la auditoría clínica de **C-15 con nuestra Skill propia**, dejando este nuevo change formalmente preparado como pendiente para el próximo ciclo.<br><br>Todo el código, guion y evidencias están disponibles en nuestro repositorio de GitHub respetando las reglas de seguridad. ¡Muchas gracias por su atención!” |

---

## 📊 Matriz de Cumplimiento de Cátedra y Tiempos

| Integrante | Rol en el Video | Inicio | Fin | Duración Exacta | Cumplimiento Consigna Cátedra |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **1. Ivana Gutierrez** | Presentación, Alcance C-01 a C-14, Problema y Justificación de C-15 | `00:00` | `02:30` | **2 min 30 seg** | Presentación personal, contexto de cambios, C-15 como pendiente. |
| **2. Rayssa Alejo** | Servidor MCP PostgreSQL, seguridad `turnos_readonly`, JSON-RPC | `02:30` | `05:00` | **2 min 30 seg** | Diferenciación MCP vs Skill, permisos mínimos (R2), evidencia real. |
| **3. Julieta Chavez** | Skill propia `auditor-reglas-clinicas-sdd`, auditoría y dictamen de C-15 | `05:00` | `07:30` | **2 min 30 seg** | Estándar de Agent Skills, leyes 26.529 y 25.326, dictamen APROBADO. |
| **4. Brisa Muñoz** | Tests automatizados (Pytest/Vitest), Demo Swagger + Frontend, Cierre | `07:30` | `10:00` | **2 min 30 seg** | 305 tests backend + 64 frontend, software funcionando en vivo, cierre. |
| **TOTAL** | **Equipo Completo — Comisión 1** | `00:00` | `10:00` | **10 min 00 seg** | **Límite máximo de 10 minutos cumplido con exactitud.** |
