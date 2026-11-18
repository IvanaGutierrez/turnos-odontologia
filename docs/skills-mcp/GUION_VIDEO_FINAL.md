# Guion Oficial de Grabación de Video — TPI Metodología de Sistemas I

> **Proyecto:** Sistema de Gestión Odontológica y Agenda Clínica (FastAPI + React + PostgreSQL + OpenSpec / SDD)  
> **Comisión:** Comisión 1 | **Materia:** Metodología de Sistemas I (UTN)  
> **Modalidad:** 4 Bloques Secuenciales continuos de 2 minutos y 30 segundos por integrante (Duración total: **10:00 exactos**).  
> **Distribución Equitativa de los 15 Changes:**  
> 1. **Integrante 1 — Ivana Gutierrez (00:00 a 02:30):** Presentación + C-01 y C-02 en detalle + Mención de C-03 y C-04.  
> 2. **Integrante 2 — Rayssa Alejo (02:30 a 05:00):** C-05 y C-06 en detalle + Mención de C-07 y C-08 + Servidor MCP PostgreSQL.  
> 3. **Integrante 3 — Julieta Chavez (05:00 a 07:30):** C-09 y C-10 en detalle + Mención de C-11 y C-12 + C-15 y Skill Propia.  
> 4. **Integrante 4 — Brisa Muñoz (07:30 a 10:00):** C-13 y C-14 en detalle + Tests automatizados + Demo en vivo + Cierre formal.  

---

## ⚠️ Reglas de Seguridad y Criterios Obligatorios de Cátedra

1. **Cámara encendida:** Cada integrante enciende su cámara (o recuadro visible) al menos al presentarse en su bloque.
2. **Regla R0 y R6 (Protección de Datos):** Solo datos 100% sintéticos/ficticios. Prohibido exponer DNI, teléfonos o historias clínicas reales.
3. **Regla R7 (Seguridad):** Nunca mostrar contraseñas reales, variables `.env` ni tokens de producción. Se muestra `.env.example` y `.mcp.example.json`.
4. **C-15 Pendiente:** Recalcar con claridad que **C-01 a C-14 están completos y archivados**, y que **C-15 queda formalmente preparado como pendiente `[ ]`**, sin contar como implementado.
5. **Ritmo de voz:** Hablar con dicción clara y fluida (120-130 palabras por minuto). El texto está calibrado para durar exactamente **2 minutos y 30 segundos** por persona.

---

## 🛠️ Checklist Técnico Previo (Tener listo en pestañas antes de grabar)

- [ ] **Backend levantado en puerto 8000:** `cd backend; .\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000`
- [ ] **Frontend levantado en puerto 5173:** `cd frontend; npm run dev`
- [ ] **Swagger UI abierto en navegador:** `http://localhost:8000/docs`
- [ ] **Frontend abierto en navegador:** `http://localhost:5173/agenda`
- [ ] **Pestañas de VS Code preparadas:**
  - `CHANGES.md` (con C-01 a C-14 en `[x]` y C-15 en `[ ]`).
  - `openspec/changes/archive/` (desplegada).
  - `.mcp.example.json` y `README.md` (sección MCP).
  - `docs/skills-mcp/evidencias/01_mcp_postgres_introspeccion.md`.
  - `.agents/skills/auditor-reglas-clinicas-sdd/SKILL.md` y `docs/skills-mcp/dictamen-c15.md`.

---

# 🎬 Guion Paso a Paso por Integrante (2m 30s por persona)

---

### 🔹 BLOQUE 1: Ivana Gutierrez — Integrante 1
⏱️ **Tiempo asignado:** `00:00 a 02:30` (2 minutos y 30 segundos continuos)  
🎯 **Contenido:** Presentación grupal + Contexto OpenSpec/SDD + **Detalle C-01 y C-02** + **Mención C-03 y C-04** + Pase a Rayssa.

