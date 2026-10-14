# Design — C-07 `ficha-odontograma-presupuesto`

## Context

Ver `proposal.md` (Why/What). Estado actual (solo lectura de `app/`): existen `Paciente.consentimiento_hc` (bool, C-01) y `Paciente.sin_whatsapp` (C-06); no hay ningún modelo, schema, router ni servicio clínico; la auditoría es append-only con `sanitizar_diff()` por denylist (ya incluye `anamnesis|historia_clinica|hc|dni|telefono|token|hash` — R6 reutilizable); la matriz `puede()` solo conoce `usuarios|configuracion_agenda|agenda_propia|turnos` (hay que extenderla con recursos clínicos, deny-by-default intacto); settings leen todo por env con fail-fast de `JWT_SECRET` (patrón a reusar para `HCE_CIFRADO_KEY`); migraciones 001–007 ocupadas con head `007_avisos_programacion` (por eso este change especifica la **008**, corrigiendo el "004" de CHANGES.md). Restricciones: R0 sintético (historias clínicas ficticias, jamás reales — crítico aquí), R1 hints, R2 capas + Alembic, R3 N/A (no se toca agenda/GiST), R5 TDD con cov 80, R6 máxima minimización (HC jamás en logs/errores/responses/diffs), R7 secretos solo env, R8 stack fijo.

## Goals / Non-Goals

**Goals:**

- HCE creable solo con consentimiento registrado, siempre con firmante profesional trazable.
- Odontograma FDI editable por batch con catálogo de estados versionado (~18) que preserva historia ante cambios de catálogo.
- Presupuesto nacido de hallazgos, con firma del paciente obligatoria antes de cualquier plan con seña, y máquina de estados explícita.
- HCE cifrada en reposo con rotación de clave documentada; exportación del paciente garantizada.

**Non-Goals:**

- Acreditar pagos o generar links MP (C-08; aquí solo `sena_requerida` + guarda "sin firma no hay plan con seña").
- Validación OS / liquidaciones (C-13 / v1.5), periodontograma, IA en imágenes, ARCA (v2).
- Frontend clínico (C-10 cubre agenda/reserva; la UI de odontograma llegará en un change posterior).

## Decisions

