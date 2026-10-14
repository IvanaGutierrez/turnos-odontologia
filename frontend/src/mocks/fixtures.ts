// Fixtures 100 % sintéticas (R0): pacientes, profesionales y turnos ficticios.
// Jamás datos reales. Espejan los shapes de los routers C-01…C-09.

export interface SlotLibre {
  inicio: string;
  fin: string;
  profesional_id: string;
  prestacion_id: string;
}

export interface TurnoPublicoCreado {
  id: string;
  profesional_id: string;
  prestacion_id: string;
  inicio: string;
  fin: string;
  estado: string;
  canal: string;
  token_publico: string;
  url_pago: string | null;
}

export interface TurnoPropio {
  estado: string;
  inicio: string;
  fin: string;
  prestacion_nombre: string;
  profesional_nombre: string;
  sede: string;
  puede_cancelar_en_termino: boolean;
  horas_limite: number;
  estado_pago?: string | null;
  url_pago?: string | null;
}

export interface AgendaItemMock {
  id: string;
  inicio: string;
  fin: string;
  estado: string;
  profesional_id: string;
  sillon_id: string | null;
  prestacion_id: string;
  sobreturno: boolean;
  paciente_nombre: string | null;
}

export interface LinkPagoMock {
  init_point: string;
  monto: number;
  moneda: "ARS";
  estado_pago: string;
}

const PROFESIONAL_A = "11111111-1111-4111-8111-111111111111";
const PROFESIONAL_B = "22222222-2222-4222-8222-222222222222";
const PROFESIONAL_C = "33333333-3333-4333-8333-333333333333";
const SILLON_1 = "a1a1a1a1-a1a1-4a1a-8a1a-a1a1a1a1a1a1";
const SILLON_2 = "b2b2b2b2-b2b2-4b2b-8b2b-b2b2b2b2b2b2";
const PRESTACION_LIMPIEZA = "c3c3c3c3-c3c3-4c3c-8c3c-c3c3c3c3c3c3";

export const ID_FICTICIOS = {
  profesionalA: PROFESIONAL_A,
  profesionalB: PROFESIONAL_B,
  profesionalC: PROFESIONAL_C,
  sillon1: SILLON_1,
  sillon2: SILLON_2,
  prestacionLimpieza: PRESTACION_LIMPIEZA,
} as const;

// DNI y teléfono ficticios con formato AR válido (solo para tests).
export const PACIENTE_FICTICIO = {
  nombre: "Paciente Ficticia Uno",
  dni: "28000001",
  telefono: "+54 9 11 5000-0001",
} as const;

export const TOKEN_VALIDO = "token-publico-ficticio-0001";
export const TOKEN_INVALIDO = "token-inexistente-0000";

export function slotsFicticios(): SlotLibre[] {
  return [
    {
      inicio: "2026-11-02T09:00:00-03:00",
      fin: "2026-11-02T09:30:00-03:00",
      profesional_id: PROFESIONAL_A,
      prestacion_id: PRESTACION_LIMPIEZA,
    },
    {
      inicio: "2026-11-02T09:30:00-03:00",
      fin: "2026-11-02T10:00:00-03:00",
      profesional_id: PROFESIONAL_A,
      prestacion_id: PRESTACION_LIMPIEZA,
    },
    {
      inicio: "2026-11-02T10:00:00-03:00",
      fin: "2026-11-02T10:30:00-03:00",
      profesional_id: PROFESIONAL_B,
      prestacion_id: PRESTACION_LIMPIEZA,
    },
  ];
}

export function turnoPublicoFicticio(): TurnoPublicoCreado {
  return {
    id: "44444444-4444-4444-8444-444444444444",
    profesional_id: PROFESIONAL_A,
    prestacion_id: PRESTACION_LIMPIEZA,
    inicio: "2026-11-02T09:00:00-03:00",
    fin: "2026-11-02T09:30:00-03:00",
    estado: "reservado",
    canal: "online",
    token_publico: TOKEN_VALIDO,
    url_pago: null,
  };
}

export function turnoPropioFicticio(estado = "reservado"): TurnoPropio {
  return {
    estado,
    inicio: "2026-11-02T09:00:00-03:00",
    fin: "2026-11-02T09:30:00-03:00",
    prestacion_nombre: "Limpieza",
    profesional_nombre: "Dra. Ficticia A",
    sede: "Consultorio",
    puede_cancelar_en_termino: true,
    horas_limite: 24,
    estado_pago: null,
    url_pago: null,
  };
}

export function agendaDiaFicticia(): AgendaItemMock[] {
  return [
    {
      id: "55555555-5555-4555-8555-555555555555",
      inicio: "2026-11-02T09:00:00-03:00",
      fin: "2026-11-02T09:30:00-03:00",
      estado: "reservado",
      profesional_id: PROFESIONAL_A,
      sillon_id: SILLON_1,
      prestacion_id: PRESTACION_LIMPIEZA,
      sobreturno: false,
      paciente_nombre: "Paciente Ficticia Uno",
    },
    {
      id: "66666666-6666-4666-8666-666666666666",
      inicio: "2026-11-02T09:00:00-03:00",
      fin: "2026-11-02T09:30:00-03:00",
      estado: "confirmado",
      profesional_id: PROFESIONAL_B,
      sillon_id: SILLON_2,
      prestacion_id: PRESTACION_LIMPIEZA,
      sobreturno: false,
      paciente_nombre: "Paciente Ficticio Dos",
    },
    {
      id: "77777777-7777-4777-8777-777777777777",
      inicio: "2026-11-02T09:30:00-03:00",
      fin: "2026-11-02T10:00:00-03:00",
      estado: "reservado",
      profesional_id: PROFESIONAL_C,
      sillon_id: SILLON_1,
      prestacion_id: PRESTACION_LIMPIEZA,
      sobreturno: false,
      paciente_nombre: "Paciente Ficticia Tres",
    },
  ];
}

export function linkPagoFicticio(): LinkPagoMock {
  return {
    init_point: "https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=ficticio-0001",
    monto: 15000,
    moneda: "ARS",
    estado_pago: "pendiente",
  };
}

export const NO_ENCONTRADO_GENERICO = {
  problema: "no_encontrado",
  detalle: "No se encontró el recurso solicitado.",
} as const;

export const POLITICA_CANCELACION_FICTICIA =
  "La cancelación requiere 24 horas de antelación. Comunicate con el consultorio para reprogramar.";
