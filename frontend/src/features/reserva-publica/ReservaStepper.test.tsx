// Tests en ROJO (parte 1) — stepper de reserva pública 3 taps
// (spec reserva-publica-ui): motivo→slot→DNI+tel, doble envío idempotente,
// 409 con alternativos conservando datos, validación AR por campo sin envío.

import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ReservaStepper } from "./ReservaStepper";

function renderStepper(): void {
  render(
    <MemoryRouter initialEntries={["/reservar/consultorio"]}>
      <ReservaStepper slug="consultorio" />
    </MemoryRouter>,
  );
}

describe("reserva pública: 3 taps", () => {
  it("guía motivo→slot→DNI+tel y confirma con token público", async () => {
    const usuario = userEvent.setup();
    renderStepper();
    expect(screen.getByRole("heading", { name: /paso 1.*motivo/i })).toBeInTheDocument();

    await usuario.click(screen.getByRole("radio", { name: /limpieza/i }));
    await usuario.click(screen.getByRole("button", { name: /continuar/i }));
    expect(screen.getByRole("heading", { name: /paso 2.*horario/i })).toBeInTheDocument();

    await usuario.click(screen.getByRole("radio", { name: /09:00/i }));
    await usuario.click(screen.getByRole("button", { name: /continuar/i }));
    expect(screen.getByRole("heading", { name: /paso 3.*datos/i })).toBeInTheDocument();

    await usuario.type(screen.getByLabelText(/dni/i), "28000001");
    await usuario.type(screen.getByLabelText(/teléfono/i), "+54 9 11 5000-0001");
    await usuario.click(screen.getByRole("button", { name: /confirmar reserva/i }));

    expect(await screen.findByText(/turno reservado/i)).toBeInTheDocument();
    expect(screen.getByText(/token-publico-ficticio-0001/)).toBeInTheDocument();
  });

  it("el doble envío usa un solo token de idempotencia y crea un único turno", async () => {
    const usuario = userEvent.setup();
    const fetchEspia = vi.spyOn(window, "fetch");
    renderStepper();
    await usuario.click(screen.getByRole("radio", { name: /limpieza/i }));
    await usuario.click(screen.getByRole("button", { name: /continuar/i }));
    await usuario.click(screen.getByRole("radio", { name: /09:30/i }));
    await usuario.click(screen.getByRole("button", { name: /continuar/i }));
    await usuario.type(screen.getByLabelText(/dni/i), "28000001");
    await usuario.type(screen.getByLabelText(/teléfono/i), "+54 9 11 5000-0001");
    const confirmar = screen.getByRole("button", { name: /confirmar reserva/i });
    await usuario.dblClick(confirmar);
    expect(await screen.findByText(/turno reservado/i)).toBeInTheDocument();
    const posts = fetchEspia.mock.calls.filter(([url]) => String(url).includes("/turnos/publicos"));
    const claves = new Set(
      posts.map(([, init]) => (init as RequestInit | undefined)?.headers),
    );
    expect(posts.length).toBeGreaterThan(0);
    expect(claves.size).toBe(1);
    expect(screen.getAllByText(/turno reservado/i)).toHaveLength(1);
    fetchEspia.mockRestore();
  });

  it("ante 409 ofrece alternativos sin perder los datos ingresados", async () => {
    const usuario = userEvent.setup();
    renderStepper();
    await usuario.click(screen.getByRole("radio", { name: /limpieza/i }));
    await usuario.click(screen.getByRole("button", { name: /continuar/i }));
    // Slot ocupado en el mock concurrente.
    await usuario.click(screen.getByRole("radio", { name: /09:00/i }));
    await usuario.click(screen.getByRole("button", { name: /continuar/i }));
    await usuario.type(screen.getByLabelText(/dni/i), "28000001");
    await usuario.type(screen.getByLabelText(/teléfono/i), "+54 9 11 5000-0001");
    await usuario.click(screen.getByRole("button", { name: /confirmar reserva/i }));

    expect(await screen.findByText(/horario ocupado/i)).toBeInTheDocument();
    const dialogo = screen.getByRole("dialog", { name: /horarios alternativos/i });
    expect(within(dialogo).getByRole("radio", { name: /09:30/i })).toBeInTheDocument();
    // Los datos se conservan.
    expect(screen.getByLabelText(/dni/i)).toHaveValue("28000001");
    expect(screen.getByLabelText(/teléfono/i)).toHaveValue("+54 9 11 5000-0001");
  });

  it("DNI o teléfono inválidos bloquean el envío con aviso por campo", async () => {
    const usuario = userEvent.setup();
    const fetchEspia = vi.spyOn(window, "fetch");
    const consola = vi.spyOn(console, "error").mockImplementation(() => undefined);
    renderStepper();
    await usuario.click(screen.getByRole("radio", { name: /limpieza/i }));
    await usuario.click(screen.getByRole("button", { name: /continuar/i }));
    await usuario.click(screen.getByRole("radio", { name: /09:00/i }));
    await usuario.click(screen.getByRole("button", { name: /continuar/i }));
    await usuario.type(screen.getByLabelText(/dni/i), "12345");
    await usuario.type(screen.getByLabelText(/teléfono/i), "sin-codigo-pais");
    await usuario.click(screen.getByRole("button", { name: /confirmar reserva/i }));

    expect(screen.getByText(/dni.*7.*8 dígitos/i)).toBeInTheDocument();
    expect(screen.getByText(/teléfono.*\+54/i)).toBeInTheDocument();
    expect(fetchEspia).not.toHaveBeenCalled();
    const volcado = consola.mock.calls.map((c) => JSON.stringify(c)).join(" ");
    expect(volcado).not.toMatch(/12345|sin-codigo-pais/);
    fetchEspia.mockRestore();
    consola.mockRestore();
  });
});
