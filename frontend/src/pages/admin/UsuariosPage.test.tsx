// Tests en ROJO (parte 1 C-11) — `pages/admin/UsuariosPage` real (spec frontend/administracion).
// Verifican: recepcion denegada sin fetch; admin lista/pagina/crea; desactivacion
// con confirmacion sin hash/token. Datos 100 % sinteticos (R0), TS estricto (R4).

import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { UsuariosPage } from "./UsuariosPage";
import { establecerSesion } from "../../shared/auth/auth";

afterEach(() => {
  vi.restoreAllMocks();
  establecerSesion(null);
});

function renderComo(roles: readonly string[]): void {
  establecerSesion({ email: "staff.ficticio@consultorio.example", roles: [...roles] });
  render(
    <MemoryRouter initialEntries={["/admin/usuarios"]}>
      <UsuariosPage />
    </MemoryRouter>,
  );
}

describe("UsuariosPage: guardas y CRUD real", () => {
  it("recepcion ve denegado sin emitir fetch a /api/v1/usuarios", async () => {
    const espiaFetch = vi.spyOn(globalThis, "fetch");
    renderComo(["recepcion"]);
    expect(screen.getByText(/acceso denegado/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /volver a tu área/i })).toBeInTheDocument();
    const llamadasUsuarios = espiaFetch.mock.calls.filter(([url]) =>
      String(url).includes("/api/v1/usuarios"),
    );
    expect(llamadasUsuarios).toHaveLength(0);
  });

  it("admin ve la lista paginada con crear y cambiar rol", async () => {
    renderComo(["admin"]);
    expect(await screen.findByRole("heading", { name: /usuarios/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /crear usuario/i })).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText(/nuevo.c11.ficticio@consultorio.example/i)).toBeInTheDocument();
  });

  it("admin desactiva con confirmacion y sin exponer hash ni token", async () => {
    const usuario = userEvent.setup();
    renderComo(["admin"]);
    await usuario.click(await screen.findByRole("button", { name: /desactivar/i }));
    expect(screen.getByText(/confirmar desactivaci/i)).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: /sí, desactivar/i }));
    expect(await screen.findByText(/inactiva/i)).toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toMatch(/password_hash/i);
    expect(document.body.textContent ?? "").not.toMatch(/access_token/i);
  });
});
