# Especificación de Comportamiento: Bloqueo de Sillones Odontológicos (C-15)

* **Capacidad:** `bloqueo-sillones`
* **Change Asociado:** `C-15-bloqueo-sillones-desinfeccion-mantenimiento`
* **Estándar:** Gherkin / Given-When-Then

---

## Escenario 1: Funcionamiento esperado (Bloqueo exitoso por desinfección post-cirugía de 30 min)

```gherkin
Escenario: Registro exitoso de bloqueo de sillón para desinfección química de bioaerosoles
  Dado que el consultorio tiene habilitado el "Sillón Demo 1" (ID: 33333333-3333-4333-8333-333333333333)
  Y que el usuario autenticado tiene el rol "recepcion"
  Y que no existen turnos agendados en ese sillón entre las "10:30" y las "11:00" del día "2026-12-05"
  Cuando el usuario envía una solicitud POST a "/api/v1/bloqueos" con el siguiente cuerpo:
    """json
    {
      "sillon_id": "33333333-3333-4333-8333-333333333333",
      "desde": "2026-12-05T10:30:00-03:00",
      "hasta": "2026-12-05T11:00:00-03:00",
      "motivo": "Desinfección química y recambio de filtros por bioaerosoles",
      "tipo": "desinfeccion"
    }
    """
  Entonces el sistema responde con código HTTP 201 Created
  Y la respuesta contiene un identificador UUID generado para el bloqueo
  Y el evento de auditoría "bloqueo_sillon_creado" queda registrado sin datos personales de ningún paciente
  Y una consulta posterior de disponibilidad en ese sillón para las "10:45" no devuelve ningún slot libre.
```

---

## Escenario 2: Error de negocio (Intento de bloquear sillón con turnos confirmados sin reubicación)

```gherkin
Escenario: Rechazo de bloqueo de sillón ante la existencia de turnos confirmados concurrentes
  Dado que el "Sillón Demo 2" (ID: 44444444-4444-4444-8444-444444444444) tiene un turno confirmado
    con inicio a las "14:00" y fin a las "14:45" del día "2026-12-05"
  Y que el usuario autenticado tiene el rol "admin"
  Cuando el usuario envía una solicitud POST a "/api/v1/bloqueos" intentando programar un mantenimiento:
    """json
    {
      "sillon_id": "44444444-4444-4444-8444-444444444444",
      "desde": "2026-12-05T13:30:00-03:00",
      "hasta": "2026-12-05T15:00:00-03:00",
      "motivo": "Calibración técnica de compresor de aire y lámpara",
      "tipo": "mantenimiento"
    }
    """
  Entonces el sistema responde con código HTTP 409 Conflict
  Y el cuerpo de la respuesta contiene:
    | campo     | valor                                                                                   |
    | problema  | "sillon_con_turnos_activos"                                                             |
    | detalle   | "El sillón posee turnos activos en esa ventana; deben reubicarse antes de bloquear."     |
  Y el estado del turno confirmado original permanece inalterado en la base de datos
  Y ningún bloqueo nuevo es persistido.
```

---

## Escenario 3: Caso de borde (Bloqueo en el límite de cierre del consultorio y solapamiento parcial)

```gherkin
Escenario: Manejo de caso de borde en horario límite y rechazo de solapamiento con otro bloqueo
  Dado que el consultorio cierra su atención a las "20:00" horas
  Y que existe un bloqueo previo en el "Sillón Demo 1" desde las "19:00" hasta las "19:30"
  Cuando el usuario envía una solicitud POST a "/api/v1/bloqueos" para desinfección final:
    """json
    {
      "sillon_id": "33333333-3333-4333-8333-333333333333",
      "desde": "2026-12-05T19:30:00-03:00",
      "hasta": "2026-12-05T20:00:00-03:00",
      "motivo": "Desinfección terminal y cierre de box",
      "tipo": "desinfeccion"
    }
    """
  Entonces el sistema responde con código HTTP 201 Created porque el intervalo adyacente no se solapa
  Pero si inmediatamente se intenta enviar otro bloqueo para el mismo sillón de "19:45" a "20:15":
  Entonces el motor de base de datos activa el constraint de exclusión GiST "ex_bloqueo_sillon_sin_solape"
  Y el sistema responde con código HTTP 409 Conflict informando colisión física de bloqueo.
```
