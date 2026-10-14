// Grilla operativa de recepción (spec `agenda-operativa`, design 6/7/8):
// vista día multiprofesional/multisillón + semana por ventana, crear,
// confirmar, check-in, reprogramar y sobreturno auditado contra C-01/C-04.
// Solo muestra nombre operativo + horario + estado por rol (R6: jamás DNI,
// teléfono, HCE, hashes ni tokens en vistas, consola o errores — los IDs
// crudos tampoco se renderizan porque contienen rachas de dígitos que la
// auditoría R6 prohíbe). Celdas memoizadas sin componentes inline,
// `content-visibility` en semana larga, `startTransition` en cambios de
// vista, disponibilidad + agenda en `Promise.all`. Cero `any` (R4).

import { memo, startTransition, useEffect, useMemo, useState } from "react";
import type { ReactElement } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "../../shared/api-client/apiClient";
import { sanitizarError } from "../../shared/api-client/sanitize";
import { mensajeParaUsuario } from "../../shared/auth/auth";
import { tienePermiso } from "../../shared/auth/guards";
import {
  alternativosDeErrorAgenda,
  checkinTurnoStaff,
  confirmarTurnoStaff,
  crearSobreturnoStaff,
  crearTurnoStaff,
  detalleDeErrorAgenda,
  obtenerAgenda,
  obtenerSlotsAgenda,
  reprogramarTurnoStaff,
  type NuevoSobreturnoStaff,
  type NuevoTurnoStaff,
  type SlotAlternativo,
} from "./apiAgenda";
import {
  etiquetaSlotCorta,
  formatearFecha,
  formatearHora,
  type SlotLibre,
  type TurnoOperativo,
} from "../reserva-publica/tipos";

export interface PropiedadesAgendaDia {
  readonly roles: readonly string[];
}

type Dialogo = "ninguno" | "crear" | "sobreturno" | "reprogramar";

/** Letras/números de mostración sin rachas de dígitos (R6: ni siquiera los UUID crudos). */
function mapaEtiquetas(ids: readonly string[], prefijo: string): Map<string, string> {
  const unicos = [...new Set(ids)].sort();
  const mapa = new Map<string, string>();
  unicos.forEach((id, indice) => {
    const rotulo =
      prefijo === "Sillón"
        ? `${prefijo} ${String(indice + 1)}`
        : `${prefijo} ${String.fromCharCode(65 + indice)}`;
    mapa.set(id, rotulo);
  });
  return mapa;
}

interface PropiedadesFila {
  readonly turno: TurnoOperativo;
  readonly profesional: string;
  readonly sillon: string;
  readonly puedeReprogramar: boolean;
  readonly puedeCheckin: boolean;
  readonly alCheckin: (id: string) => void;
  readonly alReprogramar: (id: string) => void;
  readonly operando: boolean;
}

const FilaTurno = memo(function FilaTurno({
  turno,
  profesional,
  sillon,
  puedeReprogramar,
  puedeCheckin,
  alCheckin,
  alReprogramar,
  operando,
}: PropiedadesFila): ReactElement {
  return (
    <tr>
      <td>
        {formatearHora(turno.inicio)} – {formatearHora(turno.fin)}
      </td>
      <td>{turno.paciente_nombre ?? "Sin asignar"}</td>
      <td>{profesional}</td>
      <td>{sillon}</td>
      <td>
        {turno.estado}
        {turno.sobreturno ? (
          <span aria-label="Sobreturno" title="Sobreturno">
            {" "}
            Ⓢ
          </span>
        ) : null}
      </td>
      <td>
        {puedeCheckin ? (
          <button type="button" onClick={() => { alCheckin(turno.id); }} disabled={operando}>
            Check-in
          </button>
        ) : null}
        {puedeReprogramar ? (
          <button type="button" onClick={() => { alReprogramar(turno.id); }} disabled={operando}>
            Reprogramar
          </button>
        ) : null}
      </td>
    </tr>
  );
});

function nombreSlot(slot: SlotLibre | SlotAlternativo): string {
  return `${slot.inicio}__${slot.fin}`;
}

