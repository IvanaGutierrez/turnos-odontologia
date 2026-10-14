// Tests en ROJO (parte 1 C-11) — `pages/admin/AuditoriaPage` (spec frontend/administracion).
// Verifican: filtros entidad/id/accion/rango + paginado, tabla {hora, usuario,
// accion, entidad, entidad_id} sin PII/HCE, errores 401/403/422 en espanol.
// Fixtures 100 % sinteticas (R0); la pagina aun no existe -> ROJO genuino.

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { AuditoriaPage } from "./AuditoriaPage";
import { establecerSesion } from "../../shared/auth/auth";

const TURNO_ID_FICTICIO = "turno-ficticio-c11-0001";
const DNI_FICTICIO = "90123456";
const TEL_FICTICIO = "+54 9 11 5000-0001";

function renderAuditoriaAdmin(): void {
  establecerSesion({ email: "admin.ficticio@consultorio.example", roles: ["admin"] });
  render(
    <MemoryRouter initialEntries={["/admin/auditoria"]}>
      <AuditoriaPage />
    </MemoryRouter>,
  );
}

describe("AuditoriaPage: filtros por entidad e id solo admin", () => {
  it("admin filtra por entidad=turno y un id, sin DNI ni telefonos", async () => {
    const usuario = userEvent.setup();
    renderAuditoriaAdmin();
    await usuario.selectOptions(screen.getByLabelText(/^entidad$/i), "turno");
    await usuario.type(screen.getByLabelText(/id de entidad/i), TURNO_ID_FICTICIO);
    await usuario.click(screen.getByRole("button", { name: /filtrar/i }));
    const tabla = await screen.findByRole("table");
    expect(tabla.textContent ?? "").toMatch(/turno_creado|turno_cancelado/i);
    expect(tabla.textContent ?? "").not.toMatch(new RegExp(DNI_FICTICIO));
    expect(document.body.textContent ?? "").not.toMatch(/5000-0001/);
    expect(document.body.textContent ?? "").not.toMatch(new RegExp(TEL_FICTICIO.replace("+", "\\+")));
  });

  it("pagina resultados con hora, usuario y accion sin columnas PII", async () => {
    const usuario = userEvent.setup();
    renderAuditoriaAdmin();
    await usuario.click(screen.getByRole("button", { name: /filtrar/i }));
    const tabla = await screen.findByRole("table");
    expect(tabla.textContent ?? "").toMatch(/hora|usuario|acci/i);
    expect(screen.queryByText(/dni/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/tel[eé]fono/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /siguiente/i })).toBeInTheDocument();
  });
});
