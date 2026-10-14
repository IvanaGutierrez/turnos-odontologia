// Tests en ROJO (parte 1) — validadores AR + sanitizador R6.
// Verifican: DNI 7–8 dígitos, teléfono E.164 +54…, eliminación de DNI/tel/HCE/
// hashes/tokens de errores y reportes, truncado de textos libres.

import { describe, expect, it, vi } from "vitest";
import { validarDniAr, validarTelefonoAr } from "./validatorsAr";
import { sanitizarError } from "../api-client/sanitize";

describe("validadores AR: DNI", () => {
  it.each(["28000001", "30123456", "1234567"])("acepta DNI válido %s", (dni) => {
    expect(validarDniAr(dni)).toBe(dni);
  });

  it.each(["12345", "123456789", "ABC12345", "", "28.000.0A"])(
    "rechaza DNI inválido %s con mensaje en español",
    (dni) => {
      expect(() => validarDniAr(dni)).toThrowError(/dni/i);
    },
  );

  it("normaliza puntos de miles sin aceptar letras", () => {
    expect(validarDniAr("28.000.001")).toBe("28000001");
  });
});

describe("validadores AR: teléfono", () => {
  it.each(["+54 9 11 5000-0001", "+5491150000001", "+54 11 5000-0001"])(
    "acepta teléfono E.164 AR %s",
    (telefono) => {
      expect(validarTelefonoAr(telefono)).toBe(telefono);
    },
  );

  it.each(["1150000001", "555-1234", "", "+1 212 555-0100", "no-es-un-telefono"])(
    "rechaza teléfono inválido %s sin enviarlo",
    (telefono) => {
      expect(() => validarTelefonoAr(telefono)).toThrowError(/teléfono/i);
    },
  );
});

describe("sanitizador R6: errores y reportes sin PII", () => {
  const MUESTRA_PII = {
    dni: "28000001",
    telefono: "+54 9 11 5000-0001",
    hce: "historia clínica: diabetes tipo 2",
    hash: "argon2id$v=19$m=65536,t=3,p=4$ficticio",
    token: "token-publico-ficticio-0001",
    jwt: "eyJhbGciOiJIUzI1NiJ9.ficticio.firma",
  };

  it("elimina DNI, teléfono, HCE, hashes y tokens del mensaje visible", () => {
    const crudo = `422 en campo dni ${MUESTRA_PII.dni} tel ${MUESTRA_PII.telefono} ${MUESTRA_PII.hce} ${MUESTRA_PII.hash} ${MUESTRA_PII.token} ${MUESTRA_PII.jwt}`;
    const limpio = sanitizarError(crudo);
    expect(limpio).not.toMatch(/28000001/);
    expect(limpio).not.toMatch(/\+54/);
    expect(limpio).not.toMatch(/diabetes/i);
    expect(limpio).not.toMatch(/argon2id/i);
    expect(limpio).not.toMatch(/token-publico/i);
    expect(limpio).not.toMatch(/eyJhbGciOi/);
    expect(limpio).toMatch(/dni|teléfono|campo/i);
  });

  it("trunca textos libres a un máximo visible", () => {
    const largo = `detalle: ${"x".repeat(5000)}`;
    expect(sanitizarError(largo).length).toBeLessThanOrEqual(280);
  });

  it("el reporte de error nunca incluye PII aunque el formulario la tenga", () => {
    const consola = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { reportarError } = sanitizarModulo();
    reportarError(new Error(`falló reserva dni ${MUESTRA_PII.dni} tel ${MUESTRA_PII.telefono}`));
    const volcado = consola.mock.calls.map((c) => JSON.stringify(c)).join(" ");
    expect(volcado).not.toMatch(/28000001|\+54/);
    consola.mockRestore();
  });

  function sanitizarModulo(): { reportarError: (e: Error) => void } {
    // El módulo real expone `reportarError`; si no existe, el test falla en rojo.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mod = require("../api-client/sanitize") as {
      reportarError: (e: Error) => void;
    };
    return mod;
  }
});
