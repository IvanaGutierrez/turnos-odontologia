// Guarda de rutas deny-by-default, espejo de la matriz C-02
// (`backend/app/domain/auth/matriz.py` + `ROLES_SOBRETURNO` de `agenda.py`).
// Recurso desconocido o rol desconocido → denegado. La guarda refleja la
// matriz, no la redefine.

import type { ReactNode } from "react";
import { Link } from "react-router-dom";

const MATRIZ_PERMISOS: Record<string, readonly string[]> = {
  usuarios: ["admin"],
  configuracion_agenda: ["admin"],
  agenda_propia: ["admin", "odontologo"],
  turnos: ["admin", "odontologo", "recepcion"],
  pacientes: ["admin", "odontologo", "recepcion"],
  ficha_clinica: ["odontologo"],
  odontograma: ["odontologo"],
  evolucion: ["odontologo"],
  presupuesto: ["admin", "odontologo"],
  plan_tratamiento: ["admin", "odontologo"],
  caja: ["admin", "recepcion"],
  reapertura_caja: ["admin"],
  exportacion_datos: ["odontologo"],
  // Permiso fino de sobreturno (C-04): `odontologo` tiene `turnos` pero no este.
  sobreturno: ["recepcion", "admin"],
  // Administración C-11 (espejo de `domain/auth/matriz.py`): bitácora solo
  // admin; reportes agregados por rol; CSV sin recepción.
  auditoria: ["admin"],
  reportes: ["admin", "odontologo", "recepcion"],
  reportes_csv: ["admin", "odontologo"],
};

/** `true` si el rol opera el recurso; desconocidos → `false` (deny). */
export function tienePermiso(rol: string, recurso: string): boolean {
  const habilitados = MATRIZ_PERMISOS[recurso];
  if (habilitados === undefined) return false;
  return habilitados.includes(rol);
}

/** Área de aterrizaje según el primer rol de la sesión. */
export function areaPorRol(rol: string): string {
  if (rol === "admin") return "/admin/usuarios";
  if (rol === "odontologo" || rol === "recepcion") return "/agenda";
  return "/login";
}

export interface RequireRolProps {
  readonly roles: readonly string[];
  readonly recurso: string;
  readonly children: ReactNode;
}

/**
 * Guarda de ruta: sin permiso muestra acceso denegado genérico en español
 * (sin revelar si el recurso existe) con enlace al área del rol.
 */
export function RequireRol({ roles, recurso, children }: RequireRolProps): ReactNode {
  const permitido = roles.some((rol) => tienePermiso(rol, recurso));
  if (permitido) return <>{children}</>;
  const destino = areaPorRol(roles[0] ?? "");
  return (
    <section aria-label="Acceso denegado">
      <h1>Acceso denegado</h1>
      <p>No tenés permiso para ver esta sección.</p>
      <p>
        <Link to={destino}>Volver a tu área de trabajo</Link>
      </p>
    </section>
  );
}
