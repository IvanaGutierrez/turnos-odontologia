// Entrada de la SPA: en desarrollo levanta el worker MSW (mismo contrato que
// usan Vitest y Playwright) antes del primer render, para que ninguna request
// salga a la red. En producción el worker no se incluye.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

async function iniciar(): Promise<void> {
  if (import.meta.env.DEV) {
    const { workerMsw } = await import("./mocks/browser");
    await workerMsw.start({ onUnhandledRequest: "bypass" });
    const { exponerDetenerMocks } = await import("./mocks/testHooks");
    exponerDetenerMocks(workerMsw);
  }
  const raiz = document.getElementById("raiz");
  if (raiz === null) return;
  createRoot(raiz).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void iniciar();
