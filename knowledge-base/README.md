# Turnos Odontología (AR) — Base de Conocimiento

Base de conocimiento generada desde `docs/discovery/informe-discovery.md` (18 sistemas, matriz ponderada, MVP) + `discovery/discovery.md` (checklist 11 puntos) + sección `discovery` del state (Mode A, `source: "ingest"`). Fecha: 2026-09-30.

## Índice de Archivos

| Archivo | Contenido |
|---------|-----------|
| [01_vision_y_objetivos.md](01_vision_y_objetivos.md) | Propósito, objetivos por actor, alcance v1/v1.5/v2, fuera de alcance, métricas |
| [02_descripcion_general.md](02_descripcion_general.md) | Stack fijo, arquitectura, integraciones, API REST |
| [03_actores_y_roles.md](03_actores_y_roles.md) | 5 actores + workers, matriz RBAC, rutas públicas |
| [04_modelo_de_datos.md](04_modelo_de_datos.md) | 7 dominios, ERD, 14 entidades, seed |
| [05_reglas_de_negocio.md](05_reglas_de_negocio.md) | 25 reglas RN-AG/PU/PA/CL/AU/NO/OS + excepciones |
| [06_funcionalidades.md](06_funcionalidades.md) | 6 épicas, 11 US (v1 + v1.5) con CA y reglas |
| [07_flujos_principales.md](07_flujos_principales.md) | Reserva, writeback WA, atención, seña MP, lista de espera, cierre |
| [08_arquitectura_propuesta.md](08_arquitectura_propuesta.md) | Patrones, directorios, seguridad Ley 25.326/26.529, env vars |
| [09_decisiones_y_supuestos.md](09_decisiones_y_supuestos.md) | 7 decisiones DD + 4 supuestos SU |
| [10_preguntas_abiertas.md](10_preguntas_abiertas.md) | 2 inconsistencias + top 5 preguntas críticas |
| [11_integraciones_locales.md](11_integraciones_locales.md) | Extra 1X: WhatsApp + Mercado Pago + ARCA + GCal |

## Quick Start para Desarrolladores

1. Entender el dominio → [01](01_vision_y_objetivos.md), [03](03_actores_y_roles.md)
2. Entender los datos → [04](04_modelo_de_datos.md)
3. Entender las reglas → [05](05_reglas_de_negocio.md)
4. Entender la arquitectura → [02](02_descripcion_general.md), [08](08_arquitectura_propuesta.md)
5. Implementar → [07](07_flujos_principales.md), [06](06_funcionalidades.md)
6. Antes de codificar → [10](10_preguntas_abiertas.md)

## Resumen Ejecutivo

Sistema de turnos odontológicos para Argentina (FastAPI + React) que combina agenda online sin cuenta, WhatsApp nativo, odontograma + presupuestos y señas por Mercado Pago; deja OS preventiva y lista de espera con seña como moat v1.5 y ARCA nativa para v2 — el hueco que ningún competidor cubre hoy.
