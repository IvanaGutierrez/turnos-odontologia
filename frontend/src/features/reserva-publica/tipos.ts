// Tipos del dominio de reserva pública y autogestión (spec `reserva-publica-ui`,
// design decisión 8): `TurnoPropio` (ver-propio mínimo alcanzado por token)
// separado de `TurnoOperativo` (grilla operativa sin PII: sin DNI ni teléfono).
// Catálogos locales del MVP hasta que el backend exponga `/catalogos`.
// TS estricto, cero `any` (R4). Sin datos reales: valores por defecto
// sintéticos para el primer render (la `page` los reemplaza con la
// disponibilidad real vía `Promise.all`).

export interface SlotLibre {
  readonly inicio: string;
  readonly fin: string;
  readonly profesional_id: string;
  readonly prestacion_id: string;
}

export interface Prestacion {
  readonly id: string;
  readonly nombre: string;
  readonly duracionMin: number;
}

export interface Profesional {
  readonly id: string;
  readonly nombre: string;
}

/** Respuesta de `POST /turnos/publicos`: incluye el token para autogestionar. */
export interface TurnoPublicoCreado {
  readonly id: string;
  readonly profesional_id: string;
  readonly prestacion_id: string;
  readonly inicio: string;
  readonly fin: string;
  readonly estado: string;
  readonly canal: string;
  readonly token_publico: string;
  readonly url_pago: string | null;
}

/** Ver-propio mínimo de `GET /turnos/publicos/:token` (C-05): sin DNI ni tel. */
export interface TurnoPropio {
  readonly estado: string;
  readonly inicio: string;
  readonly fin: string;
  readonly prestacion_nombre: string;
  readonly profesional_nombre: string;
  readonly sede: string;
  readonly puede_cancelar_en_termino: boolean;
  readonly horas_limite: number;
  readonly estado_pago?: string | null;
  readonly url_pago?: string | null;
}

/**
 * Fila operativa de agenda (C-04): solo lo que el rol ve en grilla.
 * Separada de `TurnoPropio` a propósito — jamás lleva DNI, teléfono,
 * historia clínica ni tokens (R6).
 */
export interface TurnoOperativo {
  readonly id: string;
  readonly inicio: string;
  readonly fin: string;
  readonly estado: string;
  readonly profesional_id: string;
  readonly sillon_id: string | null;
  readonly prestacion_id: string;
  readonly sobreturno: boolean;
  readonly paciente_nombre: string | null;
}

/** Respuesta de `POST /turnos/publicos/:token/reprogramar` (mismo token). */
export interface ReprogramacionPropia {
  readonly id: string;
  readonly token_publico: string;
  readonly estado: string;
  readonly inicio: string;
  readonly fin: string;
}

export const CATALOGO_PRESTACIONES: readonly Prestacion[] = [
  { id: "10000000-0000-4000-8000-000000000001", nombre: "Limpieza", duracionMin: 30 },
  { id: "10000000-0000-4000-8000-000000000002", nombre: "Control", duracionMin: 20 },
  { id: "10000000-0000-4000-8000-000000000003", nombre: "Consulta de urgencia", duracionMin: 30 },
];

export const CATALOGO_PROFESIONALES: readonly Profesional[] = [
  { id: "20000000-0000-4000-8000-000000000001", nombre: "Dra. Ficticia A" },
  { id: "20000000-0000-4000-8000-000000000002", nombre: "Dr. Ficticio B" },
];

/** Primer render inmediato (la page lo reemplaza con disponibilidad real). */
export const SLOTS_INICIALES: readonly SlotLibre[] = [
  {
    inicio: "2026-11-02T09:00:00-03:00",
    fin: "2026-11-02T09:30:00-03:00",
    profesional_id: "20000000-0000-4000-8000-000000000001",
    prestacion_id: "10000000-0000-4000-8000-000000000001",
  },
  {
    inicio: "2026-11-02T09:30:00-03:00",
    fin: "2026-11-02T10:00:00-03:00",
    profesional_id: "20000000-0000-4000-8000-000000000001",
    prestacion_id: "10000000-0000-4000-8000-000000000001",
  },
  {
    inicio: "2026-11-02T10:00:00-03:00",
    fin: "2026-11-02T10:30:00-03:00",
    profesional_id: "20000000-0000-4000-8000-000000000002",
    prestacion_id: "10000000-0000-4000-8000-000000000001",
  },
];

