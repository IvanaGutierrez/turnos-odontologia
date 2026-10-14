// Cliente HTTP tipado contra `/api/v1` (spec `api-client-auth`, design 2).
// - Base solo desde `VITE_API_URL`; access token solo en memoria (nunca
//   `localStorage`).
// - Ante `401`: una sola rotación de refresh en vuelo aunque haya N requests
//   concurrentes; si el refresh falla, cierra la sesión local.
// - Idempotencia configurable por request (`Idempotency-Key`).
// - Reintento limitado ante red/`5xx` solo en lecturas o envíos idempotentes;
//   los logs llevan método + estado + mensaje sanitizado, jamás cuerpos,
//   headers, tokens ni rutas con PII (R6).

import { MENSAJES } from "../i18n/es-AR";
import { sanitizarError } from "./sanitize";

export interface OpcionesCliente {
  readonly baseUrl?: string;
}

export interface OpcionesEnvio {
  readonly idempotencia?: string;
  readonly reintentos?: number;
}

export type ParametrosConsulta = Record<string, string>;

/** Error operativo con mensaje genérico en español, sin PII. */
export class ApiError<TDetalle = unknown> extends Error {
  readonly estado: number;
  readonly mensaje: string;
  readonly recurso: string;
  readonly codigo: string | undefined;
  readonly datos: TDetalle | undefined;

  constructor(estado: number, mensaje: string, recurso: string, codigo?: string, datos?: TDetalle) {
    super(mensaje);
    this.name = "ApiError";
    this.estado = estado;
    this.mensaje = mensaje;
    this.recurso = recurso;
    this.codigo = codigo;
    this.datos = datos;
  }
}

export interface ClienteApi {
  get<T>(ruta: string, params?: ParametrosConsulta, opciones?: OpcionesEnvio): Promise<T>;
  post<T>(ruta: string, cuerpo?: unknown, opciones?: OpcionesEnvio): Promise<T>;
  patch<T>(ruta: string, cuerpo?: unknown, opciones?: OpcionesEnvio): Promise<T>;
  del<T>(ruta: string, opciones?: OpcionesEnvio): Promise<T>;
  establecerAccess(token: string): void;
  limpiarAccess(): void;
  accessActual(): string | null;
}

const RUTA_REFRESH = "/auth/refresh";

function baseUrlPorDefecto(): string {
  const deEntorno: unknown = import.meta.env.VITE_API_URL;
  if (typeof deEntorno === "string" && deEntorno.length > 0) return deEntorno;
  return "http://localhost:8000/api/v1";
}

function esObjetoRegistro(valor: unknown): valor is Record<string, unknown> {
  return typeof valor === "object" && valor !== null;
}

