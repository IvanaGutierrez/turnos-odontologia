// Handlers MSW espejo del contrato OpenAPI del backend (solo lectura).
// Códigos y shapes copiados de los routers C-01…C-09; cuerpos sintéticos (R0).
// Base: VITE_API_URL en tests; misma familia para el worker de dev/E2E.

import { http, HttpResponse } from "msw";
import {
  ID_FICTICIOS,
  NO_ENCONTRADO_GENERICO,
  POLITICA_CANCELACION_FICTICIA,
  TOKEN_VALIDO,
  agendaDiaFicticia,
  linkPagoFicticio,
  slotsFicticios,
  turnoPropioFicticio,
  turnoPublicoFicticio,
} from "./fixtures";

// `*/…`: coincide con cualquier origen (el cliente usa VITE_API_URL absoluto).
const API = "*/api/v1";

export const ACCESS_FICTICIO = "access-ficticio-0001";
export const ACCESS_ROTADO_FICTICIO = "access-ficticio-rotado-0002";
export const ACCESS_ADMIN_FICTICIO = "access-admin-ficticio-0003";
export const ACCESS_ODONTOLOGO_FICTICIO = "access-odontologo-ficticio-0004";

// --- administración C-11: estado ficticio en memoria (R0, sin PII) ---
interface UsuarioFicticio {
  id: string;
  email: string;
  rol: string;
  activo: boolean;
}

const USUARIO_ADMIN_FICTICIO: UsuarioFicticio = {
  id: "90000000-0000-4000-8000-000000000001",
  email: "admin.ficticio@consultorio.example",
  rol: "admin",
  activo: true,
};

const USUARIO_NUEVO_C11: UsuarioFicticio = {
  id: "90000000-0000-4000-8000-000000000002",
  email: "nuevo.c11.ficticio@consultorio.example",
  rol: "recepcion",
  activo: true,
};

const USUARIO_ODONTO_FICTICIO: UsuarioFicticio = {
  id: "90000000-0000-4000-8000-000000000003",
  email: "odontologo.ficticio@consultorio.example",
  rol: "odontologo",
  activo: true,
};

// Un solo usuario activo en la lista inicial: los tests de `UsuariosPage`
// localizan un único botón "Desactivar" y un único "Inactiva" (el alta y la
// baja agregan/mutan filas en cada sesión del mock).
let usuariosFicticios: UsuarioFicticio[] = [USUARIO_NUEVO_C11];

let proximoUsuarioFicticio = 10;

interface EventoFicticio {
  id: string;
  accion: string;
  entidad: string;
  entidad_id: string;
  diff: Record<string, string>;
  usuario_id: string;
  ip: string | null;
  hora: string;
  creado_en: string;
}

const TURNO_C11 = "turno-ficticio-c11-0001";

const eventosFicticios: EventoFicticio[] = [
  {
    id: "91000000-0000-4000-8000-000000000001",
    accion: "turno_creado",
    entidad: "turno",
    entidad_id: TURNO_C11,
    diff: { estado: "reservado" },
    usuario_id: USUARIO_ADMIN_FICTICIO.id,
    ip: null,
    hora: "2026-11-02T09:00:00-03:00",
    creado_en: "2026-11-02T09:00:00-03:00",
  },
  {
    id: "91000000-0000-4000-8000-000000000002",
    accion: "turno_cancelado",
    entidad: "turno",
    entidad_id: TURNO_C11,
    diff: { estado: "cancelado" },
    usuario_id: USUARIO_ADMIN_FICTICIO.id,
    ip: null,
    hora: "2026-11-02T10:00:00-03:00",
    creado_en: "2026-11-02T10:00:00-03:00",
  },
  {
    id: "91000000-0000-4000-8000-000000000003",
    accion: "pago_acreditado",
    entidad: "pago",
    entidad_id: "pago-ficticio-c11-0001",
    diff: { estado: "acreditado" },
    usuario_id: USUARIO_ADMIN_FICTICIO.id,
    ip: null,
    hora: "2026-11-02T11:00:00-03:00",
    creado_en: "2026-11-02T11:00:00-03:00",
  },
  {
    id: "91000000-0000-4000-8000-000000000004",
    accion: "cierre_creado",
    entidad: "cierre",
    entidad_id: "cierre-ficticio-c11-0001",
    diff: { estado: "cerrado" },
    usuario_id: USUARIO_ADMIN_FICTICIO.id,
    ip: null,
    hora: "2026-11-02T12:00:00-03:00",
    creado_en: "2026-11-02T12:00:00-03:00",
  },
  {
    id: "91000000-0000-4000-8000-000000000005",
    accion: "evolucion_registrada",
    entidad: "ficha",
    entidad_id: "ficha-ficticia-c11-0001",
    diff: { estado: "registrada" },
    usuario_id: USUARIO_ODONTO_FICTICIO.id,
    ip: null,
    hora: "2026-11-02T13:00:00-03:00",
    creado_en: "2026-11-02T13:00:00-03:00",
  },
];

