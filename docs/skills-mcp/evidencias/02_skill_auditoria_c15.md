# Dictamen de Auditoría de Arquitectura Clínica y Gobernanza SDD

* **Change Evaluado:** `C-15-bloqueo-sillones-desinfeccion-mantenimiento`
* **Fecha de Evaluación:** 17 de Noviembre de 2026
* **Auditor:** Skill Propia `auditor-reglas-clinicas-sdd`
* **Normativas de Referencia:** `knowledge-base/05_reglas_de_negocio.md`, Ley 26.529, Ley 25.326, Reglas R0 a R8 de `AGENTS.md`
* **Dictamen Final:** **`[APROBADO]`** (Aprobado formalmente para avanzar a fase Apply)

---

## 1. Resumen Ejecutivo

La propuesta arquitectónica y especificación formal de comportamiento del Change C-15 ha sido evaluada exhaustivamente. El diseño aborda de forma rigurosa la problemática crítica de **bioseguridad odontológica** (ventanas obligatorias de 20 a 30 minutos para desinfección de bioaerosoles entre cirugías) y el mantenimiento de equipamiento rotatorio y electrohidráulico.

La arquitectura propuesta satisface el principio de defensa en profundidad exigido por la **Regla R3**: la prevención de colisiones temporales en un sillón no delega su seguridad en código de aplicación volátil, sino que establece un **constraint de exclusión física GiST** en PostgreSQL (`btree_gist` con rangos `tstzrange`). Asimismo, respeta estrictamente la privacidad del paciente al no almacenar ni emitir PII en motivos de bloqueo ni en registros de auditoría (**Ley 25.326 / Reglas R0 y R6**), manteniendo desacoplada la agenda de la historia clínica (**Ley 26.529**).

---

## 2. Matriz de Cumplimiento de Reglas y Normativas

| Regla / Norma | Descripción del Criterio | Estado | Observación Técnica |
| :--- | :--- | :--- | :--- |
| **RN-AG-01** | Anti-solapamiento físico estricto de recursos | **CUMPLE** | El servicio valida que no existan turnos activos coincidentes (`409 Conflict`) y el motor de base de datos prohíbe solapar dos bloqueos en el mismo sillón físico. |
| **RN-AG-04** | Bioseguridad y desinfección post-tratamiento | **CUMPLE** | Se formaliza el soporte de ventanas de 20–30 minutos para ventilación y desinfección química de bioaerosoles, excluyendo estos slots de la agenda pública. |
| **RN-AG-05** | Integridad ante cancelaciones / reubicaciones | **CUMPLE** | Si un sillón posee turnos confirmados, el sistema impide el bloqueo silencioso (`409`), obligando a recepción a reubicar o cancelar formalmente con aviso al paciente. |
| **RN-CL-04** | Matriz de Control de Acceso (RBAC) | **CUMPLE** | Endpoints de escritura restringidos a `admin` y `recepcion`. El rol `odontologo` dispone solo de permisos de lectura para conocer la operatividad del box. |
| **Ley 25.326 / R6** | Cero PII en logs, URLs, errores y respuestas | **CUMPLE** | Los motivos son estrictamente técnicos (*"Desinfección de box"*, *"Mantenimiento turbina"*). La auditoría purga datos sensibles y las URLs solo usan identificadores UUID. |
| **Ley 26.529** | Reserva de historia clínica confidencial | **CUMPLE** | Desacoplamiento total: la causa médica que originó la desinfección no se expone en la agenda ni en el bloqueo, resguardando el secreto médico. |
| **Regla R2** | Ciclo de persistencia controlado por Alembic | **CUMPLE** | El cambio de esquema planifica la migración formal `014_bloqueo_sillon_exclusion.py`, prohibiendo modificaciones manuales en la base de datos. |
| **Regla R3** | Restricción de exclusión física GiST | **CUMPLE** | Se define `EXCLUDE USING gist (sillon_id WITH =, tstzrange(desde, hasta, '[)') WITH &&) WHERE (sillon_id IS NOT NULL)` como última línea de defensa. |

---

## 3. Análisis de Escenarios de Prueba Verificables (Given / When / Then)

La especificación `specs/bloqueo_sillones.md` fue contrastada con los criterios de prueba:

* **Escenario 1 (Happy Path - Desinfección de 30 min):**
  - *Evaluación:* **Excelente**. Modela con precisión el flujo operativo habitual post-intervención quirúrgica con rol `recepcion`, comprobando la respuesta `201 Created` y la desaparición inmediata de slots libres en el servicio de disponibilidad.
* **Escenario 2 (Error de Negocio - Turnos confirmados preexistentes):**
  - *Evaluación:* **Robusta**. Evita el riesgo operativo de "pisar" citas de pacientes. El sistema responde `409 Conflict` con problema `sillon_con_turnos_activos` y no muta la base de datos.
* **Escenario 3 (Caso de Borde - Límite de cierre y solapamiento GiST):**
  - *Evaluación:* **Concluyente**. Comprueba que intervalos adyacentes (`[19:30, 20:00)`) sean permitidos, pero que solapamientos parciales (`[19:45, 20:15)`) sean interceptados por la restricción matemática del motor relacional.

---

## 4. Hallazgos y Observaciones

### Puntos Fuertes:
1. **Defensa en Profundidad**: Doble capa de validación (servicio lógico en FastAPI + restricción `EXCLUDE USING gist` en PostgreSQL).
2. **Alineación con el Dominio Odontológico**: Refleja la realidad sanitaria de los consultorios argentinos y el protocolo de bioaerosoles.
3. **Respeto a la Gobernanza SDD**: Los artefactos fueron elaborados sin escribir código prematuro en backend ni frontend, respetando la separación entre diseño e implementación.

### Advertencias (No Bloqueantes):
* *Sincronización en Grilla Frontend*: Al implementar la fase Apply, la grilla de `AgendaDia` (`C-04`) deberá pintar visualmente los bloques de desinfección con un color diferenciado (ej. ámbar/gris con ícono de advertencia) para que recepción reconozca rápidamente el motivo.

### Bloqueantes:
* **Ninguno**. La propuesta cumple con todos los estándares técnicos, clínicos y legales del proyecto.

---

## 5. Recomendaciones de Implementación para la Fase Apply

1. **Migración Alembic**: Asegurar que la migración `014` verifique la existencia de la extensión `btree_gist` (ya instalada en la migración `001`) antes de crear el constraint.
2. **Manejo de Excepciones**: En `app/services/bloqueos.py`, capturar específicamente `IntegrityError` de SQLAlchemy mapeando el nombre del constraint `ex_bloqueo_sillon_sin_solape` a una respuesta `409 Conflict` uniforme.
3. **Verificación TDD**: Ejecutar el ciclo RED-GREEN-REFACTOR implementando primero los tests de integración de los tres escenarios en `tests/integration/test_bloqueo_sillones.py`.
