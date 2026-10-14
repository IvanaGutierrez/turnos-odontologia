# Proposal — C-09 `caja-cierre-diario`

## Why

La seña por Mercado Pago ya acredita pagos reales (C-08, US-030), pero ese dinero no se concilia contra nada: no existe registro de movimientos manuales (efectivo/transferencia/tarjeta) ni cierre diario que compare lo declarado por recepción contra lo acreditado. Sin este change, la clínica no puede detectar faltantes ni cerrar el día (US-031, Flujo 6, RN-PA-04/05). Governance ALTO: hay dinero en juego y bloqueo operativo (día cerrado bloquea movimientos).

## What Changes

- `POST /api/v1/caja/movimientos` — registra ingresos/egresos por método (`efectivo|transferencia|tarjeta|mercadopago`) con `usuario_id` (operador autenticado) y `concepto` obligatorios (RN-PA-05); método inválido → `422`; movimiento con fecha en día cerrado → `422`.
- `POST /api/v1/caja/cierre` — cierra el día/sede: snapshot de totales por método desde movimientos, compara contra pagos `acreditado` del día y marca `diferencia` (`cuadrado|con_diferencia`); UN solo cierre por (fecha, sede) — segundo intento → `409` (RN-PA-04).
- `POST /api/v1/caja/reapertura` — revierte un cierre a `abierto`; SOLO admin (`403` + log para no-admin), siempre auditada (RN-PA-04, RN-AU-03).
- `GET /api/v1/caja/movimientos?fecha&sede` + `GET /api/v1/caja/cierre?fecha&sede` — listado/consulta para el arqueo de recepción (Flujo 6 paso 1).
- Modelos `MovimientoCaja`, `CierreDiario`; **migración Alembic 011** (ver design decisión 1: CHANGES.md decía "006" pero 006–010 ya existen; cadena verificada `001→…→010_pago_comprobante`, head `010`).
- Tests planeados (se ejecutan en apply, datos sintéticos — R0).

## Capabilities

### New Capabilities

- `cobros/caja-cierre-diario`: caja con movimientos por método, cierre diario con conciliación contra pagos acreditados y marca de diferencias, unicidad día/sede, bloqueo de día cerrado y reapertura admin auditada.

### Modified Capabilities

_(ninguna — `cobros/sena-mercadopago` no cambia sus REQUIREMENTS: el evento `pago_acreditado` v1 sigue con el mismo shape y se consume de solo lectura; `agenda/*` y `auditoria` se reutilizan sin modificar)_

## Impact

- Nuevo: modelos `MovimientoCaja`/`CierreDiario` + migración 011, servicio `caja.py`, router `caja` bajo `/api/v1` con JWT + RBAC (recurso nuevo `caja`, reapertura solo admin), settings `CAJA_*` solo por env (R7), `.env.example` extendido.
- Reusa sin modificar: tabla `pago` + evento `pago_acreditado` v1 de C-08 (fuente de conciliación, solo lectura), matriz RBAC C-02 (se extiende con recursos nuevos, sin cambiar los existentes), `AuditoriaLog` + `sanitizar_diff` C-02 (eventos `movimiento_registrado|cierre_creado|cierre_reabierto`), sede como texto con default `"Consultorio"` (patrón `Sillon.sede`).
- No-objetivos explícitos: facturación ARCA (v2), reembolsos automáticos, cobro de OS (C-13), reportes/exportación CSV (C-11 consume los snapshots, no los implementa), multi-sede real (sede es texto, una por defecto).
