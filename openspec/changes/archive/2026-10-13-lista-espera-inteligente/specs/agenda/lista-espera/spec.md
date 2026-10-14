# Spec Delta — `agenda/lista-espera`

## Purpose

Esta capacidad cubre la lista de espera inteligente del consultorio: los pacientes anotan su ventana de disponibilidad, cada cancelación dispara un ranking determinístico del hueco liberado, el sistema oferta el slot al top-N por WhatsApp con seña expirable y asigna el turno a quien paga primero, re-ofertando ante expiración y expirando silenciosamente ante ventana vencida — sin filtrar jamás datos de otros en espera.

## ADDED Requirements

### Requirement: Alta, consulta y baja de la espera con ventana

El sistema SHALL exponer `POST /api/v1/lista-espera` (JWT, solo staff `admin|recepcion`) que crea una entrada `{paciente_id, prestacion_id, profesional_id?, ventana_desde, ventana_hasta}` en estado `activa`; SHALL exponer `GET /api/v1/lista-espera?estado` (staff `admin|recepcion|odontologo`) y `DELETE /api/v1/lista-espera/:id` (baja manual → `expirada`, sin oferta); y SHALL responder `422` ante ventana inválida (`desde >= hasta` o ambos en el pasado) y `404` idéntico sin filtrar datos ante id inexistente (R6).

#### Scenario: Alta en lista con ventana válida

- **WHEN** recepción anota un paciente con prestación y ventana futura válida
- **THEN** responde `201` con la entrada en `activa` y registra `lista_espera_creada` sin PII en el `diff`

#### Scenario: Alta con ventana inválida o pasada

- **WHEN** la ventana tiene `desde >= hasta` o ya terminó
- **THEN** responde `422` sin crear nada

#### Scenario: Baja manual expira sin oferta

- **WHEN** staff elimina una entrada `activa|ofertada`
- **THEN** la entrada pasa a `expirada`, sus ofertas `pendiente` a `expirada`, y no se envía ningún mensaje

### Requirement: Cancelación dispara scoring determinístico y blast top-N

El sistema SHALL, ante toda cancelación (`cancelado` por cualquier canal C-04/C-05/C-12) de un turno futuro, publicar el hueco (profesional, sillón, inicio, fin) y ranquear las entradas elegibles (`activa` + ventana que cubre el hueco + misma `prestacion_id` y `profesional_id` si está fijado) con `score = 100*(P_VENT*w_vent + P_HIST*w_hist + P_VALOR*w_valor)` (pesos por env, desempate por `created_at` ASC), persistiendo `score` + componentes; y SHALL crear una `OfertaEspera pendiente` con `expira_at = ahora + LISTA_ESPERA_OFERTA_TTL_MIN` por cada uno del top-N (`LISTA_ESPERA_TOP_N`), pasando esas entradas a `ofertada` y enviando el blast WhatsApp con link de seña (nadie recibe dos ofertas del mismo hueco).

#### Scenario: Cancelación dispara scoring y blast al top-N

- **WHEN** se cancela un turno futuro existiendo espera elegible que cubre el hueco
- **THEN** se ranquea por score, el top-N queda `ofertada` con oferta `pendiente` expirable + link de seña, y se registra `oferta_enviada` por oferta sin PII

#### Scenario: Orden de scoring exacto con desempate por antigüedad

- **WHEN** varias entradas cubren el mismo hueco con distinto ajuste de ventana, historial y valor
- **THEN** el orden respeta la fórmula con los pesos vigentes y, a igualdad de score, gana la más antigua

#### Scenario: Sin elegibles el hueco queda libre sin ruido

- **WHEN** se cancela un turno sin entradas elegibles (o todas con ventana vencida)
- **THEN** no se crea ninguna oferta ni se envía ningún mensaje; el hueco sigue reservable por los canales normales

### Requirement: Oferta expirable aceptada asigna turno, seña y aviso