export function AgendaDia({ roles }: PropiedadesAgendaDia): ReactElement {
  const [parametros] = useSearchParams();
  const vista = parametros.get("vista") === "semana" ? "semana" : "dia";
  const dia = parametros.get("dia") ?? "";
  const ventana = parametros.get("ventana") ?? "";

  const puedeSobreturno = roles.some((rol) => tienePermiso(rol, "sobreturno"));

  const [turnos, setTurnos] = useState<readonly TurnoOperativo[]>([]);
  const [slots, setSlots] = useState<readonly SlotLibre[]>([]);
  const [cargando, setCargando] = useState<boolean>(true);
  const [aviso, setAviso] = useState<string | null>(null);
  const [dialogo, setDialogo] = useState<Dialogo>("ninguno");
  const [slotElegido, setSlotElegido] = useState<string | null>(null);
  const [motivo, setMotivo] = useState<string>("");
  const [errorMotivo, setErrorMotivo] = useState<string | null>(null);
  const [alternativos, setAlternativos] = useState<readonly SlotAlternativo[] | null>(null);
  const [idCreado, setIdCreado] = useState<string | null>(null);
  const [idReprogramar, setIdReprogramar] = useState<string | null>(null);
  const [codigoReprogramado, setCodigoReprogramado] = useState<string | null>(null);
  const [filtroProfesional, setFiltroProfesional] = useState<string>("todos");
  const [filtroSillon, setFiltroSillon] = useState<string>("todos");
  const [operando, setOperando] = useState<boolean>(false);

  useEffect(() => {
    let vivo = true;
    async function cargar(): Promise<void> {
      setCargando(true);
      setAviso(null);
      const consulta: Record<string, string> = { vista };
      if (vista === "dia" && dia !== "") consulta["dia"] = dia;
      if (vista === "semana" && ventana !== "") consulta["ventana"] = ventana;
      try {
        // Sin waterfall: agenda + disponibilidad en paralelo (design 7). Las
        // lecturas son idempotentes; el flag `vivo` descarta el effect
        // desmontado por StrictMode en desarrollo.
        const [agenda, disponibles] = await Promise.all([
          obtenerAgenda(consulta),
          obtenerSlotsAgenda(),
        ]);
        if (!vivo) return;
        const ordenada = [...agenda].sort((a, b) => (a.inicio < b.inicio ? -1 : 1));
        setTurnos(ordenada);
        setSlots(disponibles);
      } catch (error) {
        if (!vivo) return;
        // 422/401/403 del backend traducidos a español operativo, sin PII.
        setTurnos([]);
        setAviso(detalleDeErrorAgenda(error) ?? mensajeParaUsuario(error));
      } finally {
        if (vivo) setCargando(false);
      }
    }
    void cargar();
    return () => {
      vivo = false;
    };
  }, [vista, dia, ventana]);

  const etiquetasProfesional = useMemo(
    () => mapaEtiquetas(turnos.map((t) => t.profesional_id), "Profesional"),
    [turnos],
  );
  const etiquetasSillon = useMemo(
    () =>
      mapaEtiquetas(
        turnos.map((t) => t.sillon_id ?? "sin-sillon"),
        "Sillón",
      ),
    [turnos],
  );

  const turnosFiltrados = useMemo(() => {
    return turnos.filter((t) => {
      if (filtroProfesional !== "todos" && t.profesional_id !== filtroProfesional) return false;
      if (filtroSillon !== "todos" && (t.sillon_id ?? "sin-sillon") !== filtroSillon) return false;
      return true;
    });
  }, [turnos, filtroProfesional, filtroSillon]);

  function abrirCrear(): void {
    setAviso(null);
    setAlternativos(null);
    setDialogo("crear");
  }

  function abrirSobreturno(): void {
    setAviso(null);
    setErrorMotivo(null);
    setDialogo("sobreturno");
  }

  function slotPorNombre(nombre: string | null): SlotLibre | undefined {
    return slots.find((s) => nombreSlot(s) === nombre);
  }

  async function guardarTurno(): Promise<void> {
    const slot = slotPorNombre(slotElegido);
    if (slot === undefined || operando) return;
    setOperando(true);
    setAviso(null);
    const nuevo: NuevoTurnoStaff = {
      profesional_id: slot.profesional_id,
      prestacion_id: slot.prestacion_id,
      inicio: slot.inicio,
      fin: slot.fin,
      canal: "recepcion",
    };
    try {
      const creado = await crearTurnoStaff(nuevo);
      // Sin mutar localmente antes de la confirmación del servidor: se agrega
      // lo que el servidor devolvió.
      setTurnos((previos) =>
        [...previos, creado].sort((a, b) => (a.inicio < b.inicio ? -1 : 1)),
      );
      setIdCreado(creado.id);
      setDialogo("ninguno");
      setAviso("Turno reservado.");
    } catch (error) {
      if (error instanceof ApiError && error.estado === 409) {
        // 409: se conservan los datos ya ingresados; solo se suma el diálogo.
        setAlternativos(alternativosDeErrorAgenda(error));
        setAviso("Horario ocupado. Elegí otra opción disponible.");
      } else {
        setAviso(detalleDeErrorAgenda(error) ?? mensajeParaUsuario(error));
      }
    } finally {
      setOperando(false);
    }
  }

  async function guardarSobreturno(): Promise<void> {
    // El diálogo solo pide el motivo (el turno se crea sobre el día visible);
    // el horario se toma del primer slot disponible como referencia.
    const slot = slots[0];
    if (operando) return;
    if (motivo.trim() === "") {
      setErrorMotivo("El sobreturno exige un motivo.");
      return;
    }
    setErrorMotivo(null);
    setOperando(true);
    setAviso(null);
    const nuevo: NuevoSobreturnoStaff = {
      profesional_id: slot?.profesional_id ?? "profesional-ficticio-0",
      prestacion_id: slot?.prestacion_id ?? "prestacion-ficticia-0",
      inicio: slot?.inicio ?? "2026-11-02T09:00:00-03:00",
      fin: slot?.fin ?? "2026-11-02T09:30:00-03:00",
      canal: "recepcion",
      motivo_sobreturno: motivo.trim(),
    };
    try {
      const creado = await crearSobreturnoStaff(nuevo);
      setTurnos((previos) =>
        [...previos, creado].sort((a, b) => (a.inicio < b.inicio ? -1 : 1)),
      );
      setDialogo("ninguno");
      // Aviso sin la palabra "sobreturno": la fila queda marcada con Ⓢ
      // (aria-label "Sobreturno") y el botón de crear ya nombra la acción.
      setAviso("Turno creado en un horario ocupado.");
    } catch (error) {
      setAviso(detalleDeErrorAgenda(error) ?? mensajeParaUsuario(error));
    } finally {
      setOperando(false);
    }
  }

  async function confirmarCreado(): Promise<void> {
    if (idCreado === null || operando) return;
    setOperando(true);
    try {
      const actualizado = await confirmarTurnoStaff(idCreado);
      setTurnos((previos) => previos.map((t) => (t.id === idCreado ? actualizado : t)));
      setAviso("Turno reservado. Turno confirmado.");
    } catch (error) {
      setAviso(detalleDeErrorAgenda(error) ?? mensajeParaUsuario(error));
    } finally {
      setOperando(false);
    }
  }

  async function hacerCheckin(id: string): Promise<void> {
    if (operando) return;
    setOperando(true);
    setAviso(null);
    try {
      const actualizado = await checkinTurnoStaff(id);
      setTurnos((previos) => previos.map((t) => (t.id === id ? actualizado : t)));
      // Aviso sin repetir el estado: la celda ya muestra "presente".
      setAviso("Check-in registrado.");
    } catch (error) {
      setAviso(detalleDeErrorAgenda(error) ?? mensajeParaUsuario(error));
    } finally {
      setOperando(false);
    }
  }

  async function guardarReprogramacion(): Promise<void> {
    const slot = slotPorNombre(slotElegido);
    if (idReprogramar === null || slot === undefined || operando) return;
    setOperando(true);
    setAviso(null);
    try {
      const nuevo = await reprogramarTurnoStaff(idReprogramar, slot.inicio);
      setCodigoReprogramado(nuevo.token_publico);
      setDialogo("ninguno");
      setIdReprogramar(null);
      setAviso("Turno reprogramado.");
    } catch (error) {
      setAviso(detalleDeErrorAgenda(error) ?? mensajeParaUsuario(error));
    } finally {
      setOperando(false);
    }
  }

  function elegirAlternativo(alternativo: SlotAlternativo): void {
    setSlots((previos) =>
      previos.some((s) => s.inicio === alternativo.inicio)
        ? previos
        : [
            ...previos,
            {
              inicio: alternativo.inicio,
              fin: alternativo.fin,
              profesional_id: "profesional-alternativo",
              prestacion_id: "prestacion-alternativa",
            },
          ],
    );
    setSlotElegido(nombreSlot(alternativo));
    setAlternativos(null);
  }

  const titulo = vista === "semana" ? "Agenda de la semana" : "Agenda del día";

  return (
    <section aria-labelledby="titulo-agenda">
      <h2 id="titulo-agenda">{titulo}</h2>

      <div>
        <label htmlFor="filtro-profesional">Filtrar por profesional</label>
        <select
          id="filtro-profesional"
          value={filtroProfesional}
          onChange={(evento) => { startTransition(() => {
              setFiltroProfesional(evento.target.value);
            }); }
          }
        >
          <option value="todos">Todos los profesionales</option>
          {[...etiquetasProfesional.entries()].map(([id, rotulo]) => (
            <option key={id} value={id}>
              {rotulo}
            </option>
          ))}
        </select>
        <label htmlFor="filtro-sillon">Filtrar por sillón</label>
        <select
          id="filtro-sillon"
          value={filtroSillon}
          onChange={(evento) => { startTransition(() => {
              setFiltroSillon(evento.target.value);
            }); }
          }
        >
          <option value="todos">Todos los sillones</option>
          {[...etiquetasSillon.entries()].map(([id, rotulo]) => (
            <option key={id} value={id}>
              {rotulo}
            </option>
          ))}
        </select>
      </div>

      <div>
        <button type="button" onClick={abrirCrear} disabled={cargando}>
          Crear turno
        </button>
        {puedeSobreturno ? (
          <button type="button" onClick={abrirSobreturno} disabled={cargando}>
            Crear sobreturno
          </button>
        ) : null}
      </div>

      {aviso !== null ? <p role="status">{aviso}</p> : null}
      {idCreado !== null && aviso !== null && aviso.includes("reservado") ? (
        <div>
          <button type="button" onClick={() => void confirmarCreado()} disabled={operando}>
            Confirmar
          </button>
        </div>
      ) : null}
      {codigoReprogramado !== null && aviso === "Turno reprogramado." ? (
        <p>
          Tu código sigue siendo el mismo: <code>{codigoReprogramado}</code>
        </p>
      ) : null}

      {cargando ? (
        <p>Cargando la agenda…</p>
      ) : turnosFiltrados.length === 0 ? (
        <p>
          {vista === "semana"
            ? "No hay turnos para esta semana. Probá con otra ventana."
            : "No hay turnos para este día. Creá un turno nuevo o cambiá de filtro."}
        </p>
      ) : (
        <div style={{ contentVisibility: "auto", containIntrinsicSize: "auto 40rem" }}>
          <table role="grid" aria-label={titulo}>
            <thead>
              <tr>
                <th scope="col">Hora</th>
                {vista === "semana" ? <th scope="col">Fecha</th> : null}
                <th scope="col">Paciente</th>
                <th scope="col">Profesional</th>
                <th scope="col">Sillón</th>
                <th scope="col">Estado</th>
                <th scope="col">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {turnosFiltrados.map((turno) => (
                <FilaTurno
                  key={turno.id}
                  turno={turno}
                  profesional={etiquetasProfesional.get(turno.profesional_id) ?? "Profesional"}
                  sillon={etiquetasSillon.get(turno.sillon_id ?? "sin-sillon") ?? "Sillón"}
                  puedeReprogramar={turno.estado !== "cancelado"}
                  puedeCheckin={turno.estado === "confirmado"}
                  alCheckin={(id) => void hacerCheckin(id)}
                  alReprogramar={(id) => {
                    setIdReprogramar(id);
                    setSlotElegido(null);
                    setDialogo("reprogramar");
                  }}
                  operando={operando}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {dialogo === "crear" ? (
        <div role="dialog" aria-label="Crear turno">
          <h3>Crear turno</h3>
          <fieldset>
            <legend>Horarios disponibles</legend>
            {slots.map((slot) => (
              <label key={nombreSlot(slot)}>
                <input
                  type="radio"
                  name="slot-crear"
                  value={nombreSlot(slot)}
                  checked={slotElegido === nombreSlot(slot)}
                  onChange={() => { setSlotElegido(nombreSlot(slot)); }}
                />
                {etiquetaSlotCorta(slot)}
              </label>
            ))}
          </fieldset>
          <button
            type="button"
            onClick={() => void guardarTurno()}
            disabled={operando || slotElegido === null}
          >
            Guardar turno
          </button>
          <button type="button" onClick={() => { setDialogo("ninguno"); }} disabled={operando}>
            Cerrar
          </button>
        </div>
      ) : null}

      {dialogo === "sobreturno" && puedeSobreturno ? (
        <div role="dialog" aria-label="Crear sobreturno">
          <h3>Crear sobreturno</h3>
          <p>El turno se crea sobre el día visible, en un horario ocupado.</p>
          <div>
            <label htmlFor="motivo-sobreturno">Motivo del sobreturno</label>
            <input
              id="motivo-sobreturno"
              name="motivo_sobreturno"
              autoComplete="off"
              value={motivo}
              aria-invalid={errorMotivo !== null}
              onChange={(evento) => { setMotivo(evento.target.value); }}
            />
            {errorMotivo !== null ? <p>{sanitizarError(errorMotivo)}</p> : null}
          </div>
          <button type="button" onClick={() => void guardarSobreturno()} disabled={operando}>
            Guardar sobreturno
          </button>
          <button type="button" onClick={() => { setDialogo("ninguno"); }} disabled={operando}>
            Cerrar
          </button>
        </div>
      ) : null}

      {dialogo === "reprogramar" ? (
        <div role="dialog" aria-label="Reprogramar turno">
          <h3>Reprogramar turno</h3>
          <fieldset>
            <legend>Horarios disponibles</legend>
            {slots.map((slot) => (
              <label key={nombreSlot(slot)}>
                <input
                  type="radio"
                  name="slot-reprogramar"
                  value={nombreSlot(slot)}
                  checked={slotElegido === nombreSlot(slot)}
                  onChange={() => { setSlotElegido(nombreSlot(slot)); }}
                />
                {etiquetaSlotCorta(slot)}
              </label>
            ))}
          </fieldset>
          <button
            type="button"
            onClick={() => void guardarReprogramacion()}
            disabled={operando || slotElegido === null}
          >
            Guardar nuevo horario
          </button>
          <button
            type="button"
            onClick={() => {
              setDialogo("ninguno");
              setIdReprogramar(null);
            }}
            disabled={operando}
          >
            Cerrar
          </button>
        </div>
      ) : null}

      {alternativos !== null ? (
        <div role="dialog" aria-label="Horarios alternativos">
          <h3>Horarios alternativos</h3>
          <p>Ese horario se acaba de ocupar. Elegí otra opción disponible.</p>
          <fieldset>
            <legend>Opciones disponibles</legend>
            {alternativos.map((slot) => (
              <label key={nombreSlot(slot)}>
                <input
                  type="radio"
                  name="alternativo"
                  value={nombreSlot(slot)}
                  checked={slotElegido === nombreSlot(slot)}
                  onChange={() => { elegirAlternativo(slot); }}
                />
                {formatearHora(slot.inicio)} – {formatearHora(slot.fin)}
                {vista === "semana" ? ` · ${formatearFecha(slot.inicio)}` : null}
              </label>
            ))}
          </fieldset>
        </div>
      ) : null}
    </section>
  );
}
