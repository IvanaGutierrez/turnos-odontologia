---
name: auditor-reglas-clinicas-sdd
description: Audita artefactos de software y propuestas OpenSpec (proposal, design, specs, tasks) confrontándolos contra las reglas de negocio odontológicas (RN-AG, RN-CL, RN-AU), la Ley 26.529 y la Ley 25.326 (Regla R6 sin PII) para emitir un dictamen formal de arquitectura clínica y legal.
---

# Auditor de Reglas Clínicas, Bioseguridad y Gobernanza SDD (`auditor-reglas-clinicas-sdd`)

## Propósito
Esta skill actúa como un **auditor formal de arquitectura y gobernanza clínica** dentro del flujo de desarrollo basado en especificaciones (SDD / OpenSpec). Su misión es evaluar de forma exhaustiva las propuestas de cambio (`proposal.md`), diseños técnicos (`design.md`), escenarios de prueba (`specs/*.md`) y desgloses de tareas (`tasks.md`) antes de que se escriba una sola línea de código en backend o frontend.

Garantiza que toda funcionalidad planificada respete:
1. Las **reglas de negocio de la agenda odontológica** (anti-solapamiento estricto, bioseguridad, tiempos de desinfección y disponibilidad de recursos físicos).
2. La **matriz de permisos y control de acceso (RBAC)** del consultorio.
3. El marco normativo argentino de salud y privacidad: **Ley 26.529** (Derechos del Paciente y reserva de Historia Clínica) y **Ley 25.326** (Protección de los Datos Personales / Reglas R0 y R6 del proyecto).
4. La robustez técnica de la persistencia: exigencia de restricciones de exclusión físicas en PostgreSQL (`btree_gist`) en lugar de validaciones volátiles en software.

---

## Triggers (Cuándo se Activa)
Esta skill debe cargarse y ejecutarse en las siguientes circunstancias:
- Al preparar o revisar los artefactos de un nuevo Change en OpenSpec (durante `/opsx:propose` o antes de `/opsx:apply`).
- Durante revisiones arquitectónicas de cambios que impacten en entidades críticas (`Turno`, `Sillon`, `Profesional`, `Bloqueo`, `Ficha`, `Presupuesto`, `Pago`).
- Cuando se formulen políticas de agenda, bioseguridad, tiempos de desinfección o bloqueos de sillones (ej. Change C-15).
- Ante cualquier solicitud explícita de "auditar change", "revisar cumplimiento clínico" o "auditar propuesta con reglas de negocio".

---

## Entradas Requeridas
Para realizar la auditoría, el agente debe disponer de:
1. **Artefactos del Change a evaluar:**
   - `openspec/changes/<change-name>/proposal.md`
   - `openspec/changes/<change-name>/design.md`
   - `openspec/changes/<change-name>/specs/*.md`
   - `openspec/changes/<change-name>/tasks.md`
2. **Base de Conocimiento del Proyecto (fuente de verdad):**
   - `knowledge-base/05_reglas_de_negocio.md` (especialmente secciones RN-AG, RN-CL, RN-AU, RN-PA).
   - `knowledge-base/03_actores_y_roles.md` (matriz RBAC).
   - `knowledge-base/04_modelo_de_datos.md` (esquema relacional y restricciones).
   - `AGENTS.md` / `CLAUDE.md` (reglas duras R0 a R8).

---

## Procedimiento de Auditoría Paso a Paso

El auditor ejecuta estrictamente las siguientes fases:

### Paso 1: Mapeo de Entidades e Impacto Arquitectónico
- Identificar qué modelos de base de datos se crean o modifican (ej. `Bloqueo`, `Sillon`, `Turno`).
- Identificar los endpoints REST propuestos, sus métodos HTTP y los esquemas de entrada y salida (Pydantic).
- Determinar el nivel de gobernanza asignado (CRÍTICO, ALTO, MEDIO, BAJO).

