# Propuesta de Cambio C-15: Bloqueo de Sillones Odontológicos por Desinfección y Mantenimiento

* **Identificador:** C-15
* **Nombre de la Rama / Change:** `C-15-bloqueo-sillones-desinfeccion-mantenimiento`
* **Nivel de Gobernanza:** MEDIO
* **Dependencias:** C-01 (`crear-turno-anti-solapamiento`), C-04 (`agenda-operativa-recepcion`)
* **Estado:** `[ ]` Propuesta formalizada (Ciclo SDD / Preparado para implementación)

---

## 1. Contexto y Necesidad Real en el Consultorio

En la práctica odontológica moderna, el **sillón dental (box)** es una unidad operativa compleja que integra circuitos de agua, aire comprimido, instrumental rotatorio de alta velocidad (turbinas que superan las 300.000 RPM) y aspiración de fluidos. La disponibilidad física del sillón se ve condicionada por dos factores ineludibles:

1. **Protocolos de Bioseguridad y Desinfección Post-Tratamiento**:
   Los procedimientos invasivos (extracciones quirúrgicas, cirugías periodontales, raspajes o aperturas cavitarias) generan nubes densas de **bioaerosoles** cargados de sangre, saliva y patógenos en suspensión. Las normativas sanitarias y de control de infecciones exigen ventanas obligatorias de **20 a 30 minutos** entre pacientes para:
   - Ventilación del box.
   - Desinfección química de superficies, mangueras y escupidera.
   - Purga de conductos de aspiración.
   - Recambio de instrumental y colocación de barreras estériles descartables.
2. **Mantenimiento Técnico Preventivo y Correctivo**:
   Roturas en turbinas, averías en mangueras de succión, descalibración de lámparas de fotocurado o caídas en la presión de los compresores inhabilitan el uso del box físico, incluso si el odontólogo asignado se encuentra libre.

---

## 2. Problema Detectado en la Arquitectura Actual

Actualmente, el sistema cuenta con los 14 Changes fundacionales (`C-01` a `C-14`) operando en producción. Sin embargo, existe una limitación operativa:

* La entidad `Bloqueo` (`app/models/disponibilidad.py`) fue concebida en `C-03` para registrar licencias, congresos o feriados del odontólogo (`profesional_id`).
* Si bien la tabla posee una columna `sillon_id` en la base de datos (según introspección MCP), el servicio de creación de turnos (`crear_turno.py`) y el cálculo de disponibilidad (`disponibilidad.py`) no cruzan los bloqueos contra el sillón físico, ni existe una API para que Recepción o Administración declaren un sillón en estado de desinfección o mantenimiento.
* **Riesgo:** Un paciente puede reservar un turno en un sillón que está físicamente inoperativo o contaminado con bioaerosoles, violando normas de bioseguridad o generando demoras críticas en la sala de espera.

---

## 3. Solución Propuesta

El **Change C-15** resuelve esta problemática de forma integral:

1. **Extensión del Modelo de Dominio y Endpoints:**
   - Formalizar el uso de `sillon_id` en `Bloqueo`, admitiendo bloqueos de tipo `profesional` (licencias) o de tipo `sillon` (desinfección, mantenimiento).
   - Crear el endpoint `POST /api/v1/bloqueos` protegido por RBAC (restringido a roles `admin` y `recepcion`).
2. **Garantía Física Anti-solapamiento (Extensión de C-01):**
   - Incorporar un constraint de exclusión en PostgreSQL (`EXCLUDE USING gist`) con rangos `tstzrange` para que sea matemáticamente imposible superponer dos bloqueos en el mismo sillón.
   - En el servicio de reserva de turnos, verificar que el sillón no posea bloqueos activos antes de persistir la cita.
3. **Visibilidad en la Agenda Operativa (Extensión de C-04):**
   - Exponer en `GET /api/v1/agenda` las franjas bloqueadas por sillón con su motivo operativo (*"Desinfección de box"*, *"Mantenimiento técnico"*).
   - Excluir automáticamente estos intervalos de los slots ofrecidos en la reserva pública online (`C-03` / `C-10`).
4. **Protección de Datos y Privacidad (Leyes 25.326 y 26.529 / Reglas R0 y R6):**
   - Los motivos de bloqueo son estrictamente técnicos u operativos. Jamás contienen datos de pacientes (DNI, teléfonos, nombres ni diagnósticos médicos).

---

## 4. Criterios de Aceptación y Alcance del Change

* **Backend:**
  - Endpoint `POST /api/v1/bloqueos` (crear bloqueo por profesional o sillón).
  - Endpoint `GET /api/v1/bloqueos` (listar bloqueos activos con filtros de fecha y sede).
  - Rechazo con `409 Conflict` si se intenta bloquear un sillón que ya cuenta con turnos confirmados en ese horario (requiere reubicación previa).
  - Migración Alembic `014_bloqueo_sillon_exclusion.py` con índice GiST sobre `(sillon_id, tstzrange(desde, hasta))`.
* **Testing:**
  - Cobertura 100% en tests unitarios y de integración para solapamiento, RBAC y cálculo de disponibilidad con sillones bloqueados.
* **Fuera de Alcance:**
  - Compra de repuestos de mantenimiento o integración con proveedores de equipamiento.
