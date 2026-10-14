// Acceso a los contratos C-03 (reserva/disponibilidad) y C-05 (autogestión)
// desde la UI pública: sin JWT, con token de idempotencia en la creación.
// Reutiliza `shared/api-client` (R2-front); jamás registra PII (R6).

import { ApiError, crearClienteApi, type ClienteApi } from "../../shared/api-client/apiClient";
import type {
  ReprogramacionPropia,
  SlotLibre,
  TurnoPropio,
  TurnoPublicoCreado,
} from "./tipos";

const cliente: ClienteApi = crearClienteApi();

export interface NuevoTurnoPublico {
  readonly prestacion_id: string;
  readonly profesional_id: string;
  readonly inicio: string;
  readonly fin: string;
  readonly dni: string;
  readonly telefono: string;
}

function esRegistro(valor: unknown): valor is Record<string, unknown> {
  return typeof valor === "object" && valor !== null;
}

function esSlotLibre(valor: unknown): valor is SlotLibre {
  if (!esRegistro(valor)) return false;
  return (
    typeof valor["inicio"] === "string" &&
    typeof valor["fin"] === "string" &&
    typeof valor["profesional_id"] === "string" &&
    typeof valor["prestacion_id"] === "string"
  );
}

function esTurnoPublicoCreado(valor: unknown): valor is TurnoPublicoCreado {
  if (!esRegistro(valor)) return false;
  return (
    typeof valor["id"] === "string" &&
    typeof valor["profesional_id"] === "string" &&
    typeof valor["prestacion_id"] === "string" &&
    typeof valor["inicio"] === "string" &&
    typeof valor["fin"] === "string" &&
    typeof valor["estado"] === "string" &&
    typeof valor["canal"] === "string" &&
    typeof valor["token_publico"] === "string" &&
    (valor["url_pago"] === null || typeof valor["url_pago"] === "string")
  );
}

function esTurnoPropio(valor: unknown): valor is TurnoPropio {
  if (!esRegistro(valor)) return false;
  return (
    typeof valor["estado"] === "string" &&
    typeof valor["inicio"] === "string" &&
    typeof valor["fin"] === "string" &&
    typeof valor["prestacion_nombre"] === "string" &&
    typeof valor["profesional_nombre"] === "string" &&
    typeof valor["sede"] === "string" &&
    typeof valor["puede_cancelar_en_termino"] === "boolean" &&
    typeof valor["horas_limite"] === "number"
  );
}

function esReprogramacionPropia(valor: unknown): valor is ReprogramacionPropia {
  if (!esRegistro(valor)) return false;
  return (
    typeof valor["id"] === "string" &&
    typeof valor["token_publico"] === "string" &&
    typeof valor["estado"] === "string" &&
    typeof valor["inicio"] === "string" &&
    typeof valor["fin"] === "string"
  );
}

function exigir<T>(valor: unknown, guarda: (v: unknown) => v is T, mensaje: string): T {
  if (!guarda(valor)) throw new Error(mensaje);
  return valor;
}

/** Slots reales desde `GET /api/v1/disponibilidad` (C-03). */
export async function obtenerDisponibilidad(): Promise<SlotLibre[]> {
  const respuesta = await cliente.get<unknown>("/disponibilidad");
  if (!Array.isArray(respuesta)) throw new Error("Respuesta de disponibilidad inválida.");
  return respuesta.filter(esSlotLibre);
}

/** Crea el turno con una sola request idempotente (`Idempotency-Key`). */
export async function crearTurnoPublico(
  nuevo: NuevoTurnoPublico,
  claveIdempotencia: string,
): Promise<TurnoPublicoCreado> {
  const respuesta = await cliente.post<unknown>("/turnos/publicos", nuevo, {
    idempotencia: claveIdempotencia,
  });
  return exigir(respuesta, esTurnoPublicoCreado, "Respuesta de reserva inválida.");
}

/** Ver-propio mínimo (`GET /turnos/publicos/:token`, C-05). */
export async function verTurnoPropio(token: string): Promise<TurnoPropio> {
  const respuesta = await cliente.get<unknown>(`/turnos/publicos/${encodeURIComponent(token)}`);
  return exigir(respuesta, esTurnoPropio, "Respuesta de turno inválida.");
}

export async function confirmarTurnoPropio(token: string): Promise<TurnoPropio> {
  const respuesta = await cliente.post<unknown>(
    `/turnos/publicos/${encodeURIComponent(token)}/confirmar`,
  );
  return exigir(respuesta, esTurnoPropio, "Respuesta de confirmación inválida.");
}

/** `consulta` arrastra el query previo (`?fuera_de_termino=1`) si lo había. */
export async function cancelarTurnoPropio(token: string, consulta: string): Promise<TurnoPropio> {
  const ruta = `/turnos/publicos/${encodeURIComponent(token)}/cancelar${consulta}`;
  const respuesta = await cliente.post<unknown>(ruta);
  return exigir(respuesta, esTurnoPropio, "Respuesta de cancelación inválida.");
}

export async function reprogramarTurnoPropio(
  token: string,
  inicio: string,
): Promise<ReprogramacionPropia> {
  const respuesta = await cliente.post<unknown>(
    `/turnos/publicos/${encodeURIComponent(token)}/reprogramar`,
    { inicio },
  );
  return exigir(respuesta, esReprogramacionPropia, "Respuesta de reprogramación inválida.");
}

/**
 * `detalle` crudo del backend (p. ej. política de cancelación del 422).
 * El backend ya lo envía sanitizado; solo se usa si es texto.
 */
export function detalleDeError(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  if (!esRegistro(error.datos)) return null;
  return typeof error.datos["detalle"] === "string" ? error.datos["detalle"] : null;
}

/** `slots_alternativos` del 409 (lista vacía si el cuerpo no los trae). */
export function alternativosDeError(error: unknown): SlotLibre[] {
  if (!(error instanceof ApiError)) return [];
  if (!esRegistro(error.datos)) return [];
  const lista: unknown = error.datos["slots_alternativos"];
  if (!Array.isArray(lista)) return [];
  return lista.filter(esSlotLibre);
}
