// E2E en ROJO (parte 1) — agenda operativa (tasks 4.1, 4.2).
// Requiere: ruta /agenda con grilla día/semana (aún no existe).
import { expect, test } from "@playwright/test";

test.describe("agenda operativa", () => {
  test("día renderiza grilla multiprofesional ordenada", async ({ page }) => {
    await page.goto("/agenda?vista=dia");
    const grilla = page.getByRole("grid", { name: /agenda del día/i });
    await expect(grilla).toBeVisible();
    await expect(page.getByRole("row")).toHaveCount(4);
    await expect(page.getByText(/paciente ficticia uno/i)).toBeVisible();
  });

  test("día vacío invita a actuar sin códigos técnicos", async ({ page }) => {
    await page.goto("/agenda?vista=dia&dia=vacio");
    await expect(page.getByText(/no hay turnos para este día/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /crear turno/i })).toBeVisible();
  });

  test("crear y confirmar turno desde recepción", async ({ page }) => {
    await page.goto("/agenda?vista=dia");
    await expect(page.getByRole("grid", { name: /agenda del día/i })).toBeVisible();
    await page.getByRole("button", { name: /crear turno/i }).click();
    await page.getByRole("radio", { name: /10:00/i }).click();
    await page.getByRole("button", { name: /guardar turno/i }).click();
    await expect(page.getByText(/turno reservado/i)).toBeVisible();
    await page.getByRole("button", { name: /confirmar/i }).click();
    await expect(page.getByText(/turno confirmado/i)).toBeVisible();
  });

  test("semana pagina por ventana y ventana excesiva avisa", async ({ page }) => {
    await page.goto("/agenda?vista=semana");
    await expect(page.getByRole("grid", { name: /agenda de la semana/i })).toBeVisible();
    await page.goto("/agenda?vista=semana&ventana=excesiva");
    await expect(page.getByText(/ventana máxima.*7 días/i)).toBeVisible();
  });

  test("check-in de turno confirmado refleja presente", async ({ page }) => {
    await page.goto("/agenda?vista=dia");
    await expect(page.getByRole("grid", { name: /agenda del día/i })).toBeVisible();
    await page
      .getByRole("row", { name: /paciente ficticio dos/i })
      .getByRole("button", { name: /check-in/i })
      .click();
    await expect(page.getByText(/presente/i)).toBeVisible();
  });

  test("reprogramar conserva el token público", async ({ page }) => {
    await page.goto("/agenda?vista=dia");
    await expect(page.getByRole("grid", { name: /agenda del día/i })).toBeVisible();
    await page
      .getByRole("row", { name: /paciente ficticia uno/i })
      .getByRole("button", { name: /reprogramar/i })
      .click();
    await page.getByRole("radio", { name: /09:30/i }).click();
    await page.getByRole("button", { name: /guardar nuevo horario/i }).click();
    await expect(page.getByText(/reprogramado/i)).toBeVisible();
    await expect(page.getByText(/token-publico-ficticio-0001/)).toBeVisible();
  });

  test("slot tomado ofrece alternativos sin mutar ni perder datos", async ({ page }) => {
    await page.route("**/api/v1/turnos", (route) =>
      route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({
          problema: "slot_ocupado",
          detalle: "El horario ya fue reservado.",
          slots_alternativos: [
            {
              inicio: "2026-11-02T09:30:00-03:00",
              fin: "2026-11-02T10:00:00-03:00",
            },
          ],
        }),
      }),
    );
    await page.goto("/agenda?vista=dia");
    await expect(page.getByRole("grid", { name: /agenda del día/i })).toBeVisible();
    await page.getByRole("button", { name: /crear turno/i }).click();
    await page.getByRole("radio", { name: /09:00/i }).click();
    await page.getByRole("button", { name: /guardar turno/i }).click();
    await expect(page.getByText(/horario ocupado/i)).toBeVisible();
    await expect(
      page.getByRole("dialog", { name: /horarios alternativos/i }),
    ).toBeVisible();
  });

  test("sobreturno con motivo crea y marca la fila", async ({ page }) => {
    await page.goto("/agenda?vista=dia");
    await expect(page.getByRole("grid", { name: /agenda del día/i })).toBeVisible();
    await page.getByRole("button", { name: /crear sobreturno/i }).click();
    await page.getByLabel(/motivo del sobreturno/i).fill("urgencia dolor agudo");
    await page.getByRole("button", { name: /guardar sobreturno/i }).click();
    await expect(page.getByText(/sobreturno/i)).toBeVisible();
  });

  test("ninguna superficie contiene PII", async ({ page }) => {
    const errores: string[] = [];
    page.on("console", (m) => {
      if (m.type() === "error") errores.push(m.text());
    });
    await page.goto("/agenda?vista=dia");
    await expect(page.getByRole("grid", { name: /agenda del día/i })).toBeVisible();
    const texto = (await page.textContent("body")) ?? "";
    expect(texto).not.toMatch(/\b\d{7,8}\b/);
    expect(texto).not.toMatch(/\+54/);
    expect(errores.join(" ")).not.toMatch(/\b\d{7,8}\b|\+54/);
  });
});
