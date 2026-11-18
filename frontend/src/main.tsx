// Entrada de la SPA: en desarrollo levanta el worker MSW (mismo contrato que
// usan Vitest y Playwright) antes del primer render, para que ninguna request
// salga a la red. En producción el worker no se incluye.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./estilos.css";

async function iniciar(): Promise<void> {
  // MSW solo se activa si se solicita explícitamente vía VITE_USE_MOCKS=true (ej. suites aisladas)
  if (import.meta.env.DEV && import.meta.env.VITE_USE_MOCKS === "true") {
    const { workerMsw } = await import("./mocks/browser");
    await workerMsw.start({ onUnhandledRequest: "bypass" });
    const { exponerDetenerMocks } = await import("./mocks/testHooks");
    exponerDetenerMocks(workerMsw);
  } else if ("serviceWorker" in navigator) {
    // Desregistrar cualquier service worker previo de MSW para que las peticiones vayan al backend real
    void navigator.serviceWorker.getRegistrations().then((registrations) => {
      for (const registration of registrations) {
        void registration.unregister();
      }
    });
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