### Paso 2: Confrontación con Reglas de Negocio Odontológicas
- **RN-AG-01 (Anti-solapamiento Estricto):** Verificar que la propuesta impida matemáticamente el doble agendamiento o conflicto físico de un recurso (profesional y sillón). En bloqueos de sillón (C-15), validar que un sillón bloqueado no admita turnos activos en esa ventana temporal.
- **RN-AG-04 (Bioseguridad y Desinfección):** Verificar que se contemplen tiempos muertos de 20 a 30 minutos entre tratamientos invasivos/quirúrgicos para desinfección de bioaerosoles, esterilización y recambio de instrumental.
- **RN-AG-05 (Cancelación y Reprogramación):** Asegurar que si un bloqueo inhabilita turnos confirmados existentes, se defina el mecanismo de cancelación/reubicación con aviso preventivo y gestión de señas.
- **RN-CL-04 (RBAC Clínico y Operativo):** Verificar qué roles tienen autorización para crear o modificar bloqueos (exclusivo de `admin` y `recepcion`; `odontologo` no puede bloquear sillones de terceros).

### Paso 3: Control Legal y Protección de Datos Personales
- **Ley 25.326 (Protección de Datos Personales / Reglas R0 y R6):**
  - Comprobar que en ninguna URL, log, parámetro de query ni respuesta pública se expongan DNI, teléfonos, nombres ni diagnósticos.
  - Verificar que los motivos de bloqueo sean genéricos u operativos (*"Mantenimiento técnico"*, *"Desinfección de box"*), sin revelar diagnósticos ni datos médicos de pacientes.
- **Ley 26.529 (Derechos del Paciente e Historia Clínica):**
  - Garantizar que los bloqueos y la agenda operativa estén completamente desacoplados del contenido clínico confidencial (HCE/anamnesis).

### Paso 4: Evaluación de Resiliencia Técnica en Base de Datos
- **Defensa en Profundidad (Regla R3):** Verificar que el diseño no dependa únicamente de un `if` o `select` en FastAPI, sino que exija un constraint de exclusión en PostgreSQL (`EXCLUDE USING gist`) con `tstzrange` sobre el identificador del sillón y el rango temporal.
- **Aislamiento de Entorno (Regla R2):** Comprobar que todo cambio de esquema relacional esté planificado mediante una migración formal de Alembic versionada.

### Paso 5: Emisión del Dictamen Formal
Consolidar los hallazgos en un informe de auditoría Markdown estructurado según la plantilla definida abajo.

---

## Plantilla del Dictamen de Auditoría

```markdown
# Dictamen de Auditoría de Arquitectura Clínica y Gobernanza SDD

* **Change Evaluado:** [Nombre del Change]
* **Fecha de Evaluación:** [YYYY-MM-DD]
* **Auditor:** Skill `auditor-reglas-clinicas-sdd`
* **Dictamen Final:** [APROBADO | ADVERTENCIA | BLOQUEANTE]

## 1. Resumen Ejecutivo
[Párrafo sintético con la conclusión de la auditoría y los puntos más destacados]

## 2. Matriz de Cumplimiento de Reglas y Normativas

| Regla / Norma | Descripción | Estado | Observación Técnica |
| :--- | :--- | :--- | :--- |
| **RN-AG-01** | Anti-solapamiento físico estricto | [CUMPLE / OBSERVA / NO CUMPLE] | [Detalle] |
| **RN-AG-04** | Bioseguridad y desinfección post-tratamiento | [CUMPLE / OBSERVA / NO CUMPLE] | [Detalle] |
| **RN-CL-04** | Control de acceso por rol (RBAC) | [CUMPLE / OBSERVA / NO CUMPLE] | [Detalle] |
| **Ley 25.326 / R6** | Cero PII en logs, URLs y respuestas | [CUMPLE / OBSERVA / NO CUMPLE] | [Detalle] |
| **Ley 26.529** | Reserva de historia clínica confidencial | [CUMPLE / OBSERVA / NO CUMPLE] | [Detalle] |
| **Regla R3** | Exclusión física en motor PostgreSQL (GiST) | [CUMPLE / OBSERVA / NO CUMPLE] | [Detalle] |

## 3. Análisis de Escenarios de Prueba (Given / When / Then)
* **Escenario 1 (Happy Path):** [Evaluación]
* **Escenario 2 (Error de Negocio):** [Evaluación]
* **Escenario 3 (Caso de Borde):** [Evaluación]

## 4. Hallazgos y Observaciones
* **Puntos Fuertes:** [Aspectos bien resueltos]
* **Advertencias (No bloqueantes):** [Detalles a considerar]
* **Bloqueantes (Requieren remediación):** [Si existen, detallar qué impide avanzar a Apply]

## 5. Recomendaciones de Remediación
[Instrucciones exactas para el equipo de desarrollo antes de pasar a la fase de implementación]
```
