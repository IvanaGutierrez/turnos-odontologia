// Ganchos de test solo-desarrollo (capa mock, jamás producción).
// Expone la detención del worker MSW para el E2E "slot tomado en
// concurrente": el worker opaca `page.route`, así que ese caso detiene el
// mockeado y deja que `page.route` sirva el 409. La rama `import.meta.env.DEV`
// se elimina en el build de producción (impacto prod: cero).

import type { SetupWorker } from "msw/browser";

interface VentanaTest {
  __detenerMocks?: () => void;
}

/** Registra `window.__detenerMocks` (solo DEV, llamado desde `main.tsx`). */
export function exponerDetenerMocks(worker: SetupWorker): void {
  const ventana = window as unknown as VentanaTest;
  ventana.__detenerMocks = () => {
    worker.stop();
  };
}
