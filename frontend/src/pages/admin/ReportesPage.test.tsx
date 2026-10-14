// Tests en ROJO (parte 1 C-11) — `pages/admin/ReportesPage` + `features/admin/apiReportes`
// (spec frontend/administracion). Verifican: odontologo propios sin datos ajenos;
// descarga CSV admin con blob tipado; recepcion solo operativo dia sin CSV.
// Fixtures 100 % sinteticas (R0), TS estricto cero `any` (R4). Modulos aun no
// existen -> ROJO genuino.

import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ReportesPage } from "./ReportesPage";
import { descargarCsv } from "../../features/admin/apiReportes";
import { establecerSesion } from "../../shared/auth/auth";

afterEach(() => {
  vi.restoreAllMocks();
  establecerSesion(null);
});

function renderComo(roles: readonly string[]): void {
  establecerSesion({ email: "staff.ficticio@consultorio.example", roles: [...roles] });
  render(
    <MemoryRouter initialEntries={["/admin/reportes"]}>
      <ReportesPage />
    </MemoryRouter>,
  );
}

describe("ReportesPage: 3 vistas por rol y CSV tipado", () => {
  it("odontologo ve solo sus tarjetas sin selector ajeno ni CSV ajeno", async () => {
    renderComo(["odontologo"]);
    expect(await screen.findByText(/ocupaci/i)).toBeInTheDocument();
    expect(screen.getByText(/ausentismo/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/profesional/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /descargar.*ajeno|todos/i })).not.toBeInTheDocument();
  });

  it("admin descarga CSV de ocupacion con nombre y headers del contrato", async () => {
    const usuario = userEvent.setup();
    const crearObjetoUrl = vi.fn((): string => "blob:ficticio-0001");
    const revocarObjetoUrl = vi.fn((): void => undefined);
    vi.stubGlobal("URL", {
      createObjectURL: crearObjetoUrl,
      revokeObjectURL: revocarObjetoUrl,
    });
    const clicEnlace = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation((): void => undefined);
    renderComo(["admin"]);
    await usuario.click(await screen.findByRole("button", { name: /descargar ocupaci/i }));
    expect(typeof descargarCsv).toBe("function");
    expect(crearObjetoUrl).toHaveBeenCalledTimes(1);
    expect(clicEnlace.mock.calls.length).toBeGreaterThanOrEqual(1);
    const enlace = document.querySelector("a[download]") as HTMLAnchorElement | null;
    expect(enlace?.download).toMatch(/^reporte-ocupacion-.*-.*\.csv$/);
  });

  it("recepcion solo ve el operativo del dia sin rango ni descarga", async () => {
    renderComo(["recepcion"]);
    expect(await screen.findByText(/hoy/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/desde|hasta|rango/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /descargar/i })).not.toBeInTheDocument();
  });
});
