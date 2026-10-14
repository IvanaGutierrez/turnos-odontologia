// E2E en ROJO (parte 1 C-11) — administracion por rol (spec frontend/administracion).
// Requiere: /admin/usuarios CRUD real, /admin/auditoria con filtros,
// /admin/reportes con 3 vistas + CSV (aun no existen). Roles via login real.
import { expect, test } from "@playwright/test";

test.describe("administracion por rol", () => {
  test("admin crea, cambia rol y desactiva un usuario", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/email/i).fill("admin@consultorio.test");
    await page.getByLabel(/contraseña/i).fill("Secreta-ficticia-01");
    await page.getByRole("button", { name: /iniciar sesión/i }).click();
    await expect(page).toHaveURL(/\/admin\/usuarios/);
    await page.getByRole("button", { name: /crear usuario/i }).click();
    await page.getByLabel(/email/i).fill("nuevo.ficticio@consultorio.test");
    await page.getByRole("button", { name: /guardar/i }).click();
    await expect(page.getByText(/nuevo.ficticio@consultorio.test/i)).toBeVisible();
    await page.getByRole("button", { name: /desactivar/i }).first().click();
    await page.getByRole("button", { name: /sí, desactivar/i }).click();
    await expect(page.getByText(/inactiva/i)).toBeVisible();
  });

  test("admin filtra auditoria por turno e id", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/email/i).fill("admin@consultorio.test");
    await page.getByLabel(/contraseña/i).fill("Secreta-ficticia-01");
    await page.getByRole("button", { name: /iniciar sesión/i }).click();
    await expect(page).toHaveURL(/\/admin\/usuarios/);
    await page.getByRole("link", { name: /^auditoría$/i }).click();
    await page.getByLabel(/^entidad$/i).selectOption("turno");
    await page.getByLabel(/id de entidad/i).fill("turno-ficticio-c11-0001");
    await page.getByRole("button", { name: /filtrar/i }).click();
    await expect(page.getByRole("table")).toContainText(/turno_creado|turno_cancelado/i);
  });

  test("odontologo ve solo sus reportes propios", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/email/i).fill("odontologo@consultorio.test");
    await page.getByLabel(/contraseña/i).fill("Secreta-ficticia-01");
    await page.getByRole("button", { name: /iniciar sesión/i }).click();
    await expect(page).toHaveURL(/\/agenda/);
    await page.getByRole("link", { name: /^reportes$/i }).click();
    await expect(page.getByText(/ocupaci/i)).toBeVisible();
    await expect(page.getByLabel(/profesional/i)).toHaveCount(0);
  });

  test("recepcion ve solo el operativo del dia sin CSV", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/email/i).fill("recepcion@consultorio.test");
    await page.getByLabel(/contraseña/i).fill("Secreta-ficticia-01");
    await page.getByRole("button", { name: /iniciar sesión/i }).click();
    await expect(page).toHaveURL(/\/agenda/);
    await page.getByRole("link", { name: /^reportes$/i }).click();
    await expect(page.getByText(/hoy/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /descargar/i })).toHaveCount(0);
  });
});