| Minuto | Qué mostrar en pantalla | Qué decir palabra por palabra (Diálogo de Ivana) |
| :--- | :--- | :--- |
| **00:00 – 00:35**<br>*(35 seg)* | **Cámara encendida en primer plano.**<br>De fondo: Portada del repositorio GitHub (`IvanaGutierrez/turnos-odontologia`). | “Hola a todos, mi nombre es **Ivana Gutierrez** y junto a mis compañeras **Rayssa Alejo**, **Julieta Chavez** y **Brisa Muñoz**, conformamos el equipo de la Comisión 1 de Metodología de Sistemas I.<br><br>En este video presentamos nuestro Trabajo Práctico Integrador: el **Sistema de Gestión Odontológica y Agenda Clínica**, desarrollado sobre la base del Parcial 2 con FastAPI, React y PostgreSQL, aplicando una metodología ágil guiada por especificaciones mediante OpenSpec y SDD.” |
| **00:35 – 01:25**<br>*(50 seg)* | **Compartir pantalla:** Abrir `CHANGES.md` en VS Code.<br>Desplegar `openspec/changes/archive/2026-10-07-crear-turno-.../`<br>Mostrar `proposal.md` y la constraint GiST en la migración. | “Como vemos en `CHANGES.md`, nuestro roadmap cuenta con los 14 changes iniciales completamente terminados y archivados. Vamos a recorrerlos de forma equilibrada entre todas.<br><br>En primer lugar, el **Change C-01: Crear un turno evitando solapamientos por profesional y por sillón/box** fue nuestro núcleo fundacional. Resolvió el problema crítico de la doble reserva concurrente. En lugar de confiar únicamente en chequeos por software, implementamos una garantía matemática en PostgreSQL con restricciones físicas de exclusión GiST sobre tipos de rango `tstzrange`, verificado con tests automatizados de colisión.” |
| **01:25 – 02:05**<br>*(40 seg)* | **Pantalla:** Abrir `openspec/changes/archive/2026-10-07-auth-jwt-.../`<br>Mostrar router de autenticación y tabla `AuditoriaLog`. | “Sobre esa base implementamos el **Change C-02: Autenticación JWT, roles y auditoría**. Este change protegió el acceso al sistema mediante tokens JWT con rotación estricta de refresh tokens, una matriz de permisos RBAC para Administradores, Recepción y Odontólogos, y una bitácora inalterable de auditoría sin exponer datos personales (PII), cumpliendo con la Ley 25.326.” |
| **02:05 – 02:25**<br>*(20 seg)* | **Pantalla:** Señalar en `CHANGES.md` las filas de **C-03** y **C-04** en estado `[x] archivado`. | “Completando esta primera etapa de agenda, el **Change C-03** resolvió el cálculo de disponibilidad real y reserva pública 24/7 sin cuenta de paciente; mientras que el **Change C-04** implementó la agenda operativa diaria y semanal de recepción con control de check-in y sobreturnos.” |
| **02:25 – 02:30**<br>*(5 seg)* | Transición hacia el segundo bloque. | “A continuación, mi compañera **Rayssa Alejo** presentará los changes de autogestión y WhatsApp, junto a nuestro Servidor MCP.” |

---

### 🔹 BLOQUE 2: Rayssa Alejo — Integrante 2
⏱️ **Tiempo asignado:** `02:30 a 05:00` (2 minutos y 30 segundos continuos)  
🎯 **Contenido:** **Detalle C-05 y C-06** + **Mención C-07 y C-08** + **Servidor MCP PostgreSQL** (`turnos_readonly`, R0/R2/R7, introspección JSON-RPC) + Pase a Julieta.

