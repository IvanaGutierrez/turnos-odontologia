# admin/reportes-operativos Specification

## Purpose
Da al consultorio reportes operativos agregados (ocupación, ausentismo, ingresos) con scoping por rol y exportación CSV sanitizada, sin exponer jamás PII ni historia clínica.

## Requirements

### Requirement: Ocupación por profesional y sillón en rango

El sistema SHALL exponer `GET /api/v1/reportes/ocupacion?desde&hasta&profesional_id&sillon_id&sede` (JWT, recurso `reportes`) que devuelve por profesional y por sillón `{turnos_totales, turnos_activos, horas_ocupadas, ocupacion_pct}` calculados en DB sobre turnos no-cancelados del rango; admin ve todo, odontólogo solo su `profesional_id` propio (cualquier otro id → `403`), recepción solo el día operativo (`desde==hasta==hoy`, otro rango → `403`).

#### Scenario: Ocupación con números esperados por profesional y sillón

- **WHEN** admin pide ocupación de una semana con 20 turnos activos de 40 slots en el profesional A y 10 de 40 en el sillón 1
- **THEN** responde `200` con `ocupacion_pct=50` para el profesional A y `25` para el sillón 1, solo con IDs y conteos

#### Scenario: Odontólogo ve solo sus propios números

- **WHEN** odontólogo pide ocupación propia y luego la de otro profesional
- **THEN** la propia es `200` con sus conteos y la ajena es `403` sin datos

#### Scenario: Recepción fuera del día operativo → 403

- **WHEN** recepción pide ocupación de una semana pasada
- **THEN** responde `403` genérico sin ejecutar la agregación

### Requirement: Ausentismo global y por profesional en rango

El sistema SHALL exponer `GET /api/v1/reportes/ausentismo?desde&hasta&profesional_id` que devuelve `{turnos_finalizados, ausentes, ausentismo_pct}` donde finalizados = `presente+atendido+ausente` y ausentes = `estado='ausente'`; mismo scoping por rol que ocupación; JAMÁS incluye DNI, teléfonos, nombres ni HCE.

#### Scenario: Ausentismo con números esperados

- **WHEN** admin pide ausentismo de un mes con 90 finalizados y 9 ausentes
- **THEN** responde `200` con `ausentismo_pct=10`, solo agregados sin PII

### Requirement: Ingresos por método en rango con conciliación visible

El sistema SHALL exponer `GET /api/v1/reportes/ingresos?desde&hasta&sede` que devuelve `{por_metodo: {efectivo, transferencia, tarjeta, mercadopago}, total, acreditado_mp, diferencia}` desde `movimiento_caja` (ingresos menos egresos) + `pago acreditado` (fuente C-08/C-09, solo lectura); admin full, odontólogo solo sus cobros propios agregados sin detalle de otros, recepción solo el día operativo.

#### Scenario: Ingresos por método con números esperados

- **WHEN** admin pide ingresos de un día con $10.000 efectivo, $8.000 MP declarado y $8.000 acreditado
- **THEN** responde `200` con `por_metodo={efectivo:10000, mercadopago:8000}`, `total=18000` y `diferencia=0`

### Requirement: Exportación CSV sanitizada en streaming

El sistema SHALL exponer `GET /api/v1/reportes/:tipo.csv?mismos_filtros` (`ocupacion|ausentismo|ingresos`; JWT, recurso `reportes_csv` → `admin` full y `odontologo` solo propios; recepción sin CSV → `403`) que responde `text/csv; charset=utf-8` con BOM, separador `,`, primera fila de headers fijos en español (`periodo_desde,periodo_hasta,dimension,dimension_id,turnos_totales,turnos_activos,horas_ocupadas,ocupacion_pct` / `periodo_desde,periodo_hasta,profesional_id,turnos_finalizados,ausentes,ausentismo_pct` / `periodo_desde,periodo_hasta,metodo,monto,total,acreditado_mp,diferencia`), cuerpo en streaming (no carga todo en memoria), `Content-Disposition: attachment`, y registra `reporte_csv_exportado`; el CSV JAMÁS contiene DNI, teléfonos, nombres, emails, HCE ni tokens.

#### Scenario: CSV de ingresos con headers y formato esperado

- **WHEN** admin descarga `GET /api/v1/reportes/ingresos.csv?desde=<d1>&hasta=<d2>`
- **THEN** responde `200` `text/csv` con la fila de headers exacta, una fila por método con montos del JSON, BOM inicial y evento `reporte_csv_exportado`

#### Scenario: CSV nunca expone PII

- **WHEN** se descargan los 3 CSV con datos reales del día
- **THEN** ningún campo coincide con DNI, teléfono, email, nombre de paciente ni HCE, y los montos igualan a los endpoints JSON

#### Scenario: Recepción pide CSV → 403

- **WHEN** recepción autenticada pide cualquier `*.csv`
- **THEN** responde `403` genérico sin generar contenido ni evento de exportación