const OCUPACION_FICTICIA = {
  por_profesional: [
    {
      profesional_id: ID_FICTICIOS.profesionalA,
      turnos_totales: 40,
      turnos_activos: 20,
      horas_ocupadas: 10,
      ocupacion_pct: 50,
    },
  ],
  por_sillon: [
    {
      sillon_id: ID_FICTICIOS.sillon1,
      turnos_totales: 40,
      turnos_activos: 10,
      horas_ocupadas: 5,
      ocupacion_pct: 25,
    },
  ],
};

const AUSENTISMO_FICTICIO = {
  turnos_finalizados: 90,
  ausentes: 9,
  ausentismo_pct: 10,
  por_profesional: [
    {
      profesional_id: ID_FICTICIOS.profesionalA,
      turnos_finalizados: 90,
      ausentes: 9,
      ausentismo_pct: 10,
    },
  ],
};

const INGRESOS_FICTICIOS = {
  por_metodo: { efectivo: 10000, mercadopago: 8000, tarjeta: 0, transferencia: 0 },
  total: 18000,
  acreditado_mp: 8000,
  diferencia: 0,
};

const ROLES_VALIDOS = ["admin", "odontologo", "recepcion"] as const;

// Ocupación de slots creados en esta sesión del mock: el primer POST con un
// `inicio` gana (201) y los siguientes con el mismo `inicio` reciben el 409
// con alternativos, como un backend real ante reserva concurrente. Sin esto,
// el 409 solo era alcanzable con la clave mágica `clave-ocupada` y dos tests
// idénticos (éxito + 409 con el mismo slot) no podían pasar a la vez.
const iniciosOcupados = new Set<string>();

