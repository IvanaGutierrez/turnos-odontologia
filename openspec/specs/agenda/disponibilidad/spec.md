# agenda/disponibilidad Specification

## Purpose
Permite que cualquier persona consulte los huecos realmente reservables por motivo y profesional en una ventana dada, para elegir un slot sin llamar y sin ver datos de otros pacientes.

## Requirements

### Requirement: Slots reales derivan de horario menos bloqueos menos turnos

El sistema SHALL calcular los slots ofrecidos por `GET /api/v1/disponibilidad` como la intersección del horario vigente del profesional con la duración de la prestación, excluyendo todo intervalo superpuesto con un `Bloqueo` vigente o con un turno activo del mismo profesional o del mismo sillón requerido, y SHALL ordenar los slots cronológicamente.

#### Scenario: Slots excluyen turnos y bloqueos existentes

- **WHEN** se pide `GET /api/v1/disponibilidad?prestacion_id=<limpieza 45'>&profesional_id=<P>&desde=<2026-11-01T00:00-03:00>&hasta=<2026-11-02T00:00-03:00>` existiendo un turno activo de P de 10:00 a 10:45 y un bloqueo de P de 12:00 a 13:00
- **THEN** responde `200` con una lista de slots de 45' que no contiene ningún slot superpuesto con 10:00–10:45 ni con 12:00–13:00, e incluye al menos un slot libre anterior y uno posterior

#### Scenario: Slot fantasma jamás ofrecido

- **WHEN** se consulta disponibilidad sobre una ventana donde cada hueco de horario está cubierto por turnos activos o bloqueos
- **THEN** responde `200` con lista vacía (jamás un slot que al reservarlo colisione de forma predecible)

### Requirement: Agenda por motivo sin exponer ocupación ajena

El sistema SHALL derivar la duración del slot exclusivamente de `prestacion.duracion_min` (cadena `motivo→duración→profesional→slot`, RN-AG-03/04) y SHALL responder solo con inicios/fines libres, sin indicar qué turnos, pacientes o motivos ocupan los huecos vecinos ni incluir DNI, teléfonos o datos clínicos (R6, Ley 25.326 minimización).

#### Scenario: Disponibilidad no filtra quién ocupa un slot

- **WHEN** se pide disponibilidad sobre una ventana con turnos ocupados por otros pacientes y se inspecciona el cuerpo `200` y los logs
- **THEN** cada item contiene solo `{inicio, fin, profesional_id, prestacion_id}` (o shape equivalente sin PII) y ni el cuerpo ni los logs contienen DNI, teléfonos o datos clínicos de terceros

#### Scenario: Prestación inexistente o ventana inválida no gotea información

- **WHEN** se pide disponibilidad con `prestacion_id` inexistente o con `desde >= hasta` o ventana mayor al máximo configurable
- **THEN** responde `404` (prestación) o `422` (ventana) con mensaje genérico, sin revelar horarios, bloqueos ni turnos

### Requirement: Disponibilidad es pública con rate limit anti-scraping

El sistema SHALL exponer `GET /api/v1/disponibilidad` sin JWT y SHALL aplicar rate limit por IP (y por teléfono cuando se provea como filtro opcional) respondiendo `429` con indicación de reintento al excederse (RN-PU-03).

#### Scenario: Rate limit por IP en disponibilidad → 429

- **WHEN** se supera el tope configurable de consultas por minuto desde la misma IP
- **THEN** responde `429` con indicación de reintento y sin procesar el cálculo de slots
