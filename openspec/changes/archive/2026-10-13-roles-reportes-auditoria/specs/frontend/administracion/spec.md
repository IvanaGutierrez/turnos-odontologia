# Spec Delta — `frontend/administracion`

## Purpose

Da al staff las pantallas de administración (usuarios, auditoría, reportes) con guardas por rol y vistas acotadas, en español y accesibles, sin mostrar jamás PII proveniente de auditoría o reportes.

## ADDED Requirements

### Requirement: Páginas admin con guardas por rol y rutas por vista

El sistema SHALL exponer `pages/admin/UsuariosPage` (recurso `usuarios`, solo admin), `pages/admin/AuditoriaPage` (recurso `auditoria`, solo admin) y `pages/admin/ReportesPage` (recurso `reportes`, admin/odontólogo/recepción) bajo `/admin/usuarios|/admin/auditoria|/admin/reportes`, todas tras `RequireRol` (deny-by-default, mensaje genérico en español + enlace al área del rol); sin permiso muestran acceso denegado sin llamar a la API.

#### Scenario: Recepción abre usuarios → denegado sin fetch

- **WHEN** un rol `recepcion` navega a `/admin/usuarios`
- **THEN** ve "Acceso denegado" con enlace a su área y no se emite ningún request a `/api/v1/usuarios`

#### Scenario: Odontólogo abre reportes propios sin datos ajenos

- **WHEN** odontólogo navega a `/admin/reportes`
- **THEN** ve solo sus tarjetas de ocupación/ausentismo/ingresos propios, sin selector de otros profesionales ni botón CSV ajeno

### Requirement: Usuarios y auditoría operables con datos sintéticos en tests

Usuarios SHALL listar/paginar, crear (email+rol+password), cambiar rol y desactivar con confirmación y mensajes en español; Auditoría SHALL filtrar por `entidad/entidad_id/accion/rango` y paginar, mostrando `{hora, usuario, acción, entidad, entidad_id}` sin columnas de PII/HC; ambas SHALL manejar `401/403/422/409` con mensajes del catálogo `es-AR` sin exponer cuerpos crudos.

#### Scenario: Admin desactiva un usuario con confirmación

- **WHEN** admin confirma la desactivación en `UsuariosPage`
- **THEN** la fila pasa a inactiva, se muestra aviso en español y no aparece ningún hash ni token en pantalla

#### Scenario: Admin filtra auditoría por turno

- **WHEN** admin filtra por `entidad=turno` y un id en `AuditoriaPage`
- **THEN** la tabla muestra solo esos eventos con hora, usuario y acción, sin DNI ni teléfonos

### Requirement: Reportes con 3 vistas y descarga CSV tipada

Reportes SHALL mostrar: admin full (filtros rango/profesional/sillón/sede + 3 bloques + descarga CSV por tipo), odontólogo propios (sus 3 bloques sin selectores ajenos + CSV propio), recepción operativo día (solo hoy + sede, sin CSV); la descarga SHALL usar blob tipado con nombre `reporte-<tipo>-<desde>-<hasta>.csv`; tablas con `<table>/<th scope>` y mensajes de vacío/error en español; cero `any` (R4).

#### Scenario: Admin descarga CSV de ocupación

- **WHEN** admin elige rango y pulsa descargar ocupación
- **THEN** se descarga `reporte-ocupacion-<desde>-<hasta>.csv` con los headers del contrato y los números visibles en pantalla

#### Scenario: Recepción solo ve el operativo del día

- **WHEN** recepción abre `/admin/reportes` un día cualquiera
- **THEN** ve ocupación/ausentismo/ingresos de hoy sin selectores de rango ni botón de descarga