export const handlers = [
  // --- auth (C-02) ---
  http.post(`${API}/auth/login`, async ({ request }) => {
    const cuerpo = (await request.json()) as { email?: string };
    if (cuerpo.email === "bloqueada@consultorio.test") {
      return new HttpResponse(JSON.stringify({ detalle: "Demasiados intentos. Reintentá más tarde." }), {
        status: 429,
        headers: { "Retry-After": "60", "Content-Type": "application/json" },
      });
    }
    if (cuerpo.email === "recepcion@consultorio.test") {
      return HttpResponse.json({ access_token: ACCESS_FICTICIO }, { status: 200 });
    }
    if (cuerpo.email === "admin@consultorio.test") {
      return HttpResponse.json({ access_token: ACCESS_ADMIN_FICTICIO }, { status: 200 });
    }
    if (cuerpo.email === "odontologo@consultorio.test") {
      return HttpResponse.json({ access_token: ACCESS_ODONTOLOGO_FICTICIO }, { status: 200 });
    }
    return HttpResponse.json({ detalle: "Credenciales inválidas." }, { status: 401 });
  }),

  http.post(`${API}/auth/refresh`, ({ request }) => {
    const cookie = request.headers.get("cookie") ?? "";
    if (cookie.includes("refresh-valido-ficticio")) {
      return HttpResponse.json({ access_token: ACCESS_ROTADO_FICTICIO }, { status: 200 });
    }
    return HttpResponse.json({ detalle: "Sesión inválida." }, { status: 401 });
  }),

  http.post(`${API}/auth/logout`, () => {
    return HttpResponse.json({ detalle: "Sesión cerrada." }, { status: 200 });
  }),

  http.get(`${API}/auth/me`, ({ request }) => {
    const auth = request.headers.get("authorization") ?? "";
    if (auth === `Bearer ${ACCESS_FICTICIO}` || auth === `Bearer ${ACCESS_ROTADO_FICTICIO}`) {
      return HttpResponse.json(
        {
          id: "99999999-9999-4999-8999-999999999999",
          email: "recepcion@consultorio.test",
          roles: ["recepcion"],
          activo: true,
        },
        { status: 200 },
      );
    }
    if (auth === `Bearer ${ACCESS_ADMIN_FICTICIO}`) {
      return HttpResponse.json(
        {
          id: "99999999-9999-4999-8999-999999999998",
          email: "admin@consultorio.test",
          roles: ["admin"],
          activo: true,
        },
        { status: 200 },
      );
    }
    if (auth === `Bearer ${ACCESS_ODONTOLOGO_FICTICIO}`) {
      return HttpResponse.json(
        {
          id: "99999999-9999-4999-8999-999999999997",
          email: "odontologo@consultorio.test",
          roles: ["odontologo"],
          activo: true,
        },
        { status: 200 },
      );
    }
    return HttpResponse.json({ detalle: "Sesión inválida." }, { status: 401 });
  }),

  // --- administración C-11 (usuarios/auditoría/reportes, datos ficticios) ---
  http.get(`${API}/usuarios`, ({ request }) => {
    const url = new URL(request.url);
    const page = Number(url.searchParams.get("page") ?? "1");
    const pageSize = Number(url.searchParams.get("page_size") ?? "20");
    const inicio = (page - 1) * pageSize;
    return HttpResponse.json(
      {
        items: usuariosFicticios.slice(inicio, inicio + pageSize),
        total: usuariosFicticios.length,
        page,
        page_size: pageSize,
      },
      { status: 200 },
    );
  }),

  http.post(`${API}/usuarios`, async ({ request }) => {
    const cuerpo = (await request.json()) as { email?: unknown; rol?: unknown };
    const email = typeof cuerpo.email === "string" ? cuerpo.email : "";
    const rol = typeof cuerpo.rol === "string" ? cuerpo.rol : "";
    if (!(ROLES_VALIDOS as readonly string[]).includes(rol)) {
      return HttpResponse.json({ detalle: "Rol inválido." }, { status: 422 });
    }
    if (usuariosFicticios.some((u) => u.email === email)) {
      return HttpResponse.json({ detalle: "El email ya está registrado." }, { status: 409 });
    }
    proximoUsuarioFicticio += 1;
    const creado: UsuarioFicticio = {
      id: `90000000-0000-4000-8000-0000000000${String(proximoUsuarioFicticio)}`,
      email,
      rol,
      activo: true,
    };
    usuariosFicticios.push(creado);
    return HttpResponse.json(creado, { status: 201 });
  }),

  http.patch(`${API}/usuarios/:id`, async ({ params, request }) => {
    const fila = usuariosFicticios.find((u) => u.id === params["id"]);
    if (fila === undefined) {
      return HttpResponse.json({ detalle: "No se encontró el recurso solicitado." }, { status: 404 });
    }
    const cuerpo = (await request.json()) as { rol?: unknown; activo?: unknown };
    if (cuerpo.rol !== undefined) {
      if (typeof cuerpo.rol !== "string" || !(ROLES_VALIDOS as readonly string[]).includes(cuerpo.rol)) {
        return HttpResponse.json({ detalle: "Rol inválido." }, { status: 422 });
      }
      fila.rol = cuerpo.rol;
    }
    if (cuerpo.activo !== undefined && typeof cuerpo.activo === "boolean") {
      fila.activo = cuerpo.activo;
    }
    return HttpResponse.json({ ...fila }, { status: 200 });
  }),

  http.delete(`${API}/usuarios/:id`, ({ params }) => {
    const fila = usuariosFicticios.find((u) => u.id === params["id"]);
    if (fila === undefined) {
      return HttpResponse.json({ detalle: "No se encontró el recurso solicitado." }, { status: 404 });
    }
    fila.activo = false;
    return HttpResponse.json({ ...fila }, { status: 200 });
  }),

  http.get(`${API}/auditoria`, ({ request }) => {
    const url = new URL(request.url);
    const entidad = url.searchParams.get("entidad");
    const entidadId = url.searchParams.get("entidad_id");
    const accion = url.searchParams.get("accion");
    const page = Number(url.searchParams.get("page") ?? "1");
    const pageSize = Number(url.searchParams.get("page_size") ?? "20");
    const filtrados = eventosFicticios.filter((e) => {
      if (entidad !== null && entidad !== "" && e.entidad !== entidad) return false;
      if (entidadId !== null && entidadId !== "" && e.entidad_id !== entidadId) return false;
      if (accion !== null && accion !== "" && e.accion !== accion) return false;
      return true;
    });
    const inicio = (page - 1) * pageSize;
    return HttpResponse.json(
      {
        items: filtrados.slice(inicio, inicio + pageSize),
        total: filtrados.length,
        page,
        page_size: pageSize,
      },
      { status: 200 },
    );
  }),

  http.get(`${API}/reportes/ocupacion`, () => {
    return HttpResponse.json(OCUPACION_FICTICIA, { status: 200 });
  }),

  http.get(`${API}/reportes/ausentismo`, () => {
    return HttpResponse.json(AUSENTISMO_FICTICIO, { status: 200 });
  }),

  http.get(`${API}/reportes/ingresos`, () => {
    return HttpResponse.json(INGRESOS_FICTICIOS, { status: 200 });
  }),

  http.get(`${API}/reportes/ocupacion.csv`, ({ request }) => {
    const url = new URL(request.url);
    const desde = url.searchParams.get("desde") ?? "2026-11-01";
    const hasta = url.searchParams.get("hasta") ?? "2026-11-08";
    const lineas = [
      "periodo_desde,periodo_hasta,dimension,dimension_id,turnos_totales,turnos_activos,horas_ocupadas,ocupacion_pct",
      `${desde},${hasta},profesional,${ID_FICTICIOS.profesionalA},40,20,10,50`,
      `${desde},${hasta},sillon,${ID_FICTICIOS.sillon1},40,10,5,25`,
    ];
    return new HttpResponse(`\uFEFF${lineas.join("\n")}\n`, {
      status: 200,
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename=reporte-ocupacion-${desde}-${hasta}.csv`,
      },
    });
  }),

  http.get(`${API}/reportes/ausentismo.csv`, ({ request }) => {
    const url = new URL(request.url);
    const desde = url.searchParams.get("desde") ?? "2026-11-01";
    const hasta = url.searchParams.get("hasta") ?? "2026-11-08";
    const lineas = [
      "periodo_desde,periodo_hasta,profesional_id,turnos_finalizados,ausentes,ausentismo_pct",
      `${desde},${hasta},${ID_FICTICIOS.profesionalA},90,9,10`,
    ];
    return new HttpResponse(`\uFEFF${lineas.join("\n")}\n`, {
      status: 200,
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename=reporte-ausentismo-${desde}-${hasta}.csv`,
      },
    });
  }),

  http.get(`${API}/reportes/ingresos.csv`, ({ request }) => {
    const url = new URL(request.url);
    const desde = url.searchParams.get("desde") ?? "2026-11-01";
    const hasta = url.searchParams.get("hasta") ?? "2026-11-08";
    const lineas = [
      "periodo_desde,periodo_hasta,metodo,monto,total,acreditado_mp,diferencia",
      `${desde},${hasta},efectivo,10000,18000,8000,0`,
      `${desde},${hasta},mercadopago,8000,18000,8000,0`,
    ];
    return new HttpResponse(`\uFEFF${lineas.join("\n")}\n`, {
      status: 200,
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename=reporte-ingresos-${desde}-${hasta}.csv`,
      },
    });
  }),

  // --- disponibilidad pública (C-03) ---
  http.get(`${API}/disponibilidad`, ({ request }) => {
    const url = new URL(request.url);
    if (url.searchParams.get("profesional_id") === "inexistente") {
      return HttpResponse.json({ problema: "no_encontrado" }, { status: 404 });
    }
    return HttpResponse.json(slotsFicticios(), { status: 200 });
  }),

  // --- reserva pública (C-03) ---
  http.post(`${API}/turnos/publicos`, async ({ request }) => {
    const clave = request.headers.get("Idempotency-Key");
    if (clave === null || clave.trim() === "") {
      return HttpResponse.json(
        { problema: "validacion", detalle: "Falta el header Idempotency-Key." },
        { status: 422 },
      );
    }
    const cuerpo = (await request.json()) as { inicio?: string; fin?: string };
    const inicio = typeof cuerpo.inicio === "string" ? cuerpo.inicio : "";
    const ocupado =
      inicio !== "" &&
      (iniciosOcupados.has(inicio) ||
        (inicio === "2026-11-02T09:00:00-03:00" && clave === "clave-ocupada"));
    if (ocupado) {
      return HttpResponse.json(
        {
          problema: "slot_ocupado",
          detalle: "El horario ya fue reservado.",
          slots_alternativos: slotsFicticios().filter((s) => s.inicio !== inicio),
        },
        { status: 409 },
      );
    }
    if (inicio !== "") iniciosOcupados.add(inicio);
    const base = turnoPublicoFicticio();
    return HttpResponse.json(
      {
        ...base,
        inicio: inicio === "" ? base.inicio : inicio,
        fin: typeof cuerpo.fin === "string" && cuerpo.fin !== "" ? cuerpo.fin : base.fin,
      },
      { status: 201 },
    );
  }),

  // --- autogestión por token (C-05) ---
  http.get(`${API}/turnos/publicos/:token`, ({ params }) => {
    if (params["token"] !== TOKEN_VALIDO) {
      return HttpResponse.json(NO_ENCONTRADO_GENERICO, { status: 404 });
    }
    return HttpResponse.json(turnoPropioFicticio("reservado"), { status: 200 });
  }),

  http.post(`${API}/turnos/publicos/:token/confirmar`, ({ params }) => {
    if (params["token"] !== TOKEN_VALIDO) {
      return HttpResponse.json(NO_ENCONTRADO_GENERICO, { status: 404 });
    }
    return HttpResponse.json(turnoPropioFicticio("confirmado"), { status: 200 });
  }),

  http.post(`${API}/turnos/publicos/:token/cancelar`, ({ params, request }) => {
    if (params["token"] !== TOKEN_VALIDO) {
      return HttpResponse.json(NO_ENCONTRADO_GENERICO, { status: 404 });
    }
    const url = new URL(request.url);
    if (url.searchParams.get("fuera_de_termino") === "1") {
      return HttpResponse.json(
        {
          problema: "fuera_de_termino",
          detalle: POLITICA_CANCELACION_FICTICIA,
        },
        { status: 422 },
      );
    }
    return HttpResponse.json(turnoPropioFicticio("cancelado"), { status: 200 });
  }),

  http.post(`${API}/turnos/publicos/:token/reprogramar`, ({ params }) => {
    if (params["token"] !== TOKEN_VALIDO) {
      return HttpResponse.json(NO_ENCONTRADO_GENERICO, { status: 404 });
    }
    return HttpResponse.json(
      {
        id: "44444444-4444-4444-8444-444444444444",
        token_publico: TOKEN_VALIDO,
        estado: "reservado",
        inicio: "2026-11-02T09:30:00-03:00",
        fin: "2026-11-02T10:00:00-03:00",
      },
      { status: 201 },
    );
  }),

  // --- agenda operativa (C-04) ---
  // Nota de fidelidad: el backend exige JWT; el mock sirve sin `Authorization`
  // porque los flujos E2E/unit de C-10 abren `/agenda` sin login previo (la
  // app igual envía el header cuando hay sesión, y en producción sin sesión
  // la página redirige a `/login`). Solo capa mock, sin tocar la app.
  http.get(`${API}/agenda`, ({ request }) => {
    const url = new URL(request.url);
    if (url.searchParams.get("vista") === "semana" && url.searchParams.get("ventana") === "excesiva") {
      return HttpResponse.json(
        {
          problema: "validacion",
          detalle: "La ventana máxima es de 7 días. Volvé a la semana actual.",
        },
        { status: 422 },
      );
    }
    if (url.searchParams.get("dia") === "vacio") {
      return HttpResponse.json([], { status: 200 });
    }
    return HttpResponse.json(agendaDiaFicticia(), { status: 200 });
  }),

  // --- turnos staff (C-01/C-04, misma nota de fidelidad que `/agenda`) ---
  http.post(`${API}/turnos`, async ({ request }) => {
    const cuerpo = (await request.json()) as { inicio?: string };
    if (cuerpo.inicio === "2026-11-02T09:00:00-03:00") {
      return HttpResponse.json(
        {
          problema: "slot_ocupado",
          detalle: "El horario ya fue reservado.",
          slots_alternativos: slotsFicticios().slice(1),
        },
        { status: 409 },
      );
    }
    return HttpResponse.json({ ...turnoPublicoFicticio(), estado: "reservado" }, { status: 201 });
  }),

  http.post(`${API}/turnos/sobreturno`, async ({ request }) => {
    const rol = request.headers.get("x-rol-ficticio") ?? "recepcion";
    if (rol === "odontologo") {
      return HttpResponse.json({ detalle: "Acceso denegado." }, { status: 403 });
    }
    const cuerpo = (await request.json()) as { motivo_sobreturno?: string };
    if (!cuerpo.motivo_sobreturno || cuerpo.motivo_sobreturno.trim() === "") {
      return HttpResponse.json(
        { problema: "validacion", detalle: "El sobreturno exige motivo no vacío." },
        { status: 422 },
      );
    }
    return HttpResponse.json({ ...turnoPublicoFicticio(), sobreturno: true }, { status: 201 });
  }),

  http.post(`${API}/turnos/:id/confirmar`, () => {
    return HttpResponse.json({ ...turnoPublicoFicticio(), estado: "confirmado" }, { status: 200 });
  }),

  http.post(`${API}/turnos/:id/check-in`, () => {
    return HttpResponse.json({ ...turnoPublicoFicticio(), estado: "presente" }, { status: 200 });
  }),

  http.post(`${API}/turnos/:id/reprogramar`, () => {
    return HttpResponse.json(
      {
        id: "88888888-8888-4888-8888-888888888888",
        token_publico: TOKEN_VALIDO,
        estado: "reservado",
        inicio: "2026-11-02T09:30:00-03:00",
        fin: "2026-11-02T10:00:00-03:00",
      },
      { status: 201 },
    );
  }),

  // --- pago seña (C-08, fuera de /api/v1) ---
  http.get("*/pagar/:token", ({ params }) => {
    if (params["token"] !== TOKEN_VALIDO) {
      return HttpResponse.json(NO_ENCONTRADO_GENERICO, { status: 404 });
    }
    return HttpResponse.json(linkPagoFicticio(), { status: 200 });
  }),
];
