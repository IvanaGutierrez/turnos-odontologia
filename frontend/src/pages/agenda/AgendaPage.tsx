// Ruta `/agenda`: agenda operativa con guarda por rol `turnos`
// (deny-by-default, espejo C-02). Sin sesión en desarrollo se asume el rol
// de recepción para operar con fixtures MSW; en producción sin sesión se
// pide iniciar sesión. Copy en español, cero `any` (R4).

import { Link } from "react-router-dom";
import type { ReactElement } from "react";
import { tienePermiso, RequireRol } from "../../shared/auth/guards";
import { obtenerSesion } from "../../shared/auth/auth";
import { AgendaDia } from "../../features/agenda/AgendaDia";

function rolesSesion(): readonly string[] {
  const sesion = obtenerSesion();
  if (sesion !== null) return sesion.roles;
  if (import.meta.env.DEV) return ["recepcion"];
  return [];
}

export function AgendaPage(): ReactElement {
  const roles = rolesSesion();
  if (roles.length === 0) {
    return (
      <main>
        <h1>Agenda operativa</h1>
        <p>Sesión inválida. Iniciá sesión nuevamente.</p>
        <p>
          <Link to="/login">Iniciar sesión</Link>
        </p>
      </main>
    );
  }
  const veReportes = roles.some((rol) => tienePermiso(rol, "reportes"));
  return (
    <main>
      <h1>Agenda operativa</h1>
      {veReportes ? (
        <p>
          <Link to="/admin/reportes">Reportes</Link>
        </p>
      ) : null}
      <RequireRol roles={roles} recurso="turnos">
        <AgendaDia roles={roles} />
      </RequireRol>
    </main>
  );
}
