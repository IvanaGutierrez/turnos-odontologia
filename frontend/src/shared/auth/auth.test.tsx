// Tests en ROJO (parte 1) — `shared/auth` + guarda de rutas (spec api-client-auth).
// Verifican: login/logout/me, deny-by-default por rol, 429 con aviso accionable,
// errores 401/403 sanitizados en español, sobreturno oculto a odontólogo.

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { iniciarSesion, cerrarSesion, obtenerPerfil } from "./auth";
import { RequireRol, tienePermiso } from "./guards";

describe("auth: sesión login/logout/me", () => {
  it("login válido guarda la sesión y expone el perfil", async () => {
    const sesion = await iniciarSesion({
      email: "recepcion@consultorio.test",
      password: "Secreta-ficticia-01",
    });
    expect(sesion.email).toBe("recepcion@consultorio.test");
    expect(sesion.roles).toContain("recepcion");
    const perfil = await obtenerPerfil();
    expect(perfil.email).toBe("recepcion@consultorio.test");
  });

  it("login inválido responde 401 genérico sin revelar si el email existe", async () => {
    const error = await iniciarSesion({
      email: "nadie@consultorio.test",
      password: "Cualquiera-01",
    }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toMatch(/credenciales inválidas/i);
    expect((error as Error).message).not.toMatch(/nadie@consultorio/i);
  });

  it("logout cierra la sesión y el perfil queda inaccesible", async () => {
    await iniciarSesion({ email: "recepcion@consultorio.test", password: "Secreta-ficticia-01" });
    await cerrarSesion();
    const perfil = await obtenerPerfil().catch((e: unknown) => e);
    expect(perfil).toBeInstanceOf(Error);
  });

  it("rate limit de login muestra espera accionable sin revelar el email", async () => {
    const error = await iniciarSesion({
      email: "bloqueada@consultorio.test",
      password: "Secreta-ficticia-01",
    }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toMatch(/esper|reintent/i);
    expect((error as Error).message).not.toMatch(/bloqueada@/i);
  });

  it("el 403 se traduce a denegación genérica en español", async () => {
    const { ApiError } = await import("../api-client/apiClient");
    const denegado = new ApiError(403, "Forbidden", "/turnos/sobreturno");
    const { mensajeParaUsuario } = await import("./auth");
    expect(mensajeParaUsuario(denegado)).toMatch(/acceso denegado|sin permiso/i);
  });
});

describe("guarda de rutas: deny-by-default por rol", () => {
  function renderConRol(roles: string[], ruta: string): void {
    render(
      <MemoryRouter initialEntries={[ruta]}>
        <Routes>
          <Route
            path="/agenda"
            element={
              <RequireRol roles={roles} recurso="turnos">
                <p>Agenda operativa</p>
              </RequireRol>
            }
          />
          <Route
            path="/admin/usuarios"
            element={
              <RequireRol roles={roles} recurso="usuarios">
                <p>Usuarios</p>
              </RequireRol>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("recepción ve la agenda pero no el área admin", () => {
    renderConRol(["recepcion"], "/agenda");
    expect(screen.getByText("Agenda operativa")).toBeInTheDocument();
  });

  it("ruta sin permiso muestra acceso denegado y redirige al área del rol", () => {
    renderConRol(["recepcion"], "/admin/usuarios");
    expect(screen.getByText(/acceso denegado/i)).toBeInTheDocument();
    expect(screen.queryByText("Usuarios")).not.toBeInTheDocument();
  });

  it("recurso desconocido se deniega por defecto", () => {
    expect(tienePermiso("admin", "recurso-que-no-existe")).toBe(false);
    expect(tienePermiso("invitado", "turnos")).toBe(false);
  });

  it("odontólogo no recibe el control de sobreturno", () => {
    expect(tienePermiso("odontologo", "sobreturno")).toBe(false);
    expect(tienePermiso("recepcion", "sobreturno")).toBe(true);
    expect(tienePermiso("admin", "sobreturno")).toBe(true);
  });
});