| Minuto | Qué mostrar en pantalla | Qué decir palabra por palabra (Diálogo de Rayssa) |
| :--- | :--- | :--- |
| **02:30 – 03:10**<br>*(40 seg)* | **Cámara encendida 10 seg.**<br>Pantalla: `openspec/changes/archive/2026-10-10-autogestion-.../`<br>y `2026-10-11-recordatorios-whatsapp/`. | “Hola a todos, soy **Rayssa Alejo**. Continuando con nuestro roadmap, me tocó liderar dos changes esenciales para la experiencia del paciente:<br><br>El **Change C-05: Autogestión del paciente**, que permite confirmar, cancelar o reprogramar turnos desde el celular mediante un token público seguro, validando plazos de antelación mínima sin requerir login.<br><br>Y el **Change C-06: Recordatorios por WhatsApp**, donde integramos WhatsApp Cloud API mediante colas y workers en Redis, enviando confirmaciones inmediatas y recordatorios a 24 y 3 horas con reintentos idempotentes.” |
| **03:10 – 03:30**<br>*(20 seg)* | **Pantalla:** Señalar en `CHANGES.md` las filas de **C-07** y **C-08** en estado `[x] archivado`. | “En esta misma fase clínica se completaron el **Change C-07**, que incorporó la ficha clínica odontológica con odontograma FDI y presupuestos bajo la Ley 26.529; y el **Change C-08**, que gestiona el cobro de señas mediante Mercado Pago con webhooks idempotentes.” |
| **03:30 – 04:15**<br>*(45 seg)* | **Pantalla:** `README.md` (sección *Integración MCP y Agent Skills*) y archivo `.mcp.example.json`.<br>Mostrar terminal con permisos de `turnos_readonly`. | “Ahora pasamos a la integración de nuestro **Servidor MCP**. Es fundamental aclarar que **un servidor MCP NO es una skill**: es un protocolo abierto que expone herramientas desacopladas al modelo de IA.<br><br>Conectamos el servidor oficial `@modelcontextprotocol/server-postgres`. Para cumplir nuestras **Reglas R0, R2 y R7**, configuramos un rol exclusivo llamado `turnos_readonly` con permisos únicamente de `CONNECT`, `USAGE` y `SELECT`. De esta forma, el agente tiene prohibido modificar la base a mano; si intenta un `INSERT`, el motor aborta con `InsufficientPrivilegeError`. Y los secretos quedan protegidos en `.gitignore`.” |
| **04:15 – 04:55**<br>*(40 seg)* | **Pantalla:** Abrir `docs/skills-mcp/evidencias/01_mcp_postgres_introspeccion.md`.<br>Mostrar la respuesta JSON-RPC con columnas de `bloqueo` y constraints GiST de `turno`. | “En este archivo de evidencias vemos la ejecución real de la herramienta `query` del MCP. El servidor devolvió en formato JSON-RPC las columnas de la tabla `bloqueo` y los constraints de exclusión GiST de `turno`. Gracias a esta introspección segura, el agente pudo conocer la estructura física exacta de la base de datos sin alterar ningún dato y sin hacer suposiciones a ciegas.” |
| **04:55 – 05:00**<br>*(5 seg)* | Transición hacia el tercer bloque. | “Ahora, mi compañera **Julieta Chavez** explicará los changes de administración, la necesidad de C-15 y nuestra Skill propia.” |

---

### 🔹 BLOQUE 3: Julieta Chavez — Integrante 3
⏱️ **Tiempo asignado:** `05:00 a 07:30` (2 minutos y 30 segundos continuos)  
🎯 **Contenido:** **Detalle C-09 y C-10** + **Mención C-11 y C-12** + **Necesidad y formulación de C-15 (pendiente `[ ]`)** + **Skill propia `auditor-reglas-clinicas-sdd` y Dictamen [APROBADO]** + Pase a Brisa.

