// Autogestión del turno propio con token, sin login (spec `reserva-publica-ui`):
// ver (`GET`), confirmar, cancelar (respeta la antelación del backend) y
// reprogramar conservando el token. Ver-propio mínimo con `TurnoPropio`
// (separado de `TurnoOperativo`, R6); token inválido → no-encontrado genérico
// sin datos ni token en pantalla, consola o reportes. Tras errores
// recuperables se repuebla lo ya cargado. Copy en español, cero `any` (R4).

import { useEffect, useState } from "react";
import type { ReactElement } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ApiError } from "../../shared/api-client/apiClient";
import { mensajeParaUsuario } from "../../shared/auth/auth";
import {
  cancelarTurnoPropio,
  confirmarTurnoPropio,
  detalleDeError,
  obtenerDisponibilidad,
  reprogramarTurnoPropio,
  verTurnoPropio,
} from "../../features/reserva-publica/apiReserva";
import {
  etiquetaSlotCorta,
  formatearFecha,
  formatearHora,
  type ReprogramacionPropia,
  type SlotLibre,
  type TurnoPropio,
} from "../../features/reserva-publica/tipos";

type Fase = "cargando" | "lista" | "no-encontrado" | "error-carga";
type Modo = "ver" | "confirmar-cancelacion" | "reprogramar";

