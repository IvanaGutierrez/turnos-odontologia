// Tests en ROJO (parte 1) — `shared/api-client` (spec api-client-auth).
// Verifican: base VITE_API_URL + access en memoria, rotación única de refresh
// ante 401 con 3 requests en vuelo, idempotencia configurable, reintento
// limitado ante red/5xx sin PII en logs, 401/404 ciegos.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { servidorMsw } from "../../mocks/server";
import { crearClienteApi, ApiError } from "./apiClient";

const BASE = "http://localhost:8000/api/v1";

function clienteFresco(): ReturnType<typeof crearClienteApi> {
  return crearClienteApi({ baseUrl: BASE });
}

describe("api-client: base y autorización", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("envía requests contra VITE_API_URL con Bearer desde memoria", async () => {
    const cliente = clienteFresco();
    cliente.establecerAccess("access-en-memoria-0001");
    const vistos: string[] = [];
    servidorMsw.use(
      http.get("*/api/v1/auth/me", ({ request }) => {
        vistos.push(`${request.url}|${request.headers.get("authorization") ?? ""}`);
        return HttpResponse.json(
          { id: "1", email: "x@y.test", roles: ["recepcion"], activo: true },
          { status: 200 },
        );
      }),
    );
    await cliente.get<{ email: string }>("/auth/me");
    expect(vistos).toHaveLength(1);
    expect(vistos[0]).toBe(`${BASE}/auth/me|Bearer access-en-memoria-0001`);
  });

  it("no guarda el access en localStorage", async () => {
    const cliente = clienteFresco();
    cliente.establecerAccess("access-en-memoria-0002");
    expect(window.localStorage.getItem("access_token")).toBeNull();
    expect(window.localStorage.length).toBe(0);
  });
});

describe("api-client: rotación única de refresh ante 401", () => {
  it("con 3 requests en vuelo ejecuta una sola rotación y reintenta las tres", async () => {
    let rotaciones = 0;
    let intentosAgenda = 0;
    servidorMsw.use(
      http.get("*/api/v1/agenda", ({ request }) => {
        intentosAgenda += 1;
        const auth = request.headers.get("authorization") ?? "";
        if (auth === "Bearer access-expirado") {
          return HttpResponse.json({ detalle: "Sesión inválida." }, { status: 401 });
        }
        return HttpResponse.json([], { status: 200 });
      }),
      http.post("*/api/v1/auth/refresh", () => {
        rotaciones += 1;
        return HttpResponse.json({ access_token: "access-rotado-0003" }, { status: 200 });
      }),
    );
    const cliente = clienteFresco();
    cliente.establecerAccess("access-expirado");
    const resultados = await Promise.all([
      cliente.get<unknown[]>("/agenda?vista=dia"),
      cliente.get<unknown[]>("/agenda?vista=dia"),
      cliente.get<unknown[]>("/agenda?vista=dia"),
    ]);
    expect(resultados).toEqual([[], [], []]);
    expect(rotaciones).toBe(1);
    expect(intentosAgenda).toBe(6);
  });

  it("ante refresh inválido cierra la sesión y avisa en español", async () => {
    servidorMsw.use(
      http.get("*/api/v1/agenda", () => {
        return HttpResponse.json({ detalle: "Sesión inválida." }, { status: 401 });
      }),
      http.post("*/api/v1/auth/refresh", () => {
        return HttpResponse.json({ detalle: "Sesión inválida." }, { status: 401 });
      }),
    );
    const cliente = clienteFresco();
    cliente.establecerAccess("access-expirado");
    const error = await cliente.get("/agenda?vista=dia").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).mensaje).toMatch(/sesi/i);
    expect(cliente.accessActual()).toBeNull();
  });
});

describe("api-client: idempotencia configurable", () => {
  it("agrega Idempotency-Key solo cuando se pide", async () => {
    const claves: Array<string | null> = [];
    servidorMsw.use(
      http.post("*/api/v1/turnos/publicos", ({ request }) => {
        claves.push(request.headers.get("Idempotency-Key"));
        return HttpResponse.json({ estado: "reservado" }, { status: 201 });
      }),
    );
    const cliente = clienteFresco();
    await cliente.post("/turnos/publicos", { inicio: "x" });
    await cliente.post("/turnos/publicos", { inicio: "x" }, { idempotencia: "clave-abc-123" });
    expect(claves).toEqual([null, "clave-abc-123"]);
  });
});

describe("api-client: reintento limitado y errores ciegos", () => {
  it("ante fallo de red reintenta con límite y avisa en español sin PII", async () => {
    const consola = vi.spyOn(console, "error").mockImplementation(() => undefined);
    let intentos = 0;
    servidorMsw.use(
      http.get("*/api/v1/agenda", () => {
        intentos += 1;
        return HttpResponse.error();
      }),
    );
    const cliente = clienteFresco();
    const error = await cliente
      .get("/agenda?vista=dia", undefined, { reintentos: 2 })
      .catch((e: unknown) => e);
    expect(intentos).toBeLessThanOrEqual(3);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).mensaje).toMatch(/intent|reintent|red/i);
    const volcado = consola.mock.calls.map((c) => JSON.stringify(c)).join(" ");
    expect(volcado).not.toMatch(/28000001|\+54|token-publico/i);
    consola.mockRestore();
  });

  it("el 404 es ciego: no revela si el recurso existe", async () => {
    const cliente = clienteFresco();
    const error = await cliente
      .get("/turnos/publicos/token-inexistente-0000")
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).estado).toBe(404);
    expect((error as ApiError).mensaje).not.toMatch(/token-inexistente/i);
  });

  it("el 401 no expone el token ni credenciales", async () => {
    const consola = vi.spyOn(console, "error").mockImplementation(() => undefined);
    servidorMsw.use(
      http.post("*/api/v1/auth/refresh", () => {
        return HttpResponse.json({ detalle: "Sesión inválida." }, { status: 401 });
      }),
    );
    const cliente = clienteFresco();
    cliente.establecerAccess("access-secreto-0004");
    await cliente.get("/auth/me").catch(() => undefined);
    const volcado = consola.mock.calls.map((c) => JSON.stringify(c)).join(" ");
    expect(volcado).not.toMatch(/access-secreto-0004|password|refresh/i);
    consola.mockRestore();
  });
});