| Minuto | Qué mostrar en pantalla | Qué decir palabra por palabra (Diálogo de Julieta) |
| :--- | :--- | :--- |
| **05:00 – 05:40**<br>*(40 seg)* | **Cámara encendida 10 seg.**<br>Pantalla: `openspec/changes/archive/2026-10-12-caja-cierre-diario/`<br>y `2026-10-12-frontend-agenda-reserva/`. | “Hola a todos, mi nombre es **Julieta Chavez**. En este bloque cubrimos la administración operativa y la gobernanza clínica:<br><br>Primero, el **Change C-09: Caja y cierre diario**, que implementó el registro de ingresos y egresos conciliando los totales diarios contra los pagos acreditados por Mercado Pago.<br><br>Y el **Change C-10: Frontend operativo de agenda y reserva**, que construyó la SPA en React y TypeScript con la grilla de recepción multiprofesional y el flujo público de reserva en 3 pasos.” |
| **05:40 – 06:00**<br>*(20 seg)* | **Pantalla:** Señalar en `CHANGES.md` las filas de **C-11** y **C-12** en estado `[x] archivado`. | “Asimismo, en esta etapa se archivaron el **Change C-11** de roles, bitácora de auditoría y reportes exportables en CSV; y el **Change C-12** con el bot conversacional de WhatsApp para confirmar o cancelar turnos directamente por chat.” |
| **06:00 – 06:45**<br>*(45 seg)* | **Pantalla:** Abrir `openspec/changes/C-15-bloqueo-sillones-desinfeccion-mantenimiento/proposal.md`.<br>Mostrar sección de bioseguridad y `CHANGES.md` con C-15 en `[ ]`. | “Para esta entrega investigamos una necesidad crítica del consultorio: los tratamientos invasivos generan bioaerosoles que exigen **desinfección y ventilación de 20 a 30 minutos** entre turnos, además del mantenimiento periódico de los sillones.<br><br>Por ello formulamos el **Change C-15: Bloqueo de sillones por desinfección y mantenimiento**, extendiendo C-01 y C-04 con `sillon_id` y exclusión GiST.<br><br>Aclaramos enfáticamente la regla de cátedra: **C-15 queda formalmente especificado y preparado en estado pendiente [ ]**, sin implementar en código.” |
| **06:45 – 07:25**<br>*(40 seg)* | **Pantalla:** `.agents/skills/auditor-reglas-clinicas-sdd/SKILL.md`<br>y luego `docs/skills-mcp/dictamen-c15.md` con el veredicto `[APROBADO]`. | “Para auditar este diseño creamos nuestra **Skill propia: `auditor-reglas-clinicas-sdd`**, siguiendo el estándar de Agent Skills y la meta-skill `skill-creator`.<br><br>Esta skill audita las propuestas contra las reglas de anti-solapamiento (RN-AG-01), bioseguridad, la **Ley 26.529** de Derechos del Paciente y la **Ley 25.326** de Protección de Datos (Regla R6).<br><br>Auditamos C-15 y emitimos el dictamen formal en pantalla con veredicto **APROBADO**, demostrando cómo la Skill actúa de guardián de calidad clínica y legal.” |
| **07:25 – 07:30**<br>*(5 seg)* | Transición hacia el cuarto bloque. | “A continuación, mi compañera **Brisa Muñoz** presentará los últimos changes, la suite de tests y la demostración del sistema en vivo.” |

---

### 🔹 BLOQUE 4: Brisa Muñoz — Integrante 4
⏱️ **Tiempo asignado:** `07:30 a 10:00` (2 minutos y 30 segundos continuos)  
🎯 **Contenido:** **Detalle C-13 y C-14** + **Ejecución de Tests (Pytest 305 + Vitest 64)** + **Demo interactiva en Swagger UI y Frontend** + **Cierre formal del equipo (10:00 exactos)**.