El sistema SHALL, ante el primer webhook MP acreditado con `metadata.oferta_espera_id` de oferta `pendiente` vigente, reclamarla atómicamente (`FOR UPDATE`): oferta → `aceptada`, entrada → `asignada`, hermanas del hueco → `desplazada` con sus entradas → `activa`; SHALL crear el `Turno canal=lista_espera` con el snapshot del hueco bajo el GiST vigente; SHALL emitir `pago_acreditado` (C-09 concilia igual), comprobante por WhatsApp y `aviso_a_recepcion` con el turno visible en la grilla existente; y SHALL responder a acreditaciones tardías de ofertas ya resueltas como duplicado-perdedor (ver siguiente requirement).

#### Scenario: Oferta expirable aceptada asigna seña y turno

- **WHEN** un ofertado paga la seña dentro del TTL con el slot aún libre
- **THEN** su entrada pasa a `asignada`, existe UN turno `canal=lista_espera` en el slot, la caja ve el `pago_acreditado`, el resto vuelve a `activa` y recepción queda notificada

### Requirement: Doble pago concurrente con un solo ganador reembolsado

El sistema SHALL serializar los webhooks concurrentes sobre la misma oferta/hueco de modo que EXACTAMENTE UNO resulte `aceptada/asignada` con turno creado; el perdedor SHALL quedar con pago en `reembolsado` (refund MP ejecutado), evento `pago_reembolsado` auditado, sin turno creado y con su entrada de vuelta en `activa`; y si el slot fue ocupado por otro canal entre la oferta y el pago, el GiST SHALL rechazar el `INSERT` y el pagador irá a `reembolsado` con su entrada a `activa` (nunca cargo sin turno, nunca turno duplicado — R3).

#### Scenario: Doble pago concurrente deja un solo asignado y otro reembolsado

- **WHEN** dos pagos acreditados concurren por el mismo hueco ofertado
- **THEN** existe UN solo turno en el slot, UNA entrada `asignada`, el otro pago está `reembolsado` con `pago_reembolsado` auditado y su entrada en `activa`

### Requirement: Expiración re-oferta al siguiente y ventana vencida expira

El sistema SHALL barrer periódicamente las ofertas `pendiente` con `expira_at` pasado → `expirada` (+ evento `oferta_expirada`), devolver su entrada a `activa` y re-ofertar el hueco al siguiente elegible aún no ofertado para ese hueco; y SHALL, ante ventana vencida de una entrada (`ahora > ventana_hasta`), pasarla a `expirada` sin crear ofertas ni enviar mensajes.

#### Scenario: Expiración re-oferta al siguiente y el resto vuelve a activa

- **WHEN** expiran las ofertas del top-N sin pago
- **THEN** esas entradas vuelven a `activa`, el siguiente elegible recibe oferta `pendiente` nueva, y el evento `oferta_expirada` queda auditado

#### Scenario: Ventana vencida expira sin oferta

- **WHEN** una entrada supera su `ventana_hasta` sin haber sido asignada
- **THEN** pasa a `expirada` sin blast, sin mensajes y sin mutar el hueco

### Requirement: Recepción notificada y oferta sin filtraciones

El sistema SHALL, ante cada asignación, dejar el turno `canal=lista_espera` visible en la grilla de recepción existente y emitir `aviso_a_recepcion` + `lista_espera_asignada`; y SHALL componer cada mensaje de oferta SOLO con el slot propio del destinatario (nombre de pila, fecha, hora, sede, link de seña) — jamás posiciones, nombres, cantidades ni ningún dato de otros en espera, ni en mensajes, responses, `diff`s o logs (R6, Ley 25.326).

#### Scenario: Recepción notificada de la asignación

- **WHEN** una oferta se asigna por pago
- **THEN** el turno aparece en la agenda del día con `canal=lista_espera` y existe `aviso_a_recepcion` + `lista_espera_asignada` auditados

#### Scenario: Oferta jamás filtra otros en espera

- **WHEN** se envía cualquier oferta o se consulta cualquier endpoint de espera
- **THEN** el contenido solo menciona el slot propio del destinatario y ningún mensaje/response/`diff`/log contiene datos de otros en espera
