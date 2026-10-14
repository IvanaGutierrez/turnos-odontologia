// Stepper accesible de reserva pública en 3 pasos (spec `reserva-publica-ui`):
// 1) motivo → 2) horario real → 3) DNI + teléfono AR.
// Presentacional: los slots llegan por props (la `page` los carga en
// paralelo con `Promise.all`); por defecto usa el catálogo inicial para el
// primer render. `startTransition` entre pasos, validación AR por campo sin
// envío, doble envío idempotente (una sola request), `409` que conserva los
// inputs y ofrece alternativos en un tap. Copy en español, cero `any` (R4),
// jamás PII en consola (R6).

import { startTransition, useEffect, useRef, useState } from "react";
import type { ReactElement } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../shared/api-client/apiClient";
import { mensajeParaUsuario } from "../../shared/auth/auth";
import { validarDniAr, validarTelefonoAr } from "../../shared/validators/validatorsAr";
import { alternativosDeError, crearTurnoPublico } from "./apiReserva";
import {
  CATALOGO_PRESTACIONES,
  SLOTS_INICIALES,
  etiquetaSlotCorta,
  formatearFecha,
  formatearHora,
  nombrePrestacion,
  nombreProfesional,
  type SlotLibre,
  type TurnoPublicoCreado,
} from "./tipos";

export interface PropiedadesReservaStepper {
  readonly slug: string;
  readonly slotsIniciales?: readonly SlotLibre[];
}

type Paso = 1 | 2 | 3;

function generarClaveIdempotencia(): string {
  const cripto = globalThis.crypto;
  if (typeof cripto !== "undefined" && typeof cripto.randomUUID === "function") {
    return cripto.randomUUID();
  }
  return `reserva-${Date.now().toString(36)}-${Math.floor(Math.random() * 16777215).toString(36)}`;
}

function etiquetaSlot(slot: SlotLibre): string {
  return `${formatearHora(slot.inicio)} – ${formatearHora(slot.fin)}`;
}