| Minuto | Qué mostrar en pantalla | Qué decir palabra por palabra (Diálogo de Brisa) |
| :--- | :--- | :--- |
| **07:30 – 08:15**<br>*(45 seg)* | **Cámara encendida 10 seg.**<br>Pantalla: `openspec/changes/archive/2026-10-13-validacion-os-preventiva/`<br>y `2026-10-14-lista-espera-inteligente/`. | “Hola a todos, soy **Brisa Muñoz**. En este último bloque completamos el recorrido del roadmap y demostramos el sistema funcionando en vivo.<br><br>Presentamos los dos changes diferenciadores post-MVP:<br><br>El **Change C-13: Validación preventiva de obra social**, que valida la cobertura y topes del nomenclador antes de confirmar el turno, ofreciendo flujo particular si no cubre.<br><br>Y el **Change C-14: Lista de espera inteligente**, que ante una cancelación calcula un score ponderado de pacientes en espera y lanza una oferta automática por WhatsApp; el primero que abona la seña toma el turno disponible.” |
| **08:15 – 08:50**<br>*(35 seg)* | **Pantalla en Terminal VS Code:**<br>1. Ejecutar: `pytest -q --tb=short`<br>*(mostrar los 305 tests en verde)*.<br>2. Ejecutar: `npm test` en frontend<br>*(mostrar las 10 suites y 64 tests en verde)*. | “Para verificar la solidez del sistema ejecutamos la suite completa de pruebas automatizadas con datos sintéticos (Regla R0).<br><br>En el backend corremos `pytest` y vemos los **305 tests pasando en verde con 0 fallos**, verificando colisiones GiST, JWT, estados y lógica clínica.<br><br>En el frontend corremos `npm test` con Vitest y comprobamos las **10 suites y 64 tests en verde**, certificando cero regresiones en la plataforma.” |
| **08:50 – 09:35**<br>*(45 seg)* | **Pantalla en Navegador:**<br>1. Swagger UI (`http://localhost:8000/docs`):<br>• Login en `POST /api/v1/auth/login` con `admin.demo@consultorio.example`.<br>• `GET /api/v1/auth/me` (200 OK con roles).<br>• `GET /api/v1/disponibilidad` (200 OK slots libres).<br>2. Pestaña de Frontend (`http://localhost:5173/agenda`): Grilla operativa y check-in. | “En **Swagger UI** ejecutamos en vivo el login con el usuario demo de recepción, autorizamos el token JWT y consultamos `GET /api/v1/auth/me`, obteniendo código 200 OK con los roles del personal.<br><br>Luego consultamos `GET /api/v1/disponibilidad`, comprobando cómo el motor devuelve únicamente slots libres reales respetando la duración y los sillones.<br><br>Y en el frontend vemos la **Agenda de Recepción en tiempo real** en el puerto 5173, con turnos distribuidos por sillón y profesional con check-in en vivo.” |
| **09:35 – 10:00**<br>*(25 seg)* | **Pantalla:** `CHANGES.md` con los 14 changes en `[x]` y C-15 en `[ ]`.<br>**Cámara encendida** para la despedida formal. | “En conclusión: hemos demostrado el funcionamiento real del sistema con sus **14 changes completados y testeados**.<br><br>Integramos con éxito el **Servidor MCP PostgreSQL** en modo solo lectura y la **Skill propia de auditoría clínica**, dejando **C-15 formalmente preparado como pendiente** para el próximo ciclo.<br><br>Todo el repositorio se encuentra disponible y verificado sin secretos expuestos. ¡Muchas gracias por su atención!” |

---

## 📊 Matriz de Cobertura Completa de los 15 Changes

| Integrante | Rol y Bloque | Changes en Detalle | Changes Mencionados | Aporte Técnico Extra | Duración |
| :--- | :---: | :---: | :---: | :--- | :---: |
| **1. Ivana Gutierrez** | Bloque 1 (00:00 - 02:30) | **C-01**, **C-02** | C-03, C-04 | Presentación del equipo y contexto OpenSpec/SDD | **2m 30s** |
| **2. Rayssa Alejo** | Bloque 2 (02:30 - 05:00) | **C-05**, **C-06** | C-07, C-08 | Servidor MCP PostgreSQL (`turnos_readonly`, R0/R2/R7, JSON-RPC) | **2m 30s** |
| **3. Julieta Chavez** | Bloque 3 (05:00 - 07:30) | **C-09**, **C-10** | C-11, C-12 | Necesidad clínica, **C-15 (pendiente)** y Skill propia (`[APROBADO]`) | **2m 30s** |
| **4. Brisa Muñoz** | Bloque 4 (07:30 - 10:00) | **C-13**, **C-14** | — | Tests (305 + 64), Demo en vivo (Swagger/Frontend) y Cierre | **2m 30s** |
| **TOTAL** | **Equipo Completo** | **8 en detalle** | **6 mencionados** | **+ C-15 preparado, MCP, Skill y Tests en vivo** | **10:00 min** |
