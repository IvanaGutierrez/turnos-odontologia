// Acceso a reportes operativos (C-11) desde `/admin/reportes`.
// - JSON agregado por rol (`reportes`): admin full / odontólogo propios /
//   recepción día operativo (el scoping lo impone el backend; acá solo viajan
//   los filtros).
// - CSV (`reportes_csv`, sin recepción): descarga del endpoint en streaming
//   como `Blob` tipado, o construcción local desde el JSON ya visible (mismos
//   headers del contrato, para que la descarga iguale la pantalla).
// Allowlist mínima, jamás PII/HC (R6). Cero `any` (R4).

import type { ParametrosConsulta } from "../../shared/api-client/apiClient";
import { clienteSesion } from "../../shared/auth/auth";
import type {
  Ausentismo,
  Ingresos,
  Ocupacion,
  RangoFechas,
  TipoReporte,
} from "./tipos";
import { normalizarAusentismo, normalizarIngresos, normalizarOcupacion } from "./tipos";

const cliente = clienteSesion();

export interface FiltrosReportes extends RangoFechas {
  readonly profesional_id?: string | undefined;
  readonly sillon_id?: string | undefined;
  readonly sede?: string | undefined;
}

function aParams(filtros: FiltrosReportes): ParametrosConsulta {
  const params: ParametrosConsulta = {
    desde: filtros.desde,
    hasta: filtros.hasta,
  };
  if (filtros.profesional_id !== undefined && filtros.profesional_id !== "") {
    params["profesional_id"] = filtros.profesional_id;
  }
  if (filtros.sillon_id !== undefined && filtros.sillon_id !== "") {
    params["sillon_id"] = filtros.sillon_id;
  }
  if (filtros.sede !== undefined && filtros.sede !== "") {
    params["sede"] = filtros.sede;
  }
  return params;
}

/** `GET /api/v1/reportes/ocupacion` (agregados por profesional y sillón). */
export async function obtenerOcupacion(filtros: FiltrosReportes): Promise<Ocupacion> {
  const respuesta = await cliente.get<unknown>("/reportes/ocupacion", aParams(filtros));
  return normalizarOcupacion(respuesta);
}

/** `GET /api/v1/reportes/ausentismo` (global + por profesional). */
export async function obtenerAusentismo(filtros: FiltrosReportes): Promise<Ausentismo> {
  const respuesta = await cliente.get<unknown>("/reportes/ausentismo", aParams(filtros));
  return normalizarAusentismo(respuesta);
}

/** `GET /api/v1/reportes/ingresos` (por método + conciliación MP). */
export async function obtenerIngresos(filtros: FiltrosReportes): Promise<Ingresos> {
  const respuesta = await cliente.get<unknown>("/reportes/ingresos", aParams(filtros));
  return normalizarIngresos(respuesta);
}

function aTextoCsv(valor: number | string): string {
  if (typeof valor === "number") {
    return Number.isInteger(valor) ? String(valor) : String(valor);
  }
  return valor;
}

/** Headers fijos del contrato (`routers/reportes.py`, separador `,`). */
export const CSV_HEADERS: Record<TipoReporte, string> = {
  ocupacion:
    "periodo_desde,periodo_hasta,dimension,dimension_id,turnos_totales,turnos_activos,horas_ocupadas,ocupacion_pct",
  ausentismo:
    "periodo_desde,periodo_hasta,profesional_id,turnos_finalizados,ausentes,ausentismo_pct",
  ingresos: "periodo_desde,periodo_hasta,metodo,monto,total,acreditado_mp,diferencia",
};

/** CSV de ocupación desde el JSON visible (iguala los números en pantalla). */
export function construirCsvOcupacion(rango: RangoFechas, datos: Ocupacion): string {
  const lineas: string[] = [CSV_HEADERS.ocupacion];
  for (const fila of datos.por_profesional) {
    lineas.push(
      [
        rango.desde,
        rango.hasta,
        "profesional",
        fila.profesional_id ?? "",
        aTextoCsv(fila.turnos_totales),
        aTextoCsv(fila.turnos_activos),
        aTextoCsv(fila.horas_ocupadas),
        aTextoCsv(fila.ocupacion_pct),
      ].join(","),
    );
  }
  for (const fila of datos.por_sillon) {
    lineas.push(
      [
        rango.desde,
        rango.hasta,
        "sillon",
        fila.sillon_id ?? "",
        aTextoCsv(fila.turnos_totales),
        aTextoCsv(fila.turnos_activos),
        aTextoCsv(fila.horas_ocupadas),
        aTextoCsv(fila.ocupacion_pct),
      ].join(","),
    );
  }
  return lineas.join("\n");
}

/** CSV de ausentismo desde el JSON visible. */
export function construirCsvAusentismo(rango: RangoFechas, datos: Ausentismo): string {
  const lineas: string[] = [CSV_HEADERS.ausentismo];
  for (const fila of datos.por_profesional) {
    lineas.push(
      [
        rango.desde,
        rango.hasta,
        fila.profesional_id,
        aTextoCsv(fila.turnos_finalizados),
        aTextoCsv(fila.ausentes),
        aTextoCsv(fila.ausentismo_pct),
      ].join(","),
    );
  }
  return lineas.join("\n");
}

/** CSV de ingresos desde el JSON visible (una fila por método). */
export function construirCsvIngresos(rango: RangoFechas, datos: Ingresos): string {
  const lineas: string[] = [CSV_HEADERS.ingresos];
  for (const metodo of Object.keys(datos.por_metodo).sort()) {
    const monto = datos.por_metodo[metodo] ?? 0;
    lineas.push(
      [
        rango.desde,
        rango.hasta,
        metodo,
        aTextoCsv(monto),
        aTextoCsv(datos.total),
        aTextoCsv(datos.acreditado_mp),
        aTextoCsv(datos.diferencia),
      ].join(","),
    );
  }
  return lineas.join("\n");
}

/** Nombre del contrato: `reporte-<tipo>-<desde>-<hasta>.csv`. */
export function nombreCsv(tipo: TipoReporte, rango: RangoFechas): string {
  return `reporte-${tipo}-${rango.desde}-${rango.hasta}.csv`;
}

/**
 * `GET /api/v1/reportes/:tipo.csv` (admin full, odontólogo propio;
 * recepción → 403). Descarga el CSV del servidor como `Blob` con BOM
 * (Excel AR). La página usa los constructores locales para una descarga
 * inmediata e igual a la pantalla; este helper queda como API tipada del
 * endpoint en streaming.
 */
export async function descargarCsv(
  tipo: TipoReporte,
  filtros: FiltrosReportes,
): Promise<{ readonly blob: Blob; readonly nombre: string }> {
  const params = aParams(filtros);
  const consulta = new URLSearchParams(params).toString();
  const base: unknown = import.meta.env.VITE_API_URL;
  const origen = typeof base === "string" && base.length > 0 ? base : "http://localhost:8000/api/v1";
  const respuesta = await fetch(`${origen}/reportes/${tipo}.csv?${consulta}`, {
    credentials: "include",
  });
  if (!respuesta.ok) throw new Error("No se pudo descargar el reporte.");
  const blob = await respuesta.blob();
  return { blob, nombre: nombreCsv(tipo, filtros) };
}
