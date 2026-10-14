// Tests en ROJO (parte 1) — pago de seña con redirección MP (spec pago-sena-ui):
// resumen ARS + redirección única ante doble clic, pendiente/rechazado con
// reintento sin declarar confirmado, token inválido genérico.

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { PagarSena } from "./PagarSena";
import { TOKEN_VALIDO, TOKEN_INVALIDO, linkPagoFicticio } from "../../mocks/fixtures";

function renderPagar(token: string): void {
  render(
    <MemoryRouter initialEntries={[`/pagar/${token}`]}>
      <Routes>
        <Route path="/pagar/:token" element={<PagarSena />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("pago de seña con Mercado Pago", () => {
  it("muestra el resumen ARS y redirige a MP una sola vez ante doble clic", async () => {
    const usuario = userEvent.setup();
    const link = linkPagoFicticio();
    const redirigir = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...window.location, assign: redirigir },
      writable: true,
    });
    renderPagar(TOKEN_VALIDO);
    expect(await screen.findByText(/seña/i)).toBeInTheDocument();
    expect(screen.getByText(/\$ ?15\.000|15000.*ARS|ARS.*15000/i)).toBeInTheDocument();

    const pagar = screen.getByRole("button", { name: /pagar con mercado pago/i });
    await usuario.dblClick(pagar);
    expect(redirigir).toHaveBeenCalledTimes(1);
    expect(redirigir).toHaveBeenCalledWith(link.init_point);
    vi.restoreAllMocks();
  });

  it("pago pendiente muestra reintento sin declarar el turno confirmado", async () => {
    const usuario = userEvent.setup();
    renderPagar(`${TOKEN_VALIDO}?estado=pendiente`);
    expect(await screen.findByText(/pago pendiente/i)).toBeInTheDocument();
    expect(screen.getByText(/sigue reservado/i)).toBeInTheDocument();
    expect(screen.queryByText(/turno confirmado/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reintentar pago/i })).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: /reintentar pago/i }));
    expect(screen.queryByText(/turno confirmado/i)).not.toBeInTheDocument();
  });

  it("pago rechazado ofrece reintento manteniendo la reserva", async () => {
    renderPagar(`${TOKEN_VALIDO}?estado=rechazado`);
    expect(await screen.findByText(/pago rechazado/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reintentar pago/i })).toBeInTheDocument();
    expect(screen.queryByText(/turno confirmado/i)).not.toBeInTheDocument();
  });

  it("token inválido muestra no-encontrado genérico sin concepto ni monto", async () => {
    renderPagar(TOKEN_INVALIDO);
    expect(await screen.findByText(/no encontramos ese pago/i)).toBeInTheDocument();
    expect(screen.queryByText(/\$ ?15\.000/)).not.toBeInTheDocument();
    expect(screen.queryByText(/seña/i)).not.toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toMatch(new RegExp(TOKEN_INVALIDO));
  });
});
