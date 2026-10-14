import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";

// Worker para dev y E2E (parte 2): la app lo inicia solo en desarrollo.
export const workerMsw = setupWorker(...handlers);