export function ReservaStepper({
  slug,
  slotsIniciales = SLOTS_INICIALES,
}: PropiedadesReservaStepper): ReactElement {
  const [slots, setSlots] = useState<readonly SlotLibre[]>([...slotsIniciales]);
  const [paso, setPaso] = useState<Paso>(1);
  const [prestacionId, setPrestacionId] = useState<string>(
    CATALOGO_PRESTACIONES[0]?.id ?? "",
  );
  const [slotElegido, setSlotElegido] = useState<string | null>(null);
  const [dni, setDni] = useState<string>("");
  const [telefono, setTelefono] = useState<string>("");
  const [errorDni, setErrorDni] = useState<string | null>(null);
  const [errorTelefono, setErrorTelefono] = useState<string | null>(null);
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);
  const [alternativos, setAlternativos] = useState<readonly SlotLibre[] | null>(null);
  const [resultado, setResultado] = useState<TurnoPublicoCreado | null>(null);
  const [resumenElegido, setResumenElegido] = useState<{ motivo: string; profesional: string } | null>(
    null,
  );
  const [enviando, setEnviando] = useState<boolean>(false);
  const enviandoRef = useRef<boolean>(false);
  const claveRef = useRef<string>(generarClaveIdempotencia());

  useEffect(() => {
    setSlots([...slotsIniciales]);
  }, [slotsIniciales]);

  function irAPaso(siguiente: Paso): void {
    setErrorGeneral(null);
    startTransition(() => {
      setPaso(siguiente);
    });
  }

  function elegirAlternativo(inicio: string): void {
    const opciones = alternativos ?? [];
    const elegido = opciones.find((s) => s.inicio === inicio);
    setSlots((previos) =>
      previos.some((s) => s.inicio === inicio)
        ? previos
        : [...previos, ...opciones.filter((s) => s.inicio === inicio)],
    );
    if (elegido !== undefined) setSlotElegido(elegido.inicio);
    setAlternativos(null);
  }

  async function confirmarReserva(): Promise<void> {
    // Doble envío: el ref frena en seco el segundo clic (el estado tarda
    // un render en deshabilitar el botón).
    if (enviandoRef.current) return;

    let dniValido: string | null = null;
    let telefonoValido: string | null = null;
    try {
      dniValido = validarDniAr(dni);
      setErrorDni(null);
    } catch (error) {
      setErrorDni(mensajeParaUsuario(error));
    }
    try {
      telefonoValido = validarTelefonoAr(telefono);
      setErrorTelefono(null);
    } catch (error) {
      setErrorTelefono(mensajeParaUsuario(error));
    }
    const slot = slots.find((s) => s.inicio === slotElegido);
    // Validación AR por campo: sin valores válidos no hay envío ni logs.
    if (dniValido === null || telefonoValido === null || slot === undefined) {
      if (slot === undefined) {
        setErrorGeneral("Elegí un horario disponible para continuar.");
      }
      return;
    }

    enviandoRef.current = true;
    setEnviando(true);
    setErrorGeneral(null);
    // Resumen con lo elegido (el servidor puede devolver IDs fuera del catálogo).
    setResumenElegido({
      motivo: nombrePrestacion(prestacionId),
      profesional: nombreProfesional(slot.profesional_id),
    });
    try {
      const creado = await crearTurnoPublico(
        {
          prestacion_id: prestacionId,
          profesional_id: slot.profesional_id,
          inicio: slot.inicio,
          fin: slot.fin,
          dni: dniValido,
          telefono: telefonoValido,
        },
        claveRef.current,
      );
      setResultado(creado);
      setAlternativos(null);
    } catch (error) {
      enviandoRef.current = false;
      setEnviando(false);
      // Reintento con clave nueva: el cuerpo puede cambiar de slot.
      claveRef.current = generarClaveIdempotencia();
      if (error instanceof ApiError && error.estado === 409) {
        // 409: se conservan motivo, slot, DNI y teléfono; solo se suma el diálogo.
        setAlternativos(alternativosDeError(error));
      } else {
        setErrorGeneral(mensajeParaUsuario(error));
      }
    }
  }

  if (resultado !== null) {
    return (
      <section aria-labelledby="titulo-reservado">
        <h2 id="titulo-reservado">Turno reservado</h2>
        <dl>
          <dt>Motivo</dt>
          <dd>{resumenElegido?.motivo ?? nombrePrestacion(resultado.prestacion_id)}</dd>
          <dt>Profesional</dt>
          <dd>{resumenElegido?.profesional ?? nombreProfesional(resultado.profesional_id)}</dd>
          <dt>Fecha y hora</dt>
          <dd>
            {formatearFecha(resultado.inicio)} · {etiquetaSlot(resultado)}
          </dd>
          <dt>Sede</dt>
          <dd>{slug}</dd>
        </dl>
        <p>
          Guardá este código para gestionar tu turno: <code>{resultado.token_publico}</code>
        </p>
        <p>
          <Link to={`/gestionar/${resultado.token_publico}`}>Gestionar mi turno</Link>
        </p>
      </section>
    );
  }

  const pasos: ReadonlyArray<{ n: Paso; nombre: string }> = [
    { n: 1, nombre: "Motivo" },
    { n: 2, nombre: "Horario" },
    { n: 3, nombre: "Datos" },
  ];

  return (
    <section aria-labelledby="titulo-reserva">
      <h2 id="titulo-reserva">Reservar turno</h2>
      <ol aria-label="Progreso de la reserva">
        {pasos.map((item) => (
          <li key={item.n} aria-current={item.n === paso ? "step" : undefined}>
            Paso {item.n}: {item.nombre}
          </li>
        ))}
      </ol>

      {paso === 1 ? (
        <div>
          <h3>Paso 1 de 3 · Motivo de la consulta</h3>
          <fieldset>
            <legend>Elegí el motivo</legend>
            {CATALOGO_PRESTACIONES.map((prestacion) => (
              <label key={prestacion.id}>
                <input
                  type="radio"
                  name="motivo"
                  value={prestacion.id}
                  checked={prestacionId === prestacion.id}
                  onChange={() => { setPrestacionId(prestacion.id); }}
                />
                {prestacion.nombre} · {prestacion.duracionMin} min
              </label>
            ))}
          </fieldset>
          <button type="button" onClick={() => { irAPaso(2); }}>
            Continuar
          </button>
        </div>
      ) : null}

      {paso === 2 ? (
        <div>
          <h3>Paso 2 de 3 · Elegí el horario</h3>
          {slots.length === 0 ? (
            <div>
              <p>No hay horarios libres en este momento. Probá con otro motivo o volvé más tarde.</p>
              <button type="button" onClick={() => { irAPaso(1); }}>
                Volver al motivo
              </button>
            </div>
          ) : (
            <fieldset>
              <legend>Horarios disponibles</legend>
              {slots.map((slot) => (
                <label key={slot.inicio}>
                  <input
                    type="radio"
                    name="slot"
                    value={slot.inicio}
                    checked={slotElegido === slot.inicio}
                    onChange={() => { setSlotElegido(slot.inicio); }}
                  />
                  {etiquetaSlotCorta(slot)} · {nombreProfesional(slot.profesional_id)}
                </label>
              ))}
            </fieldset>
          )}
          <button type="button" onClick={() => { irAPaso(1); }}>
            Atrás
          </button>
          {slots.length > 0 ? (
            <button type="button" onClick={() => { irAPaso(3); }} disabled={slotElegido === null}>
              Continuar
            </button>
          ) : null}
        </div>
      ) : null}

      {paso === 3 ? (
        <div>
          <h3>Paso 3 de 3 · Tus datos</h3>
          <p>La primera reserva puede requerir verificación por código.</p>
          <div>
            <label htmlFor="reserva-dni">DNI</label>
            <input
              id="reserva-dni"
              name="dni"
              inputMode="numeric"
              autoComplete="off"
              value={dni}
              aria-invalid={errorDni !== null}
              aria-describedby={
                errorDni !== null ? "reserva-dni-ayuda reserva-dni-error" : "reserva-dni-ayuda"
              }
              onChange={(evento) => { setDni(evento.target.value); }}
            />
            <p id="reserva-dni-ayuda">Ingresá 7 u 8 dígitos, sin puntos.</p>
            {errorDni !== null ? <p id="reserva-dni-error">{errorDni}</p> : null}
          </div>
          <div>
            <label htmlFor="reserva-telefono">Teléfono</label>
            <input
              id="reserva-telefono"
              name="telefono"
              type="tel"
              autoComplete="off"
              value={telefono}
              aria-invalid={errorTelefono !== null}
              aria-describedby={
                errorTelefono !== null
                  ? "reserva-telefono-ayuda reserva-telefono-error"
                  : "reserva-telefono-ayuda"
              }
              onChange={(evento) => { setTelefono(evento.target.value); }}
            />
            <p id="reserva-telefono-ayuda">Usá el formato +54 seguido del número.</p>
            {errorTelefono !== null ? <p id="reserva-telefono-error">{errorTelefono}</p> : null}
          </div>
          {errorGeneral !== null ? <p role="alert">{errorGeneral}</p> : null}
          <button type="button" onClick={() => { irAPaso(2); }}>
            Atrás
          </button>
          <button
            type="button"
            onClick={() => void confirmarReserva()}
            disabled={enviando}
          >
            Confirmar reserva
          </button>
        </div>
      ) : null}

      {alternativos !== null ? (
        <div role="dialog" aria-label="Horarios alternativos">
          <h3>Horario ocupado</h3>
          <p>Ese horario se acaba de ocupar. Elegí otra opción disponible.</p>
          <fieldset>
            <legend>Opciones disponibles</legend>
            {alternativos.map((slot) => (
              <label key={slot.inicio}>
                <input
                  type="radio"
                  name="alternativo"
                  value={slot.inicio}
                  checked={slotElegido === slot.inicio}
                  onChange={() => { elegirAlternativo(slot.inicio); }}
                />
                {etiquetaSlotCorta(slot)} · {nombreProfesional(slot.profesional_id)}
              </label>
            ))}
          </fieldset>
        </div>
      ) : null}
    </section>
  );
}
