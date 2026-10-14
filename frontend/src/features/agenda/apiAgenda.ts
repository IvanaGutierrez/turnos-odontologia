// Acceso a agenda operativa (C-04) y turnos staff (C-01/C-04) desde la UI de
// recepción: grilla día/semana, crear, confirmar, check-in, reprogramar y
// sobreturno auditado. Reutiliza el cliente con sesión en memoria (R2-front);
// jamás registra PII: los errores se traducen a mensajes genéricos (R6).

import { ApiError, type ClienteApi } from "../../shared/api-client/apiClient";
import { clienteSesion } from "../../shared/auth/auth";
import type { SlotLibre, TurnoOperativo } from "../reserva-publica/tipos";

const cliente: ClienteApi = clienteSesion();

export interface NuevoTurnoStaff {
  readonly profesional_id: string;
  readonly prestacion_id: string;
  readonly inicio: string;
  readonly fin: string;
  readonly canal: string;
}

export interface NuevoSobreturnoStaff extends NuevoTurnoStaff {
  readonly motivo_sobreturno: string;
}

/** Alternativo del 409: solo exige inicio/fin (el backend puede mandar el slot mínimo). */
export interface SlotAlternativo {
  readonly inicio: string;
  readonly fin: string;
}

export interface ReprogramacionStaff {
  readonly id: string;
  readonly token_publico: string;
  readonly estado: string;
  readonly inicio: string;
  readonly fin: string;
}

function esRegistro(valor: unknown): valor is Record<string, unknown> {
  return typeof valor === "object" && valor !== null;
}

function esTurnoOperativo(valor: unknown): valor is TurnoOperativo {
  // Los endpoints staff devuelven `TurnoRead` (sin `paciente_nombre`) y la
  // grilla C-04 suma `paciente_nombre` + `sobreturno`: los opcionales llevan
  // defaults para aceptar ambos shapes sin inventar datos.
  if (!esRegistro(valor)) return false;
  const base =
    typeof valor["id"] === "string" &&
    typeof valor["inicio"] === "string" &&
    typeof valor["fin"] === "string" &&
    typeof valor["estado"] === "string" &&
    typeof valor["profesional_id"] === "string" &&
    typeof valor["prestacion_id"] === "string";
  if (!base) return false;
  const sillon = valor["sillon_id"];
  const sobreturno = valor["sobreturno"];
  const paciente = valor["paciente_nombre"];
  return (
    (sillon === undefined || sillon === null || typeof sillon === "string") &&
    (sobreturno === undefined || typeof sobreturno === "boolean") &&
    (paciente === undefined || paciente === null || typeof paciente === "string")
  );
}

function normalizarTurno(valor: unknown): TurnoOperativo {
  if (!esTurnoOperativo(valor)) throw new Error("Respuesta de turno inválida.");
  const registro = valor as unknown as Record<string, unknown>;
  const sillon = registro["sillon_id"];
  const sobreturno = registro["sobreturno"];
  const paciente = registro["paciente_nombre"];
  return {
    id: valor.id,
    inicio: valor.inicio,
    fin: valor.fin,
    estado: valor.estado,
    profesional_id: valor.profesional_id,
    sillon_id: typeof sillon === "string" ? sillon : null,
    prestacion_id: valor.prestacion_id,
    sobreturno: typeof sobreturno === "boolean" ? sobreturno : false,
    paciente_nombre: typeof paciente === "string" ? paciente : null,
  };
}

function esSlotAlternativo(valor: unknown): valor is SlotAlternativo {
  if (!esRegistro(valor)) return false;
  return typeof valor["inicio"] === "string" && typeof valor["fin"] === "string";
}

function esReprogramacionStaff(valor: unknown): valor is ReprogramacionStaff {
  if (!esRegistro(valor)) return false;
  return (
    typeof valor["id"] === "string" &&
    typeof valor["token_publico"] === "string" &&
    typeof valor["estado"] === "string" &&
    typeof valor["inicio"] === "string" &&
    typeof valor["fin"] === "string"
  );
}

/** Grilla día/semana (`GET /api/v1/agenda`): la consulta viaja como params (el cliente la codifica). */
export async function obtenerAgenda(
  params: Record<string, string>,
): Promise<TurnoOperativo[]> {
  const respuesta = await cliente.get<unknown>("/agenda", params);
  if (!Array.isArray(respuesta)) throw new Error("Respuesta de agenda inválida.");
  return respuesta.filter(esTurnoOperativo);
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

/** Slots para los diálogos de crear/reprogramar (`GET /api/v1/disponibilidad`, C-03). */
export async function obtenerSlotsAgenda(): Promise<SlotLibre[]> {
  const respuesta = await cliente.get<unknown>("/disponibilidad");
  if (!Array.isArray(respuesta)) throw new Error("Respuesta de disponibilidad inválida.");
  return respuesta.filter(esSlotAlternativo).map((slot, indice) => {
    if (esSlotLibre(slot)) return slot;
    return {
      inicio: slot.inicio,
      fin: slot.fin,
      profesional_id: `profesional-ficticio-${String(indice)}`,
      prestacion_id: `prestacion-ficticia-${String(indice)}`,
    };
  });
}

export async function crearTurnoStaff(nuevo: NuevoTurnoStaff): Promise<TurnoOperativo> {
  const respuesta = await cliente.post<unknown>("/turnos", nuevo);
  return normalizarTurno(respuesta);
}

export async function crearSobreturnoStaff(
  nuevo: NuevoSobreturnoStaff,
): Promise<TurnoOperativo> {
  const respuesta = await cliente.post<unknown>("/turnos/sobreturno", nuevo);
  return normalizarTurno(respuesta);
}

export async function confirmarTurnoStaff(id: string): Promise<TurnoOperativo> {
  const respuesta = await cliente.post<unknown>(`/turnos/${encodeURIComponent(id)}/confirmar`);
  return normalizarTurno(respuesta);
}

export async function checkinTurnoStaff(id: string): Promise<TurnoOperativo> {
  const respuesta = await cliente.post<unknown>(`/turnos/${encodeURIComponent(id)}/check-in`);
  return normalizarTurno(respuesta);
}

export async function reprogramarTurnoStaff(
  id: string,
  nuevoInicio: string,
): Promise<ReprogramacionStaff> {
  const respuesta = await cliente.post<unknown>(`/turnos/${encodeURIComponent(id)}/reprogramar`, {
    nuevo_inicio: nuevoInicio,
  });
  if (!esReprogramacionStaff(respuesta)) throw new Error("Respuesta de reprogramación inválida.");
  return respuesta;
}

/** `detalle` crudo del backend (p. ej. ventana máxima del 422): ya viene sanitizado y en español. */
export function detalleDeErrorAgenda(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  if (!esRegistro(error.datos)) return null;
  return typeof error.datos["detalle"] === "string" ? error.datos["detalle"] : null;
}

/** `slots_alternativos` del 409 (lista vacía si el cuerpo no los trae). */
export function alternativosDeErrorAgenda(error: unknown): SlotAlternativo[] {
  if (!(error instanceof ApiError)) return [];
  if (!esRegistro(error.datos)) return [];
  const lista: unknown = error.datos["slots_alternativos"];
  if (!Array.isArray(lista)) return [];
  return lista.filter(esSlotAlternativo);
}
