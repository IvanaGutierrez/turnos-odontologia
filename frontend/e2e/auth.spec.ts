// E2E en ROJO (parte 1) — guarda de rutas por rol (spec api-client-auth).
// Requiere: /login y guarda deny-by-default (aún no existen).
import { expect, test } from "@playwright/test";

test.describe("guarda de rutas por rol", () => {
  test("recepción entra a agenda y recibe denegación en área admin", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/email/i).fill("recepcion@consultorio.test");
    await page.getByLabel(/contraseña/i).fill("Secreta-ficticia-01");
    await page.getByRole("button", { name: /iniciar sesión/i }).click();
    await expect(page).toHaveURL(/\/agenda/);
    await page.goto("/admin/usuarios");
    await expect(page.getByText(/acceso denegado/i)).toBeVisible();
  });

  test("rate limit muestra espera accionable", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/email/i).fill("bloqueada@consultorio.test");
    await page.getByLabel(/contraseña/i).fill("Secreta-ficticia-01");
    await page.getByRole("button", { name: /iniciar sesión/i }).click();
    await expect(page.getByText(/esper.*reintent/i)).toBeVisible();
  });
});
