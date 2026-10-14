// Navegación de la sección admin (SPA: conserva la sesión en memoria).
// Solo se monta tras la guarda `RequireRol`, así que jamás provoca fetches
// en roles denegados.

import { NavLink } from "react-router-dom";
import type { ReactElement } from "react";

export function AdminNav(): ReactElement {
  return (
    <nav aria-label="Sección administración">
      <ul>
        <li>
          <NavLink to="/admin/usuarios">Usuarios</NavLink>
        </li>
        <li>
          <NavLink to="/admin/auditoria">Auditoría</NavLink>
        </li>
        <li>
          <NavLink to="/admin/reportes">Reportes</NavLink>
        </li>
      </ul>
    </nav>
  );
}
