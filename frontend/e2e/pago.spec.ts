// E2E en ROJO (parte 1) — pago de seña (task 5.1).
// Requiere: ruta /pagar/:token (aún no existe). MP mockeado a nivel request.
import { expect, test } from "@playwright/test";

const TOKEN = "token-publico-ficticio-0001";

test.describe("pago de seña con Mercado Pago", () => {
  test("resumen ARS y redirección única ante doble clic", async ({ page }) => {
    await page.route("**://www.mercadopago.com.ar/**", (route) =>
      route.fulfill({ status: 200, body: "MP ficticio" }),
    );
    await page.goto(`/pagar/${TOKEN}`);
    await expect(page.getByText(/seña/i)).toBeVisible();
    const redirecciones: string[] = [];
    page.on("framenavigated", (frame) => {
      if (frame === page.mainFrame()) redirecciones.push(frame.url());
    });
    await page.getByRole("button", { name: /pagar con mercado pago/i }).dblclick();
    await expect.poll(() => redirecciones.filter((u) => u.includes("mercadopago")).length, {
      timeout: 5_000,
    }).toBe(1);
  });

  test("pendiente ofrece reintento sin declarar confirmado", async ({ page }) => {
    await page.goto(`/pagar/${TOKEN}?estado=pendiente`);
    await expect(page.getByText(/pago pendiente/i)).toBeVisible();
    await expect(page.getByText(/sigue reservado/i)).toBeVisible();
    await expect(page.getByText(/turno confirmado/i)).toHaveCount(0);
    await expect(page.getByRole("button", { name: /reintentar pago/i })).toBeVisible();
  });

  test("token inválido genérico sin concepto ni monto", async ({ page }) => {
    await page.goto("/pagar/token-inexistente-0000");
    await expect(page.getByText(/no encontramos ese pago/i)).toBeVisible();
    await expect(page.getByText(/\$ ?15\.000/)).toHaveCount(0);
  });
});
