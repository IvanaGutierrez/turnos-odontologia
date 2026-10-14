// Tests en ROJO (parte 1) — autogestión con token (spec reserva-publica-ui):
// confirmar/cancelar/reprogramar, fuera de término con política, token inválido.

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { GestionarTurno } from "./GestionarTurno";
import { TOKEN_VALIDO, TOKEN_INVALIDO } from "../../mocks/fixtures";

function renderGestion(token: string): void {
  render(
    <MemoryRouter initialEntries={[`/gestionar/${token}`]}>
      <Routes>
        <Route path="/gestionar/:token" element={<GestionarTurno />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("autogestión con token", () => {
  it("confirma un turno reservado y refleja confirmado", async () => {
    const usuario = userEvent.setup();
    renderGestion(TOKEN_VALIDO);
    expect(await screen.findByText(/limpieza/i)).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: /confirmar turno/i }));
    expect(await screen.findByText(/turno confirmado/i)).toBeInTheDocument();
  });

  it("cancela en término y refleja cancelado con comprobante", async () => {
    const usuario = userEvent.setup();
    renderGestion(TOKEN_VALIDO);
    expect(await screen.findByText(/limpieza/i)).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: /cancelar turno/i }));
    await usuario.click(screen.getByRole("button", { name: /sí, cancelar/i }));
    expect(await screen.findByText(/turno cancelado/i)).toBeInTheDocument();
  });

  it("fuera de término muestra la política sin mutar el turno", async () => {
    const usuario = userEvent.setup();
    renderGestion(`${TOKEN_VALIDO}?fuera_de_termino=1`);
    expect(await screen.findByText(/limpieza/i)).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: /cancelar turno/i }));
    await usuario.click(screen.getByRole("button", { name: /sí, cancelar/i }));
    expect(await screen.findByText(/24 horas de antelación/i)).toBeInTheDocument();
    // El turno sigue visible y no cancelado.
    expect(screen.getByText(/limpieza/i)).toBeInTheDocument();
    expect(screen.queryByText(/turno cancelado/i)).not.toBeInTheDocument();
  });

  it("reprograma conservando el token público", async () => {
    const usuario = userEvent.setup();
    renderGestion(TOKEN_VALIDO);
    expect(await screen.findByText(/limpieza/i)).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: /reprogramar/i }));
    await usuario.click(screen.getByRole("radio", { name: /09:30/i }));
    await usuario.click(screen.getByRole("button", { name: /confirmar nuevo horario/i }));
    expect(await screen.findByText(/nuevo horario/i)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(TOKEN_VALIDO))).toBeInTheDocument();
  });

  it("token inválido muestra no-encontrado genérico sin datos ni token en consola", async () => {
    renderGestion(TOKEN_INVALIDO);
    expect(await screen.findByText(/no encontramos ese turno/i)).toBeInTheDocument();
    expect(screen.queryByText(/limpieza/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/dra\. ficticia/i)).not.toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toMatch(new RegExp(TOKEN_INVALIDO));
  });
});
