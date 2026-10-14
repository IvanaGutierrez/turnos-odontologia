// Tipos del área admin C-11 (specs `admin/gestion-usuarios`,
// `admin/reportes-operativos`, `auditoria/registro-acciones`,
// `frontend/administracion`). Espejan los contratos del backend
// (`schemas/usuarios.py`, routers `usuarios`/`auditoria`/`reportes`):
// allowlist mínima, jamás PII/HC/hashes/tokens (R6). TS estricto, cero `any`.

export type RolStaff = "admin" | "odontologo" | "recepcion";

export const ROLES_STAFF: readonly RolStaff[] = ["admin", "odontologo", "recepcion"];

export function esRolStaff(valor: unknown): valor is RolStaff {
  return valor === "admin" || valor === "odontologo" || valor === "recepcion";
}

/** Salida pública de usuario (`UsuarioOut`): jamás `password_hash` (R6). */
export interface UsuarioAdmin {
  readonly id: string;
  readonly email: string;
  readonly rol: string;
  readonly activo: boolean;
}

export interface PaginaUsuarios {
  readonly items: readonly UsuarioAdmin[];
  readonly total: number;
  readonly page: number;
  readonly page_size: number;
}

export interface NuevoUsuario {
  readonly email: string;
  readonly rol: RolStaff;
  readonly password: string;
}

/** Fila de bitácora (`GET /auditoria`): `diff` ya sanitizado (R6). */
export interface EventoAuditoria {
  readonly id: string;
  readonly accion: string;
  readonly entidad: string;
  readonly entidad_id: string;
  readonly usuario_id: string | null;
  readonly hora: string;
}

export interface PaginaAuditoria {
  readonly items: readonly EventoAuditoria[];
  readonly total: number;
  readonly page: number;
  readonly page_size: number;
}

export interface FiltrosAuditoria {
  readonly entidad?: string;
  readonly entidad_id?: string;
  readonly accion?: string;
  readonly desde?: string;
  readonly hasta?: string;
  readonly page?: number;
  readonly page_size?: number;
}

export interface FilaOcupacion {
  readonly profesional_id?: string;
  readonly sillon_id?: string;
  readonly turnos_totales: number;
  readonly turnos_activos: number;
  readonly horas_ocupadas: number;
  readonly ocupacion_pct: number;
}

export interface Ocupacion {
  readonly por_profesional: readonly FilaOcupacion[];
  readonly por_sillon: readonly FilaOcupacion[];
}

export interface FilaAusentismo {
  readonly profesional_id: string;
  readonly turnos_finalizados: number;
  readonly ausentes: number;
  readonly ausentismo_pct: number;
}

export interface Ausentismo {
  readonly turnos_finalizados: number;
  readonly ausentes: number;
  readonly ausentismo_pct: number;
  readonly por_profesional: readonly FilaAusentismo[];
}

export interface Ingresos {
  readonly por_metodo: Readonly<Record<string, number>>;
  readonly total: number;
  readonly acreditado_mp: number;
  readonly diferencia: number;
}

export interface RangoFechas {
  readonly desde: string;
  readonly hasta: string;
}

export type TipoReporte = "ocupacion" | "ausentismo" | "ingresos";

function esRegistro(valor: unknown): valor is Record<string, unknown> {
  return typeof valor === "object" && valor !== null;
}

function aNumero(valor: unknown): number {
  return typeof valor === "number" && Number.isFinite(valor) ? valor : 0;
}

function aCadena(valor: unknown): string {
  return typeof valor === "string" ? valor : "";
}

function aBooleano(valor: unknown, porDefecto: boolean): boolean {
  return typeof valor === "boolean" ? valor : porDefecto;
}

export function esUsuarioAdmin(valor: unknown): valor is UsuarioAdmin {
  if (!esRegistro(valor)) return false;
  return (
    typeof valor["id"] === "string" &&
    typeof valor["email"] === "string" &&
    typeof valor["rol"] === "string" &&
    typeof valor["activo"] === "boolean"
  );
}

export function normalizarUsuario(valor: unknown): UsuarioAdmin | null {
  if (!esUsuarioAdmin(valor)) return null;
  return { id: valor.id, email: valor.email, rol: valor.rol, activo: valor.activo };
}

export function normalizarPaginaUsuarios(valor: unknown): PaginaUsuarios {
  if (!esRegistro(valor) || !Array.isArray(valor["items"])) {
    return { items: [], total: 0, page: 1, page_size: 20 };
  }
  const items: UsuarioAdmin[] = [];
  for (const crudo of valor["items"]) {
    const fila = normalizarUsuario(crudo);
    if (fila !== null) items.push(fila);
  }
  return {
    items,
    total: aNumero(valor["total"]),
    page: aNumero(valor["page"]) === 0 ? 1 : aNumero(valor["page"]),
    page_size: aNumero(valor["page_size"]) === 0 ? 20 : aNumero(valor["page_size"]),
  };
}

export function normalizarPaginaAuditoria(valor: unknown): PaginaAuditoria {
  if (!esRegistro(valor) || !Array.isArray(valor["items"])) {
    return { items: [], total: 0, page: 1, page_size: 20 };
  }
  const items: EventoAuditoria[] = [];
  for (const crudo of valor["items"]) {
    if (!esRegistro(crudo)) continue;
    const usuarioId: unknown = crudo["usuario_id"];
    const hora: unknown = crudo["hora"] ?? crudo["creado_en"];
    items.push({
      id: aCadena(crudo["id"]),
      accion: aCadena(crudo["accion"]),
      entidad: aCadena(crudo["entidad"]),
      entidad_id: aCadena(crudo["entidad_id"]),
      usuario_id: typeof usuarioId === "string" ? usuarioId : null,
      hora: typeof hora === "string" ? hora : "",
    });
  }
  const pagina = aNumero(valor["page"]);
  const tamano = aNumero(valor["page_size"]);
  return {
    items,
    total: aNumero(valor["total"]),
    page: pagina === 0 ? 1 : pagina,
    page_size: tamano === 0 ? 20 : tamano,
  };
}

