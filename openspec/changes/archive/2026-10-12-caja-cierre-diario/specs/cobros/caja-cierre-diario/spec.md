# Spec Delta — `cobros/caja-cierre-diario`

## Purpose

Permite que recepción/admin registre movimientos de caja por método y cierre el día por sede conciliando lo declarado contra los pagos MP acreditados — con diferencias marcadas, día cerrado bloqueado y reapertura solo admin auditada.

## ADDED Requirements

### Requirement: Registro de movimientos por método con operador y concepto

El sistema SHALL exponer `POST /api/v1/caja/movimientos` (JWT, roles `admin|recepcion`) que crea UN movimiento `{fecha, sede, tipo: ingreso|egreso, concepto (1–280 caracteres), monto > 0 ARS, metodo: efectivo|transferencia|tarjeta|mercadopago, pago_id?}` con `usuario_id` del operador autenticado; SHALL responder `201` con el movimiento creado y registrar el evento `movimiento_registrado` (sin concepto crudo en el diff — R6); y SHALL responder `422` ante método fuera del catálogo, monto ≤ 0 o concepto vacío.

#### Scenario: Movimiento válido por método → 201 + auditado

- **WHEN** recepción autenticada registra un ingreso (o egreso) en `efectivo` (y luego uno por cada uno de `transferencia`, `tarjeta`, `mercadopago`) con concepto y monto positivo
- **THEN** responde `201` con `{tipo, metodo, monto, usuario_id}` del operador, y existe el evento `movimiento_registrado` sin PII ni concepto crudo

#### Scenario: Método inválido → 422

- **WHEN** se registra un movimiento con `metodo='cheque'` (u otro fuera del catálogo)
- **THEN** responde `422` de validación sin crear ningún movimiento ni evento

### Requirement: Consulta de movimientos y cierre del día

El sistema SHALL exponer `GET /api/v1/caja/movimientos?fecha&sede` (lista los movimientos del día/sede para el arqueo, Flujo 6 paso 1) y `GET /api/v1/caja/cierre?fecha&sede` (devuelve el cierre con snapshot, `diferencia` y `estado`, o `404` si aún no existe); ambos con JWT y roles `admin|recepcion`.

#### Scenario: Recepción lista los movimientos del día

- **WHEN** recepción consulta `GET /api/v1/caja/movimientos?fecha=<hoy>&sede=Consultorio` tras registrar 3 movimientos
- **THEN** responde `200` con exactamente esos 3 movimientos y sus montos

### Requirement: Cierre diario único con conciliación y diferencias

El sistema SHALL exponer `POST /api/v1/caja/cierre {fecha, sede}` (JWT, roles `admin|recepcion`) que, en UNA transacción: snapshot de totales por método desde los movimientos del día/sede, lee los pagos `acreditado` del día (fuente C-08, solo lectura), calcula `diferencia = total_mp_movimientos − acreditado_mp`, crea el cierre en estado `cerrado` con `cerrado_por`/`cerrado_at` y registra `cierre_creado`; SHALL marcar `estado_conciliacion='cuadrado'` si `diferencia == 0` y `'con_diferencia'` si no; y SHALL responder `409` ante un segundo cierre del mismo día/sede (UNIQUE `fecha,sede` — la DB manda, incluso en concurrente).

#### Scenario: Cierre compara acreditados vs movimientos y marca diferencias

- **WHEN** se cierra un día con ingresos MP declarados por $10.000 y pagos `acreditado` por $8.000
- **THEN** responde `201` con `diferencia = 2000` y `estado_conciliacion='con_diferencia'`, y el snapshot conserva ambos totales

#### Scenario: Doble cierre mismo día/sede → 409

- **WHEN** se cierra el mismo día/sede dos veces (incluso en concurrente)
- **THEN** el primero es `201`, el segundo `409`, existe UN solo renglón de cierre y UN solo evento `cierre_creado`

#### Scenario: Cierre sin diferencias → cuadrado

- **WHEN** se cierra un día donde el total MP declarado iguala exactamente los pagos `acreditado`
- **THEN** responde `201` con `diferencia = 0` y `estado_conciliacion='cuadrado'`

### Requirement: Día cerrado bloqueado para movimientos

El sistema SHALL rechazar con `422 dia_cerrado` todo `POST /api/v1/caja/movimientos` cuya `fecha` pertenezca a un cierre en estado `cerrado` (verificado en la transacción con bloqueo de fila), sin crear movimiento ni evento; los movimientos de otros días/sede abiertos siguen permitidos.

#### Scenario: Movimiento en día cerrado → 422

- **WHEN** se registra un movimiento con fecha de un día ya cerrado (y otro con fecha de un día abierto)
- **THEN** el primero es `422 dia_cerrado` sin efectos, el segundo es `201`

### Requirement: Reapertura solo admin y auditada

El sistema SHALL exponer `POST /api/v1/caja/reapertura {fecha, sede, motivo ≥10 caracteres}` que revierte el cierre a `abierto` (`reaperturas+1`) y registra `cierre_reabierto` con `{cierre_id, fecha, sede, motivo}`; SHALL exigir rol `admin` (recurso `reapertura_caja`) y responder `403` genérico + evento `reapertura_denegada` (solo `{fecha, sede, usuario_id}`) ante recepción/odontólogo; y SHALL responder `404` si no existe cierre y `422` si ya está abierto.

#### Scenario: Reapertura admin → 200 + auditada

- **WHEN** admin reabre un día cerrado con motivo válido y luego se registra un movimiento de ese día
- **THEN** la reapertura es `200` con `estado='abierto'`, existe `cierre_reabierto`, y el movimiento posterior es `201`

#### Scenario: Reapertura no-admin → 403 + log

- **WHEN** recepción (u odontólogo) intenta reabrir un día cerrado
- **THEN** responde `403` genérico, el cierre sigue `cerrado`, y existe el evento `reapertura_denegada`

### Requirement: RBAC, privacidad y configuración de caja

El sistema SHALL restringir todo `/api/v1/caja*` a JWT válido con recursos nuevos `caja → {admin, recepcion}` y `reapertura_caja → {admin}` (odontólogo → `403` en todo caja; matriz existente intacta, deny-by-default); SHALL loguear/auditar solo `{movimiento_id|cierre_id, fecha, sede, tipo, metodo, monto, diferencia, estado}` + `usuario_id`, sanitizando y truncando el `concepto` libre (jamás concepto crudo, DNI, teléfonos, HCE ni tokens — R6, Ley 25.326); y SHALL leer `CAJA_TZ` (default `America/Argentina_Buenos_Aires`) solo de env (R7).

#### Scenario: Odontólogo accede a caja → 403

- **WHEN** un JWT con rol `odontologo` llama a cualquier endpoint de caja
- **THEN** responde `403` genérico sin mutar nada

#### Scenario: Logs y errores sin PII ni concepto crudo

- **WHEN** se registra un movimiento con concepto libre, se cierra o se reabre
- **THEN** ningún log, auditoría ni response contiene el concepto crudo, DNI, teléfonos, HCE ni tokens; solo IDs, montos, métodos y estados
