// Sesión JWT contra C-02 (spec `api-client-auth`): login, logout, perfil propio
// y traducción de errores a mensajes operativos genéricos en español (R6).
// El access vive solo en el `api-client` en memoria; el refresh viaja en
// cookie HttpOnly (`credentials: include`).

import { ApiError, crearClienteApi, type ClienteApi } from "../api-client/apiClient";
import { sanitizarError } from "../api-client/sanitize";
import { MENSAJES } from "../i18n/es-AR";

export interface Credenciales {
  readonly email: string;
  readonly password: string;
}

export interface Perfil {
  readonly id: string;
  readonly email: string;
  readonly roles: string[];
  readonly activo: boolean;
}

export interface Sesion {
  readonly email: string;
  readonly roles: string[];
}

const cliente: ClienteApi = crearClienteApi();

/** Cliente compartido con la sesión (access en memoria): las features de staff lo reutilizan (R2-front). */
export function clienteSesion(): ClienteApi {
  return cliente;
}

let sesionActual: Sesion | null = null;

/** Sesión mínima en memoria (email + roles): jamás se persiste (R6). */
export function obtenerSesion(): Sesion | null {
  return sesionActual;
}

export function establecerSesion(sesion: Sesion | null): void {
  sesionActual = sesion;
}

function esLoginOk(valor: unknown): valor is { access_token: string } {
  if (typeof valor !== "object" || valor === null) return false;
  const registro = valor as Record<string, unknown>;
  return typeof registro["access_token"] === "string";
}

function esPerfil(valor: unknown): valor is Perfil {
  if (typeof valor !== "object" || valor === null) return false;
  const registro = valor as Record<string, unknown>;
  return (
    typeof registro["id"] === "string" &&
    typeof registro["email"] === "string" &&
    Array.isArray(registro["roles"]) &&
    (registro["roles"] as unknown[]).every((rol) => typeof rol === "string") &&
    typeof registro["activo"] === "boolean"
  );
}

function aPerfil(valor: Perfil): Perfil {
  return { id: valor.id, email: valor.email, roles: [...valor.roles], activo: valor.activo };
}

/** Traduce cualquier fallo de sesión a `Error` genérico en español (sin PII). */
function traducirErrorSesion(error: unknown): Error {
  if (error instanceof ApiError) {
    if (error.estado === 401) return new Error(MENSAJES.credencialesInvalidas);
    if (error.estado === 429) return new Error(MENSAJES.esperaRateLimit);
    if (error.estado === 403) return new Error(MENSAJES.accesoDenegado);
    return new Error(sanitizarError(error.mensaje));
  }
  if (error instanceof Error) return new Error(sanitizarError(error.message));
  return new Error(MENSAJES.errorInesperado);
}

/** Traduce un error técnico a mensaje visible para el usuario. */
export function mensajeParaUsuario(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.estado === 401) return MENSAJES.sesionExpirada;
    if (error.estado === 403) return MENSAJES.accesoDenegado;
    if (error.estado === 404) return MENSAJES.noEncontrado;
    if (error.estado === 409) return MENSAJES.slotOcupado;
    if (error.estado === 422) return MENSAJES.datosInvalidos;
    if (error.estado === 429) return MENSAJES.esperaRateLimit;
    if (error.estado === 0) return MENSAJES.errorRed;
    if (error.estado >= 500) return MENSAJES.errorServidor;
    return sanitizarError(error.mensaje);
  }
  if (error instanceof Error) return sanitizarError(error.message);
  return MENSAJES.errorInesperado;
}

/** Inicia sesión y devuelve email + roles del perfil propio. */
export async function iniciarSesion(credenciales: Credenciales): Promise<Sesion> {
  let respuesta: unknown;
  try {
    respuesta = await cliente.post<unknown>("/auth/login", {
      email: credenciales.email,
      password: credenciales.password,
    });
  } catch (error) {
    throw traducirErrorSesion(error);
  }
  if (!esLoginOk(respuesta)) {
    cliente.limpiarAccess();
    throw new Error(MENSAJES.credencialesInvalidas);
  }
  cliente.establecerAccess(respuesta.access_token);
  try {
    const perfil = await obtenerPerfil();
    const sesion: Sesion = { email: perfil.email, roles: perfil.roles };
    establecerSesion(sesion);
    return sesion;
  } catch (error) {
    cliente.limpiarAccess();
    establecerSesion(null);
    throw traducirErrorSesion(error);
  }
}

/** Cierra la sesión en el servidor y limpia el access local. */
export async function cerrarSesion(): Promise<void> {
  try {
    await cliente.post<unknown>("/auth/logout");
  } catch {
    // El cierre local vale igual aunque la red falle.
  } finally {
    cliente.limpiarAccess();
    establecerSesion(null);
  }
}

/** Perfil propio (`me`); falla si no hay sesión local. */
export async function obtenerPerfil(): Promise<Perfil> {
  if (cliente.accessActual() === null) {
    throw new Error(MENSAJES.sesionExpirada);
  }
  try {
    const respuesta = await cliente.get<unknown>("/auth/me");
    if (!esPerfil(respuesta)) throw new Error(MENSAJES.sesionExpirada);
    return aPerfil(respuesta);
  } catch (error) {
    if (error instanceof ApiError && error.estado === 401) {
      throw new Error(MENSAJES.sesionExpirada);
    }
    throw traducirErrorSesion(error);
  }
}
