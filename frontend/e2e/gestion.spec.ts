// E2E en ROJO (parte 1) — gestión con token (task 3.1).
// Requiere: ruta /gestionar/:token (aún no existe).
import { expect, test } from "@playwright/test";

const TOKEN = "token-publico-ficticio-0001";

test.describe("gestión del turno con token", () => {
  test("confirma un turno reservado", async ({ page }) => {
    await page.goto(`/gestionar/${TOKEN}`);
    await expect(page.getByText(/limpieza/i)).toBeVisible();
    await page.getByRole("button", { name: /confirmar turno/i }).click();
    await expect(page.getByText(/turno confirmado/i)).toBeVisible();
  });

  test("cancela en término y refleja cancelado", async ({ page }) => {
    await page.goto(`/gestionar/${TOKEN}`);
    await expect(page.getByText(/limpieza/i)).toBeVisible();
    await page.getByRole("button", { name: /cancelar turno/i }).click();
    await page.getByRole("button", { name: /sí, cancelar/i }).click();
    await expect(page.getByText(/turno cancelado/i)).toBeVisible();
  });

  test("fuera de término muestra la política sin mutar", async ({ page }) => {
    await page.goto(`/gestionar/${TOKEN}?fuera_de_termino=1`);
    await expect(page.getByText(/limpieza/i)).toBeVisible();
    await page.getByRole("button", { name: /cancelar turno/i }).click();
    await page.getByRole("button", { name: /sí, cancelar/i }).click();
    await expect(page.getByText(/24 horas de antelación/i)).toBeVisible();
    await expect(page.getByText(/limpieza/i)).toBeVisible();
  });

  test("reprograma conservando el token", async ({ page }) => {
    await page.goto(`/gestionar/${TOKEN}`);
    await expect(page.getByText(/limpieza/i)).toBeVisible();
    await page.getByRole("button", { name: /reprogramar/i }).click();
    await page.getByRole("radio", { name: /09:30/i }).click();
    await page.getByRole("button", { name: /confirmar nuevo horario/i }).click();
    await expect(page.getByText(/nuevo horario/i)).toBeVisible();
    await expect(page.getByText(new RegExp(TOKEN))).toBeVisible();
  });

  test("token inválido no filtra datos", async ({ page }) => {
    const errores: string[] = [];
    page.on("console", (m) => {
      if (m.type() === "error") errores.push(m.text());
    });
    await page.goto("/gestionar/token-inexistente-0000");
    await expect(page.getByText(/no encontramos ese turno/i)).toBeVisible();
    await expect(page.getByText(/limpieza/i)).toHaveCount(0);
    expect(errores.join(" ")).not.toMatch(/token-inexistente-0000/);
  });
});
