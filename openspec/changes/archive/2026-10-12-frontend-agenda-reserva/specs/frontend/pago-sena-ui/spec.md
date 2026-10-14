# Spec Delta — `frontend/pago-sena-ui`

## Purpose

Página pública de pago de seña por Mercado Pago: a partir del token del turno, inicia el checkout contra el contrato C-08 y redirige al paciente a Mercado Pago, informando en español el estado del pago sin exponer datos sensibles.

## ADDED Requirements

### Requirement: Checkout de seña con redirección a Mercado Pago

La UI SHALL, ante `pages/pagar/:token`, resolver el link de pago (`GET /pagar/:token` de C-08) y redirigir al paciente a Mercado Pago, mostrando antes un resumen mínimo (concepto, monto en ARS, estado de la seña) y el estado posterior (acreditado y turno `confirmado`, pendiente con reintento, o error con aviso accionable); SHALL jamás iniciar el pago dos veces por doble clic ni exponer el token en reportes de error.

#### Scenario: Pago de seña redirige a Mercado Pago

- **WHEN** un paciente con turno que requiere seña abre `pagar/:token` válido y pulsa pagar
- **THEN** la UI muestra el resumen (concepto y monto en ARS), redirige a la URL de Mercado Pago entregada por el backend una sola vez aunque se pulse dos veces, y tras la acreditación informa turno `confirmado` en español

#### Scenario: Pago pendiente o rechazado ofrece reintento sin perder el turno

- **WHEN** el pago vuelve pendiente o rechazado (el turno sigue sin confirmar según RN-PA-02)
- **THEN** la UI muestra el estado visible en español con un reintento explícito, indica que el turno sigue reservado pendiente de seña, y nunca declara el turno confirmado antes de la acreditación del backend

#### Scenario: Token de pago inválido no filtra datos

- **WHEN** se abre `pagar/:token` con un token inexistente o malformado
- **THEN** la UI muestra un no-encontrado genérico en español sin concepto, monto ni datos del turno, y no registra el token en consola ni en reportes
