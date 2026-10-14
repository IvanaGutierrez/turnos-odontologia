// Pago de seña con Mercado Pago (spec `pago-sena-ui`, contrato C-08):
// `pages/pagar/:token` resuelve el link (`GET /pagar/:token`, sin JWT, fuera
// de `/api/v1`), muestra el resumen mínimo en ARS y redirige a MP una sola
// vez aunque se pulse dos veces. Pendiente/rechazado ofrecen reintento sin
// declarar confirmado; token inválido → no-encontrado genérico sin concepto,
// monto ni token en pantalla, consola o reportes (R6). El token jamás se
// persiste (ni estado global ni almacenamiento). Cero `any` (R4).

import { useEffect, useRef, useState } from "react";
import type { ReactElement } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { sanitizarError } from "../../shared/api-client/sanitize";

interface LinkPago {
  readonly init_point: string;
  readonly monto: number;
  readonly moneda: string;
  readonly estado_pago: string;
}

type Fase = "cargando" | "lista" | "no-encontrado" | "error";

function esRegistro(valor: unknown): valor is Record<string, unknown> {
  return typeof valor === "object" && valor !== null;
}

function esLinkPago(valor: unknown): valor is LinkPago {
  if (!esRegistro(valor)) return false;
  return (
    typeof valor["init_point"] === "string" &&
    typeof valor["monto"] === "number" &&
    typeof valor["moneda"] === "string" &&
    typeof valor["estado_pago"] === "string"
  );
}

/** Origen del backend (VITE_API_URL sin el sufijo `/api/v1`, R7): C-08 vive fuera de `/api/v1`. */
function origenPago(): string {
  const deEntorno: unknown = import.meta.env.VITE_API_URL;
  const base =
    typeof deEntorno === "string" && deEntorno.length > 0
      ? deEntorno
      : "http://localhost:8000/api/v1";
  return base.replace(/\/+$/, "").replace(/\/api\/v1$/, "");
}

async function resolverLink(token: string, firma: string | null): Promise<LinkPago> {
  // El link opaco C-03/C-08 viaja firmado (`?firma=` HMAC): se reenvía tal
  // cual cuando la página lo trae; sin firma el backend real responde 404.
  const consulta = firma !== null && firma !== "" ? `?firma=${encodeURIComponent(firma)}` : "";
  let respuesta: Response;
  try {
    respuesta = await fetch(`${origenPago()}/pagar/${encodeURIComponent(token)}${consulta}`, {
      headers: { Accept: "application/json" },
    });
  } catch {
    throw new Error("Error de red. Revisá tu conexión e intentá nuevamente.");
  }
  if (respuesta.status === 404) {
    const ausente = new Error("recurso ausente");
    (ausente as unknown as { noEncontrado?: boolean }).noEncontrado = true;
    throw ausente;
  }
  if (!respuesta.ok) {
    throw new Error("Ocurrió un error inesperado. Intentá nuevamente.");
  }
  let cuerpo: unknown = null;
  try {
    cuerpo = (await respuesta.json()) as unknown;
  } catch {
    throw new Error("Ocurrió un error inesperado. Intentá nuevamente.");
  }
  if (!esLinkPago(cuerpo)) throw new Error("Ocurrió un error inesperado. Intentá nuevamente.");
  return cuerpo;
}

function esNoEncontrado(error: unknown): boolean {
  return (
    esRegistro(error) &&
    (error as unknown as { noEncontrado?: boolean }).noEncontrado === true
  );
}

function formatearMonto(monto: number, moneda: string): string {
  const miles = new Intl.NumberFormat("es-AR").format(monto);
  return `$ ${miles} ${moneda}`;
}

export function PagarSena(): ReactElement {
  const { token } = useParams();
  const [parametros] = useSearchParams();
  const estadoQuery = parametros.get("estado") ?? "";
  const firmaQuery = parametros.get("firma");
  const [fase, setFase] = useState<Fase>("cargando");
  const [link, setLink] = useState<LinkPago | null>(null);
  const redirigidoRef = useRef<boolean>(false);
  const [redirecciones, setRedirecciones] = useState<number>(0);

  useEffect(() => {
    let vivo = true;
    async function cargar(): Promise<void> {
      if (token === undefined || token === "") {
        if (vivo) setFase("no-encontrado");
        return;
      }
      try {
        const resuelto = await resolverLink(token, firmaQuery);
        if (vivo) {
          setLink(resuelto);
          setFase("lista");
        }
      } catch (error) {
        if (!vivo) return;
        if (esNoEncontrado(error)) {
          setFase("no-encontrado");
        } else {
          setFase("error");
        }
      }
    }
    void cargar();
    return () => {
      vivo = false;
    };
  }, [token, firmaQuery]);

  function pagar(): void {
    // Redirección única: el ref frena el segundo clic antes del primer render.
    if (redirigidoRef.current || link === null) return;
    redirigidoRef.current = true;
    setRedirecciones((n) => n + 1);
    window.location.assign(link.init_point);
  }

  function reintentar(): void {
    redirigidoRef.current = false;
    setRedirecciones(0);
    setFase("lista");
  }

  if (fase === "cargando") {
    return (
      <main>
        <h1>Pagar la reserva</h1>
        <p>Cargando la información del pago…</p>
      </main>
    );
  }

  if (fase === "no-encontrado") {
    return (
      <main>
        <h1>No encontramos ese pago</h1>
        <p>Revisá que el enlace esté completo o reservá un turno nuevo.</p>
        <p>
          <Link to="/">Volver al inicio</Link>
        </p>
      </main>
    );
  }

  if (fase === "error" || link === null) {
    return (
      <main>
        <h1>Pagar la reserva</h1>
        <p role="alert">Ocurrió un error inesperado. Intentá nuevamente.</p>
        <p>
          <Link to="/">Volver al inicio</Link>
        </p>
      </main>
    );
  }

  if (estadoQuery === "pendiente") {
    return (
      <main>
        <h1>Pagar la reserva</h1>
        <p>Pago pendiente: tu turno sigue reservado pendiente de seña.</p>
        <button type="button" onClick={reintentar}>
          Reintentar pago
        </button>
      </main>
    );
  }

  if (estadoQuery === "rechazado") {
    return (
      <main>
        <h1>Pagar la reserva</h1>
        <p>Pago rechazado: tu turno sigue reservado pendiente de seña.</p>
        <button type="button" onClick={reintentar}>
          Reintentar pago
        </button>
      </main>
    );
  }

  if (estadoQuery === "acreditado") {
    return (
      <main>
        <h1>Pagar la reserva</h1>
        <p>Turno confirmado. Gracias por acreditar la seña.</p>
      </main>
    );
  }

  return (
    <main>
      <h1>Pagar la reserva</h1>
      <section aria-labelledby="titulo-resumen">
        <h2 id="titulo-resumen">Resumen de la seña</h2>
        <dl>
          <dt>Monto</dt>
          <dd>{sanitizarError(formatearMonto(link.monto, link.moneda))}</dd>
          <dt>Estado</dt>
          <dd>{sanitizarError(link.estado_pago)}</dd>
        </dl>
      </section>
      <button type="button" onClick={pagar} disabled={redirecciones > 0}>
        Pagar con Mercado Pago
      </button>
    </main>
  );
}