1. **Migración 008 `008_ficha_clinica` con `down_revision = "007_avisos_programacion"` (corrección a CHANGES.md).** CHANGES.md dice "Migración 004" pero `004_sobreturno_reprogramacion` … `007_avisos_programacion` ya existen (verificado en `backend/alembic/versions/`); el próximo número libre es **008**. Crea `ficha`, `odontograma_entry`, `evolucion`, `presupuesto`, `presupuesto_item`, `plan_tratamiento`, `catalogo_odontograma_estado`; no toca GiST ni tablas de agenda (R3 intacta). Alternativa descartada: renumerar — rompería el historial Alembic de C-01…C-06.
2. **Cifrado en reposo a nivel aplicación, no pgcrypto (standard sqlalchemy + R7).** Columnas `ficha.anamnesis_cifrada` (BYTEA) y `evolucion.texto_cifrado` (BYTEA) con AES-256-GCM (Fernet) aplicado en la capa repositorio/servicio; clave `HCE_CIFRADO_KEY` (32+ bytes, fail-fast como `JWT_SECRET`) + `HCE_CIFRADO_KEY_ANTERIOR` para gracia de rotación; columna `clave_id` por fila para saber con qué clave descifrar. Rotación documentada: desplegar con ambas claves → re-cifrar en background por lotes → retirar anterior. El plaintext jamás sale del servicio (schemas de lectura devuelven minimizado o solo a roles clínicos). Alternativa descartada: `pgcrypto/pgp_sym_encrypt` — acopla el cifrado a la extensión PG, mete la clave en SQL/logs de queries y complica la rotación.
3. **Catálogo de estados versionado en tabla propia (RN-CL-02).** `catalogo_odontograma_estado(version INT, codigo TEXT, descripcion TEXT, activo BOOL, UNIQUE(version, codigo))` seed con ~18 estados (ref. DentalSoft: `sano|cariado|obturado|endodoncia|corona|implante|extraccion|ausente|…`); `odontograma_entry` guarda `estado_codigo + catalogo_version` (FK compuesta) en vez de texto libre, así un cambio de catálogo (v2) no reescribe historia. `pieza_fdi` con `CHECK (pieza_fdi BETWEEN 11 AND 48)` más validación de dientes FDI reales por servicio (11–18, 21–28, 31–38, 41–48); `cara?` (`oclusal|mesial|distal|vestibular|lingual|palatino`) opcional; UNIQUE `(ficha_id, pieza_fdi, cara NULLS NOT DISTINCT)` + índice `(ficha_id, pieza_fdi)`. Estado fuera de catálogo o pieza inválida → `422`. Alternativa descartada: enum/check de texto libre — imposible evolucionar sin migraciones destructivas ni auditar qué significaba cada estado.
4. **Gate de consentimiento en servicio, no solo en DB (RN-CL-01, Ley 26.529).** `POST /api/v1/fichas` exige `paciente.consentimiento_hc = true` (con fecha registrada); si falta → `422` con mensaje de política + guía para registrar consentimiento, sin crear nada. CHECK DB como defensa en profundidad (`ficha` exige snapshot `consentimiento_en` NOT NULL copiado del paciente al crear). Sin consentimiento no existe HCE: ni ficha, ni odontograma, ni evolución. Alternativa descartada: solo validar en frontend — el endpoint quedaría abierto a escritura directa.
5. **Firmante obligatorio + auditoría sin contenido (RN-CL-04, R6).** Toda escritura clínica registra `firmante_usuario_id + firmado_en` (odontólogo autenticado por JWT; admin no firma clínica). `AuditoriaLog` recibe `ficha_editada|odontograma_actualizado|evolucion_agregada|presupuesto_*` con diff mínimo `{ficha_id, campo_modificado, firmante_rol, fecha}` — jamás anamnesis, textos clínicos, DNI ni teléfonos (`sanitizar_diff` ya los deniega; se extiende con `pieza|estado` si hiciera falta granularidad, manteniendo códigos, no narrativa). Recepción escribiendo clínica → `403` genérico + `acceso_clinico_denegado` auditado; recepción editando contacto (nombre/teléfono/email) → `200` por el canal existente de pacientes.
6. **RBAC clínico por extensión de la matriz (standard fastapi).** Nuevos recursos `ficha_clinica` → `{admin(R auditoría), odontologo}`, `odontograma` → `{admin(R), odontologo}`, `presupuesto` → `{admin, odontologo}` + `recepcion` solo lectura y generación de link de pago (link real en C-08), `exportacion_datos` → titular + `{admin, odontologo, recepcion}` según alcance. `puede()` sin cambios (deny-by-default); `require_role()` existente en routers. Recepción ve ficha en modo lectura de contacto + presupuestos para cobrar; jamás edita clínica. Alternativa descartada: nuevo sistema de permisos — duplicaría la matriz de C-02.
7. **Presupuesto nace de hallazgos + firma del paciente gatea la seña (RN-CL-03, Flujo 3).** `POST /api/v1/presupuestos` acepta `desde_hallazgos: [{pieza_fdi, estado_codigo, prestacion_id}]` y genera items (pieza + prestación + cantidad + precio_unitario desde `prestacion.precio_base?`); total calculado en servicio. Máquina de estados: `borrador→aprobado` exige `firma_paciente` (registro firma+fecha vía `POST …/firma`, táctil/registro) → `422` si falta; `aprobado→pagado_parcial|pagado` solo vía webhook C-08; `borrador→rechazado` terminal con motivo. Plan con `sena_requerida > 0` sin firma → `422` (RN-CL-03 + RN-PA-01 combinadas). Presupuesto responde sin narrativa clínica, solo piezas/códigos/montos.
8. **Exportación del paciente como endpoint dedicado (Ley 25.326).** `GET /api/v1/pacientes/:id/exportacion` ( titular con su DNI+token, o rol clínico/admin) devuelve paquete JSON `{datos_contacto, consentimientos, ficha, odontograma, evoluciones, presupuestos, turnos}` con anamnesis descifrada solo para el titular/odontólogo tratante; auditoría `datos_exportados`. Rate-limit + respuesta paginada; jamás incluye claves ni `clave_id`. Alternativa descartada: volcado SQL/manual — no es ejercible por el paciente ni auditable.
9. **Testing (plan, se ejecuta en apply — R5, AAA, cov 80):** pytest sobre Postgres real (migración 008 aplicada, `downgrade -1`/re-`upgrade` verificados); fixtures sintéticas con prefijo HC ficticia (`PAC-HC-FICTICIO-*`, jamás datos reales, R0); casos: crear HCE sin consentimiento → 422 y cero filas; con consentimiento → 201 + firmante = odontólogo JWT; recepción `PATCH` clínica → 403 + `acceso_clinico_denegado` (y `PATCH` contacto → 200); odontólogo edita → 200 + `ficha_editada` con firmante y sin contenido clínico en el diff; batch odontograma válido → upsert por pieza; pieza 19/49 → 422; estado inexistente → 422; presupuesto desde hallazgos con total correcto; `aprobar` sin firma → 422, con firma → `aprobado`; transición `borrado→pagado` directa → 422; exportación contiene todas las secciones y audita; grep de suite confirma cero `anamnesis`/HC en logs y responses de error minimizadas.