const DIAS = [
  "domingo",
  "lunes",
  "martes",
  "miércoles",
  "jueves",
  "viernes",
  "sábado",
] as const;

const MESES = [
  "enero",
  "febrero",
  "marzo",
  "abril",
  "mayo",
  "junio",
  "julio",
  "agosto",
  "septiembre",
  "octubre",
  "noviembre",
  "diciembre",
] as const;

/**
 * "09:00": los ISO del contrato ya vienen en hora de consultorio (-03:00),
 * así que se muestra su hora mural sin depender de la ICU del entorno.
 */
export function formatearHora(iso: string): string {
  const coincidencia = /T(\d{2}):(\d{2})/.exec(iso);
  const hora = coincidencia?.[1];
  const minutos = coincidencia?.[2];
  if (hora === undefined || minutos === undefined) return iso;
  return `${hora}:${minutos}`;
}

/** "lunes 2 de noviembre" (cálculo UTC determinístico, sin ICU). */
export function formatearFecha(iso: string): string {
  const coincidencia = /(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  const anioTexto = coincidencia?.[1];
  const mesTexto = coincidencia?.[2];
  const diaTexto = coincidencia?.[3];
  if (anioTexto === undefined || mesTexto === undefined || diaTexto === undefined) return iso;
  const anio = Number(anioTexto);
  const mes = Number(mesTexto);
  const dia = Number(diaTexto);
  if (!Number.isInteger(anio) || !Number.isInteger(mes) || !Number.isInteger(dia)) return iso;
  if (mes < 1 || mes > 12 || dia < 1 || dia > 31) return iso;
  const fecha = new Date(Date.UTC(anio, mes - 1, dia));
  const diaSemana = DIAS[fecha.getUTCDay()] ?? "";
  const mesNombre = MESES[mes - 1] ?? "";
  return `${diaSemana} ${String(dia)} de ${mesNombre}`;
}

function aMinutos(hora: string, minutos: string): number | null {
  const h = Number(hora);
  const m = Number(minutos);
  if (!Number.isInteger(h) || !Number.isInteger(m)) return null;
  return h * 60 + m;
}

/**
 * "09:30 (30 min)": etiqueta corta con la hora de inicio, para que cada
 * horario matchee una sola opción (los rangos "09:00 – 09:30" duplican
 * coincidencias al buscar por hora).
 */
export function etiquetaSlotCorta(slot: SlotLibre): string {
  const hora = formatearHora(slot.inicio);
  const desde = aMinutosDeIso(slot.inicio);
  const hasta = aMinutosDeIso(slot.fin);
  if (desde === null || hasta === null || hasta <= desde) return hora;
  return `${hora} (${String(hasta - desde)} min)`;
}

function aMinutosDeIso(iso: string): number | null {
  const coincidencia = /T(\d{2}):(\d{2})/.exec(iso);
  const hora = coincidencia?.[1];
  const minutos = coincidencia?.[2];
  if (hora === undefined || minutos === undefined) return null;
  return aMinutos(hora, minutos);
}

export function nombrePrestacion(id: string): string {
  return CATALOGO_PRESTACIONES.find((p) => p.id === id)?.nombre ?? "Prestación";
}

export function nombreProfesional(id: string): string {
  const conocido = CATALOGO_PROFESIONALES.find((p) => p.id === id)?.nombre;
  if (conocido !== undefined) return conocido;
  return `Profesional ${id.slice(0, 8)}`;
}