function normalizarFilaOcupacion(valor: unknown): FilaOcupacion | null {
  if (!esRegistro(valor)) return null;
  const profesionalId: unknown = valor["profesional_id"];
  const sillonId: unknown = valor["sillon_id"];
  const fila: FilaOcupacion = {
    turnos_totales: aNumero(valor["turnos_totales"]),
    turnos_activos: aNumero(valor["turnos_activos"]),
    horas_ocupadas: aNumero(valor["horas_ocupadas"]),
    ocupacion_pct: aNumero(valor["ocupacion_pct"]),
  };
  if (typeof profesionalId === "string") {
    return { ...fila, profesional_id: profesionalId };
  }
  if (typeof sillonId === "string") {
    return { ...fila, sillon_id: sillonId };
  }
  return fila;
}

export function normalizarOcupacion(valor: unknown): Ocupacion {
  if (!esRegistro(valor)) return { por_profesional: [], por_sillon: [] };
  const porProfesional: FilaOcupacion[] = [];
  const porSillon: FilaOcupacion[] = [];
  if (Array.isArray(valor["por_profesional"])) {
    for (const crudo of valor["por_profesional"]) {
      const fila = normalizarFilaOcupacion(crudo);
      if (fila !== null) porProfesional.push(fila);
    }
  }
  if (Array.isArray(valor["por_sillon"])) {
    for (const crudo of valor["por_sillon"]) {
      const fila = normalizarFilaOcupacion(crudo);
      if (fila !== null) porSillon.push(fila);
    }
  }
  return { por_profesional: porProfesional, por_sillon: porSillon };
}

export function normalizarAusentismo(valor: unknown): Ausentismo {
  if (!esRegistro(valor)) {
    return { turnos_finalizados: 0, ausentes: 0, ausentismo_pct: 0, por_profesional: [] };
  }
  const filas: FilaAusentismo[] = [];
  if (Array.isArray(valor["por_profesional"])) {
    for (const crudo of valor["por_profesional"]) {
      if (!esRegistro(crudo)) continue;
      filas.push({
        profesional_id: aCadena(crudo["profesional_id"]),
        turnos_finalizados: aNumero(crudo["turnos_finalizados"]),
        ausentes: aNumero(crudo["ausentes"]),
        ausentismo_pct: aNumero(crudo["ausentismo_pct"]),
      });
    }
  }
  return {
    turnos_finalizados: aNumero(valor["turnos_finalizados"]),
    ausentes: aNumero(valor["ausentes"]),
    ausentismo_pct: aNumero(valor["ausentismo_pct"]),
    por_profesional: filas,
  };
}

export function normalizarIngresos(valor: unknown): Ingresos {
  if (!esRegistro(valor)) {
    return { por_metodo: {}, total: 0, acreditado_mp: 0, diferencia: 0 };
  }
  const metodos: Record<string, number> = {};
  if (esRegistro(valor["por_metodo"])) {
    for (const [metodo, monto] of Object.entries(valor["por_metodo"])) {
      metodos[metodo] = aNumero(monto);
    }
  }
  return {
    por_metodo: metodos,
    total: aNumero(valor["total"]),
    acreditado_mp: aNumero(valor["acreditado_mp"]),
    diferencia: aNumero(valor["diferencia"]),
    // Nota R6: solo montos agregados; jamás se leen DNI/tel/nombres/HC.
  };
}

/** `true` si el valor booleano/numérico indica fila activa. */
export function estaActivo(usuario: UsuarioAdmin): boolean {
  return aBooleano(usuario.activo, false);
}

// Agregados de ejemplo 100 % sintéticos (R0) para el primer render de
// `/admin/reportes` (patrón del repo: defaults ficticios que el fetch
// reemplaza con datos reales). Permiten operar la vista y la descarga CSV
// aunque la red falle; jamás PII/HC.
export const OCUPACION_EJEMPLO: Ocupacion = {
  por_profesional: [
    {
      profesional_id: "profesional-ficticio-0001",
      turnos_totales: 40,
      turnos_activos: 20,
      horas_ocupadas: 10,
      ocupacion_pct: 50,
    },
  ],
  por_sillon: [
    {
      sillon_id: "sillon-ficticio-0001",
      turnos_totales: 40,
      turnos_activos: 10,
      horas_ocupadas: 5,
      ocupacion_pct: 25,
    },
  ],
};

export const AUSENTISMO_EJEMPLO: Ausentismo = {
  turnos_finalizados: 90,
  ausentes: 9,
  ausentismo_pct: 10,
  por_profesional: [
    {
      profesional_id: "profesional-ficticio-0001",
      turnos_finalizados: 90,
      ausentes: 9,
      ausentismo_pct: 10,
    },
  ],
};

export const INGRESOS_EJEMPLO: Ingresos = {
  por_metodo: { efectivo: 10000, mercadopago: 8000, tarjeta: 0, transferencia: 0 },
  total: 18000,
  acreditado_mp: 8000,
  diferencia: 0,
};