## Runbook de rotación `HCE_CIFRADO_KEY` (GREEN parte 2, R7)

1. Backup cifrado de `ficha`/`evolucion` antes de rotar (nunca plaintext fuera del servicio).
2. Desplegar con ambas claves: `HCE_CIFRADO_KEY_ANTERIOR` = vieja, `HCE_CIFRADO_KEY` = nueva.
   La lectura prueba vigente y luego anterior (`services/cifrado_hce.py:descifrar`); la escritura
   usa siempre la vigente con `clave_id = hce-v1`.
3. Re-cifrar en background por lotes (leer con anterior → escribir con vigente, actualizar
   `clave_id`); verificar cero filas con el `clave_id` viejo antes de retirar la anterior.
4. Retirar `HCE_CIFRADO_KEY_ANTERIOR` del env y redeplegar; la app no levanta sin
   `HCE_CIFRADO_KEY` de 32+ bytes (fail-fast como `JWT_SECRET`, `settings.py`).

## Risks / Trade-offs

- [Riesgo] Clave `HCE_CIFRADO_KEY` perdida/rotada sin gracia → HCE ilegible. Mitigación: fail-fast al boot, `clave_id` por fila, ventana dual con `HCE_CIFRADO_KEY_ANTERIOR`, backup cifrado antes de rotar, runbook en design.
- [Riesgo] Catálogo v2 deja entries huérfanas. Mitigación: FK compuesta a `(version, codigo)` + nunca borrar versiones, solo `activo=false`; migración de catálogo versionada y auditada.
- [Riesgo] Firma del paciente disputada (repudio). Mitigación: registro firma+fecha+firmante+IP/dispositivo y hash del presupuesto firmado; el contenido firmado queda inmutable (cualquier cambio post-firma exige nueva versión del presupuesto).
- [Riesgo] Exportación con HC descifrada en tránsito. Mitigación: solo HTTPS, JWT de corta vida, minimización por rol, auditoría obligatoria, rate-limit.
- [Trade-off] Cifrado app-level vs pgcrypto. Aceptado app-level: costo de implementar envoltura en repositorio a cambio de claves fuera de SQL, rotación limpia y plaintext confinado al servicio.
