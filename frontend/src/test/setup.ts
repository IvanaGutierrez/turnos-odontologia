import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { afterAll, afterEach, beforeAll } from "vitest";
import { ModuleKind, ScriptTarget, transpileModule } from "typescript";
import { servidorMsw } from "../mocks/server";

// Interop CJS: `validatorsAr.test.ts` usa `require()` relativo (Node puro),
// que no resuelve `.ts`. Se registra la extensión transpilando a CJS con el
// compilador TypeScript (JS puro, apto para jsdom; esbuild exige invariantes
// del entorno Node que jsdom no cumple). Solo entorno de test. Sin tocar tests.
const requireNativo = createRequire(import.meta.url);
interface ModuloCompilable {
  _compile(contenido: string, nombre: string): void;
}
const cargador = requireNativo("module") as {
  _extensions: Record<string, (modulo: ModuloCompilable, nombre: string) => void>;
};
cargador._extensions[".ts"] = (modulo: ModuloCompilable, nombre: string): void => {
  const fuente = readFileSync(nombre, "utf8");
  const { outputText } = transpileModule(fuente, {
    compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2020 },
  });
  modulo._compile(outputText, nombre);
};

beforeAll(() => {
  servidorMsw.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  // Testing Library no registra su auto-cleanup con `globals: false`;
  // se repone acá para aislar el DOM entre tests (semántica estándar RTL).
  cleanup();
  servidorMsw.resetHandlers();
});

afterAll(() => {
  servidorMsw.close();
});