export function GestionarTurno(): ReactElement {
  const { token } = useParams();
  const [parametros] = useSearchParams();
  const fueraDeTermino = parametros.get("fuera_de_termino") === "1" ? "?fuera_de_termino=1" : "";

  const [fase, setFase] = useState<Fase>("cargando");
  const [turno, setTurno] = useState<TurnoPropio | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [modo, setModo] = useState<Modo>("ver");
  const [slots, setSlots] = useState<readonly SlotLibre[]>([]);
  const [slotNuevo, setSlotNuevo] = useState<string | null>(null);
  const [reprogramado, setReprogramado] = useState<ReprogramacionPropia | null>(null);
  const [operando, setOperando] = useState<boolean>(false);
  const [intento, setIntento] = useState<number>(0);

  useEffect(() => {
    let vivo = true;
    async function cargar(): Promise<void> {
      if (token === undefined || token === "") {
        if (vivo) setFase("no-encontrado");
        return;
      }
      try {
        const propio = await verTurnoPropio(token);
        if (vivo) {
          setTurno(propio);
          setFase("lista");
        }
      } catch (error) {
        if (!vivo) return;
        if (error instanceof ApiError && error.estado === 404) {
          setFase("no-encontrado");
        } else {
          setFase("error-carga");
          setAviso(mensajeParaUsuario(error));
        }
      }
    }
    void cargar();
    return () => {
      vivo = false;
    };
  }, [token, intento]);

  useEffect(() => {
    if (modo !== "reprogramar") return;
    let vivo = true;
    async function cargarSlots(): Promise<void> {
      try {
        const disponibles = await obtenerDisponibilidad();
        if (vivo) setSlots(disponibles);
      } catch (error) {
        if (vivo) setAviso(mensajeParaUsuario(error));
      }
    }
    void cargarSlots();
    return () => {
      vivo = false;
    };
  }, [modo]);

  async function confirmar(): Promise<void> {
    if (token === undefined || token === "" || operando) return;
    setOperando(true);
    setAviso(null);
    try {
      const actualizado = await confirmarTurnoPropio(token);
      setTurno(actualizado);
      setAviso("Turno confirmado.");
    } catch (error) {
      setAviso(mensajeParaUsuario(error));
    } finally {
      setOperando(false);
    }
  }

  async function cancelar(): Promise<void> {
    if (token === undefined || token === "" || operando) return;
    setOperando(true);
    setAviso(null);
    try {
      const actualizado = await cancelarTurnoPropio(token, fueraDeTermino);
      setTurno(actualizado);
      setModo("ver");
      setAviso("Turno cancelado. Comprobante de cancelación disponible en esta página.");
    } catch (error) {
      // Fuera de término (422): el backend manda la política en `detalle`;
      // el turno no se muta y se repuebla lo ya cargado.
      setModo("ver");
      setAviso(detalleDeError(error) ?? mensajeParaUsuario(error));
    } finally {
      setOperando(false);
    }
  }

  async function reprogramar(): Promise<void> {
    if (token === undefined || token === "" || operando || slotNuevo === null) return;
    setOperando(true);
    setAviso(null);
    try {
      const nuevo = await reprogramarTurnoPropio(token, slotNuevo);
      setReprogramado(nuevo);
      setModo("ver");
      setAviso(null);
    } catch (error) {
      setAviso(detalleDeError(error) ?? mensajeParaUsuario(error));
    } finally {
      setOperando(false);
    }
  }

  if (fase === "cargando") {
    return (
      <main>
        <h1>Gestionar turno</h1>
        <p>Cargando tu turno…</p>
      </main>
    );
  }

  if (fase === "no-encontrado") {
    return (
      <main>
        <h1>No encontramos ese turno</h1>
        <p>Revisá que el enlace esté completo o reservá un turno nuevo.</p>
        <p>
          <Link to="/reservar/consultorio">Reservar un turno</Link>
        </p>
      </main>
    );
  }

  if (fase === "error-carga") {
    return (
      <main>
        <h1>Gestionar turno</h1>
        {aviso !== null ? <p role="alert">{aviso}</p> : null}
        <button type="button" onClick={() => { setIntento((v) => v + 1); }}>
          Reintentar
        </button>
      </main>
    );
  }

  if (turno === null) {
    return (
      <main>
        <h1>Gestionar turno</h1>
        <p>No hay datos para mostrar.</p>
      </main>
    );
  }

  const cancelado = turno.estado === "cancelado";

  return (
    <main>
      <h1>Gestionar turno</h1>
      {aviso !== null ? <p role="status">{aviso}</p> : null}

      <section aria-labelledby="titulo-resumen">
        <h2 id="titulo-resumen">Resumen de tu turno</h2>
        <dl>
          <dt>Motivo</dt>
          <dd>{turno.prestacion_nombre}</dd>
          <dt>Profesional</dt>
          <dd>{turno.profesional_nombre}</dd>
          <dt>Fecha y hora</dt>
          <dd>
            {formatearFecha(turno.inicio)} · {formatearHora(turno.inicio)} –{" "}
            {formatearHora(turno.fin)}
          </dd>
          <dt>Sede</dt>
          <dd>{turno.sede}</dd>
          <dt>Estado</dt>
          <dd>{turno.estado}</dd>
        </dl>
      </section>

      {reprogramado !== null && token !== undefined ? (
        <section aria-labelledby="titulo-reprogramado">
          <h2 id="titulo-reprogramado">Turno reprogramado</h2>
          <p>
            Nuevo horario: {formatearFecha(reprogramado.inicio)} ·{" "}
            {formatearHora(reprogramado.inicio)}
          </p>
          <p>
            Tu código sigue siendo el mismo: <code>{token}</code>
          </p>
          <p>La reserva anterior quedó como reprogramada.</p>
        </section>
      ) : null}

      {!cancelado && modo === "ver" ? (
        <div>
          <button type="button" onClick={() => void confirmar()} disabled={operando}>
            Confirmar turno
          </button>
          <button type="button" onClick={() => { setModo("confirmar-cancelacion"); }} disabled={operando}>
            Cancelar turno
          </button>
          <button type="button" onClick={() => { setModo("reprogramar"); }} disabled={operando}>
            Reprogramar
          </button>
        </div>
      ) : null}

      {modo === "confirmar-cancelacion" ? (
        <div>
          <p>¿Seguro que querés cancelar este turno?</p>
          <button type="button" onClick={() => void cancelar()} disabled={operando}>
            Sí, cancelar
          </button>
          <button type="button" onClick={() => { setModo("ver"); }} disabled={operando}>
            Volver
          </button>
        </div>
      ) : null}

      {modo === "reprogramar" ? (
        <div>
          <h2>Elegí el nuevo horario</h2>
          {slots.length === 0 ? (
            <p>No hay horarios libres en este momento. Volvé a intentarlo más tarde.</p>
          ) : (
            <fieldset>
              <legend>Horarios disponibles</legend>
              {slots.map((slot) => (
                <label key={slot.inicio}>
                  <input
                    type="radio"
                    name="nuevo-horario"
                    value={slot.inicio}
                    checked={slotNuevo === slot.inicio}
                    onChange={() => { setSlotNuevo(slot.inicio); }}
                  />
                  {etiquetaSlotCorta(slot)}
                </label>
              ))}
            </fieldset>
          )}
          <button
            type="button"
            onClick={() => void reprogramar()}
            disabled={operando || slotNuevo === null}
          >
            Confirmar nuevo horario
          </button>
          <button type="button" onClick={() => { setModo("ver"); }} disabled={operando}>
            Volver
          </button>
        </div>
      ) : null}
    </main>
  );
}