export function crearClienteApi(opciones?: OpcionesCliente): ClienteApi {
  const base = (opciones?.baseUrl ?? baseUrlPorDefecto()).replace(/\/+$/, "");
  let access: string | null = null;
  let renovacionEnVuelo: Promise<string> | null = null;

  function construirUrl(ruta: string, params?: ParametrosConsulta): string {
    const normalizada = ruta.startsWith("/") ? ruta : `/${ruta}`;
    if (params === undefined) return `${base}${normalizada}`;
    const consulta = new URLSearchParams(params).toString();
    return consulta.length > 0 ? `${base}${normalizada}?${consulta}` : `${base}${normalizada}`;
  }

  function construirHeaders(idempotencia: string | undefined, conCuerpo: boolean): Headers {
    const cabeceras = new Headers();
    cabeceras.set("Accept", "application/json");
    if (conCuerpo) cabeceras.set("Content-Type", "application/json");
    if (access !== null) cabeceras.set("Authorization", `Bearer ${access}`);
    if (idempotencia !== undefined && idempotencia.length > 0) {
      cabeceras.set("Idempotency-Key", idempotencia);
    }
    return cabeceras;
  }

  function registrarFallo(metodo: string, estado: number, mensaje: string): void {
    const causa = estado > 0 ? `HTTP ${String(estado)}` : "red";
    console.error("[api]", metodo, causa, sanitizarError(mensaje));
  }

  async function leerCuerpo(respuesta: Response): Promise<unknown> {
    const texto = await respuesta.text().catch(() => "");
    if (texto.length === 0) return null;
    try {
      return JSON.parse(texto) as unknown;
    } catch {
      return texto;
    }
  }

  function mensajeSegunEstado(estado: number): string {
    if (estado === 401) return MENSAJES.sesionExpirada;
    if (estado === 403) return MENSAJES.accesoDenegado;
    if (estado === 404) return MENSAJES.noEncontrado;
    if (estado === 409) return MENSAJES.slotOcupado;
    if (estado === 422) return MENSAJES.datosInvalidos;
    if (estado === 429) return MENSAJES.esperaRateLimit;
    if (estado >= 500) return MENSAJES.errorServidor;
    return MENSAJES.errorInesperado;
  }

  /** Una sola renovación en vuelo; ante fallo, cierra la sesión local. */
  async function renovar(): Promise<string> {
    const enVuelo = renovacionEnVuelo;
    if (enVuelo !== null) return enVuelo;
    const promesa = (async (): Promise<string> => {
      let respuesta: Response;
      try {
        respuesta = await fetch(`${base}${RUTA_REFRESH}`, { method: "POST", credentials: "include" });
      } catch {
        access = null;
        registrarFallo("POST", 0, MENSAJES.errorRed);
        throw new ApiError(0, MENSAJES.errorRed, RUTA_REFRESH);
      }
      if (!respuesta.ok) {
        access = null;
        registrarFallo("POST", respuesta.status, MENSAJES.sesionExpirada);
        throw new ApiError(respuesta.status, MENSAJES.sesionExpirada, RUTA_REFRESH);
      }
      const cuerpo: unknown = await leerCuerpo(respuesta);
      const token = esObjetoRegistro(cuerpo) ? cuerpo["access_token"] : undefined;
      if (typeof token !== "string" || token.length === 0) {
        access = null;
        throw new ApiError(401, MENSAJES.sesionExpirada, RUTA_REFRESH);
      }
      access = token;
      return token;
    })();
    renovacionEnVuelo = promesa;
    try {
      return await promesa;
    } finally {
      renovacionEnVuelo = null;
    }
  }

  async function solicitar<T>(
    metodo: "GET" | "POST" | "PATCH" | "DELETE",
    ruta: string,
    cuerpo?: unknown,
    params?: ParametrosConsulta,
    opciones?: OpcionesEnvio,
  ): Promise<T> {
    const pedidos = opciones?.reintentos;
    const maxReintentos = pedidos ?? (metodo === "GET" ? 1 : 0);
    const clave = opciones?.idempotencia;
    // Reintentar un POST no idempotente duplicaría el efecto: prohibido.
    const permiteReintento = metodo === "GET" || (clave !== undefined && clave.length > 0);
    const limite = permiteReintento ? maxReintentos : 0;
    let sesionReintentada = false;
    let intento = 0;
    for (;;) {
      intento += 1;
      let respuesta: Response;
      try {
        const init: RequestInit = {
          method: metodo,
          credentials: "include",
          headers: construirHeaders(clave, cuerpo !== undefined),
        };
        if (cuerpo !== undefined) init.body = JSON.stringify(cuerpo);
        respuesta = await fetch(construirUrl(ruta, params), init);
      } catch {
        if (intento <= limite) continue;
        registrarFallo(metodo, 0, MENSAJES.errorRed);
        throw new ApiError(0, MENSAJES.errorRed, sanitizarError(ruta));
      }
      if (respuesta.ok) {
        if (respuesta.status === 204) return undefined as unknown as T;
        const datos = await leerCuerpo(respuesta);
        return datos as T;
      }
      if (respuesta.status === 401 && ruta !== RUTA_REFRESH && !sesionReintentada) {
        sesionReintentada = true;
        await renovar();
        continue;
      }
      if (respuesta.status >= 500 && intento <= limite) continue;
      const cuerpoError = await leerCuerpo(respuesta);
      const problema =
        esObjetoRegistro(cuerpoError) && typeof cuerpoError["problema"] === "string"
          ? (cuerpoError["problema"])
          : undefined;
      const mensaje = mensajeSegunEstado(respuesta.status);
      registrarFallo(metodo, respuesta.status, mensaje);
      throw new ApiError(respuesta.status, mensaje, sanitizarError(ruta), problema, cuerpoError);
    }
  }

  return {
    get<T>(ruta: string, params?: ParametrosConsulta, opciones?: OpcionesEnvio): Promise<T> {
      return solicitar<T>("GET", ruta, undefined, params, opciones);
    },
    post<T>(ruta: string, cuerpo?: unknown, opciones?: OpcionesEnvio): Promise<T> {
      return solicitar<T>("POST", ruta, cuerpo, undefined, opciones);
    },
    patch<T>(ruta: string, cuerpo?: unknown, opciones?: OpcionesEnvio): Promise<T> {
      return solicitar<T>("PATCH", ruta, cuerpo, undefined, opciones);
    },
    del<T>(ruta: string, opciones?: OpcionesEnvio): Promise<T> {
      return solicitar<T>("DELETE", ruta, undefined, undefined, opciones);
    },
    establecerAccess(token: string): void {
      access = token;
    },
    limpiarAccess(): void {
      access = null;
    },
    accessActual(): string | null {
      return access;
    },
  };
}
