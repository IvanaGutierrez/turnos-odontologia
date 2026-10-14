// Tests en ROJO (parte 1) — grilla de recepción (spec agenda-operativa):
// render con mock multiprofesional/multisillón, día vacío accionable,
// sobreturno oculto a odontólogo, sin PII por rol (R6).

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { AgendaDia } from "./AgendaDia";

function renderAgenda(roles: string[]): void {
  render(
    <MemoryRouter initialEntries={["/agenda?vista=dia"]}>
      <AgendaDia roles={roles} />
    </MemoryRouter>,
  );
}

describe("agenda día: grilla multiprofesional", () => {
  it("renderiza turnos ordenados por hora en su columna profesional/sillón", async () => {
    renderAgenda(["recepcion"]);
    const grilla = await screen.findByRole("grid", { name: /agenda del día/i });
    expect(grilla).toBeInTheDocument();
    const filas = screen.getAllByRole("row");
    // Cabecera + 3 turnos mockeados, orden cronológico.
    expect(filas).toHaveLength(4);
    expect(filas[1]?.textContent ?? "").toMatch(/09:00/);
    expect(screen.getByText(/paciente ficticia uno/i)).toBeInTheDocument();
    expect(screen.getByText(/paciente ficticio dos/i)).toBeInTheDocument();
  });

  it("día vacío invita a crear un turno o cambiar de filtro", async () => {
    render(
      <MemoryRouter initialEntries={["/agenda?vista=dia&dia=vacio"]}>
        <AgendaDia roles={["recepcion"]} />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/no hay turnos para este día/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /crear turno/i })).toBeInTheDocument();
    expect(screen.queryByText(/404|500|error técnico/i)).not.toBeInTheDocument();
  });

  it("recepción crea y confirma un turno visible en la grilla", async () => {
    const usuario = userEvent.setup();
    renderAgenda(["recepcion"]);
    await screen.findByRole("grid", { name: /agenda del día/i });
    await usuario.click(screen.getByRole("button", { name: /crear turno/i }));
    await usuario.click(screen.getByRole("radio", { name: /10:00/i }));
    await usuario.click(screen.getByRole("button", { name: /guardar turno/i }));
    expect(await screen.findByText(/turno reservado/i)).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: /confirmar/i }));
    expect(await screen.findByText(/turno confirmado/i)).toBeInTheDocument();
  });

  it("sobreturno visible para recepción con motivo, oculto para odontólogo", async () => {
    const usuario = userEvent.setup();
    renderAgenda(["recepcion"]);
    await screen.findByRole("grid", { name: /agenda del día/i });
    await usuario.click(screen.getByRole("button", { name: /crear sobreturno/i }));
    await usuario.type(
      screen.getByLabelText(/motivo del sobreturno/i),
      "urgencia dolor agudo",
    );
    await usuario.click(screen.getByRole("button", { name: /guardar sobreturno/i }));
    expect(await screen.findByText(/sobreturno/i)).toBeInTheDocument();
  });

  it("odontólogo no ve el control de sobreturno en el DOM", async () => {
    renderAgenda(["odontologo"]);
    await screen.findByRole("grid", { name: /agenda del día/i });
    expect(screen.queryByRole("button", { name: /sobreturno/i })).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toMatch(/sobreturno/i);
  });

  it("ninguna superficie expone DNI, teléfono, HCE, hashes ni tokens", async () => {
    const consola = vi.spyOn(console, "error").mockImplementation(() => undefined);
    renderAgenda(["recepcion"]);
    await screen.findByRole("grid", { name: /agenda del día/i });
    const texto = document.body.textContent ?? "";
    expect(texto).not.toMatch(/\b\d{7,8}\b/);
    expect(texto).not.toMatch(/\+54/);
    expect(texto).not.toMatch(/historia clínica|token|hash/i);
    const volcado = consola.mock.calls.map((c) => JSON.stringify(c)).join(" ");
    expect(volcado).not.toMatch(/\b\d{7,8}\b|\+54|token/i);
    consola.mockRestore();
  });
});
