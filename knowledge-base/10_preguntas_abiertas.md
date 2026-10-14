# Preguntas Abiertas

## Inconsistencias detectadas

### IN-01 — OS en MVP vs v1.5
**Documento A dice**: `discovery/discovery.md` §5 (necesarias) no lista OS; §6 (opcionales) pone validación OS como diferenciador v1.5.
**Documento B dice**: state `discovery.funcionalidades_necesarias` tampoco incluye OS; casos de uso sí incluyen "validar cobertura antes de atender".
**Impacto**: define si US-050 bloquea el MVP.
**Resolución propuesta**: OS = v1.5 (no bloquea MVP); registrar cobertura manual simple en v1 si el piloto lo exige.

### IN-02 — Cancelación: regla propone default 12 h sin fuente
**Documento A dice**: `discovery.md` §7 exige "antelación mínima configurable" sin valor.
**Documento B dice**: KB propone default 12 h (RN-AG-05).
**Impacto**: bajo; parametrizable.
**Resolución propuesta**: mantener configurable con default 12 h; validar con pilotos.

## Preguntas abiertas (priorizadas, top 5 crítico)

| Prioridad | Pregunta | Bloquea | Decisor |
|-----------|----------|---------|---------|
| Alta | ¿La obra social entra en el MVP o en v1.5 como diferenciador temprano? | Alcance sprint 1 (US-050) | Product Owner |
| Alta | ¿El paciente reserva solo con DNI + teléfono o necesita cuenta con login? (KB propone sin cuenta — DD-02) | Diseño auth pública + US-002 | Product Owner |
| Alta | ¿Multi-sucursal desde el día 1 o alcanza un consultorio/sede? | Modelo de caja/reportes | Product Owner |
| Alta | ¿Modelo de precio del producto (suscripción ARS por profesional/sede/comisión)? | Estrategia + costos WA/MP | Dueño / sponsor |
| Alta | ¿Se valida el cambio de hábito online vs WhatsApp manual con pilotos antes de construir todo? | Riesgo central del MVP (SU-01) | Product Owner + consultorios piloto |
