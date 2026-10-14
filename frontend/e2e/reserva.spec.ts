// E2E en ROJO (parte 1) — reserva pública 3 taps (tasks 2.1, 2.2).
// Requiere: ruta /reservar/:slug con stepper motivo→slot→DNI+tel (aún no existe).
import { expect, test } from "@playwright/test";

test.describe("reserva pública 3 taps", () => {
  test("motivo→slot→DNI+tel crea turno reservado con token", async ({ page }) => {
    await page.goto("/reservar/consultorio");
    await expect(page.getByRole("heading", { name: /paso 1.*motivo/i })).toBeVisible();
    await page.getByRole("radio", { name: /limpieza/i }).click();
    await page.getByRole("button", { name: /continuar/i }).click();
    await expect(page.getByRole("heading", { name: /paso 2.*horario/i })).toBeVisible();
    await page.getByRole("radio", { name: /09:00/i }).click();
    await page.getByRole("button", { name: /continuar/i }).click();
    await expect(page.getByRole("heading", { name: /paso 3.*datos/i })).toBeVisible();
    await page.getByLabel(/dni/i).fill("28000001");
    await page.getByLabel(/teléfono/i).fill("+54 9 11 5000-0001");
    await page.getByRole("button", { name: /confirmar reserva/i }).click();
    await expect(page.getByText(/turno reservado/i)).toBeVisible();
    await expect(page.getByText(/token-publico-ficticio-0001/)).toBeVisible();
  });

  test("doble envío idempotente crea un único turno", async ({ page }) => {
    await page.goto("/reservar/consultorio");
    await page.getByRole("radio", { name: /limpieza/i }).click();
    await page.getByRole("button", { name: /continuar/i }).click();
    await page.getByRole("radio", { name: /09:30/i }).click();
    await page.getByRole("button", { name: /continuar/i }).click();
    await page.getByLabel(/dni/i).fill("28000001");
    await page.getByLabel(/teléfono/i).fill("+54 9 11 5000-0001");
    await page.getByRole("button", { name: /confirmar reserva/i }).dblclick();
    await expect(page.getByText(/turno reservado/i)).toBeVisible();
    await expect(page.getByText(/turno reservado/i)).toHaveCount(1);
  });

  test("slot tomado en concurrente ofrece alternativos sin perder datos", async ({ page }) => {
    // FIX mock (asserts intactos): el worker MSW opaca `page.route`, así que
    // se detiene el mockeado para este caso (hook solo-dev `__detenerMocks`,
    // ver `src/mocks/testHooks.ts`): el tráfico vuelve a la red y el 409 de
    // abajo sí llega vía `page.route`. Cuerpo y asserts del test: intactos.
    await page.route("**/api/v1/turnos/publicos", (route) =>
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
    await page.goto("/reservar/consultorio");
    await page.waitForFunction(
      () =>
        (window as unknown as { __detenerMocks?: unknown }).__detenerMocks !== undefined,
    );
    await page.evaluate(() => {
      const gancho = (window as unknown as { __detenerMocks?: () => void }).__detenerMocks;
      if (gancho !== undefined) gancho();
    });
    await page.getByRole("radio", { name: /limpieza/i }).click();
    await page.getByRole("button", { name: /continuar/i }).click();
    await page.getByRole("radio", { name: /09:00/i }).click();
    await page.getByRole("button", { name: /continuar/i }).click();
    await page.getByLabel(/dni/i).fill("28000001");
    await page.getByLabel(/teléfono/i).fill("+54 9 11 5000-0001");
    await page.getByRole("button", { name: /confirmar reserva/i }).click();
    await expect(page.getByText(/horario ocupado/i)).toBeVisible();
    await expect(
      page.getByRole("dialog", { name: /horarios alternativos/i }),
    ).toBeVisible();
    await expect(page.getByLabel(/dni/i)).toHaveValue("28000001");
    await expect(page.getByLabel(/teléfono/i)).toHaveValue("+54 9 11 5000-0001");
  });

  test("validación AR por campo bloquea el envío sin requests", async ({ page }) => {
    const enviadas: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/turnos/publicos")) enviadas.push(r.url());
    });
    const errores: string[] = [];
    page.on("console", (m) => {
      if (m.type() === "error") errores.push(m.text());
    });
    await page.goto("/reservar/consultorio");
    await page.getByRole("radio", { name: /limpieza/i }).click();
    await page.getByRole("button", { name: /continuar/i }).click();
    await page.getByRole("radio", { name: /09:00/i }).click();
    await page.getByRole("button", { name: /continuar/i }).click();
    await page.getByLabel(/dni/i).fill("12345");
    await page.getByLabel(/teléfono/i).fill("sin-codigo-pais");
    await page.getByRole("button", { name: /confirmar reserva/i }).click();
    await expect(page.getByText(/dni.*7.*8 dígitos/i)).toBeVisible();
    expect(enviadas).toHaveLength(0);
    expect(errores.join(" ")).not.toMatch(/12345|sin-codigo-pais/);
  });
});
