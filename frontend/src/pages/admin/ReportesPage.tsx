// Reportes operativos por rol (specs `admin/reportes-operativos`,
// `frontend/administracion`): admin full (filtros + 3 bloques + CSV),
// odontologo propios (3 bloques sin selectores + CSV propio), recepcion
// operativo del dia (sin filtros ni CSV). Primer render con agregados de
// ejemplo sinteticos (R0) que el fetch reemplaza (patron del repo); la
// descarga usa blob tipado con nombre `reporte-<tipo>-<desde>-<hasta>.csv` e
// iguala los numeros en pantalla. Sin permiso la guarda muestra denegado SIN
// llamar a la API. Tablas semanticas, copy en espanol, cero `any` (R4), solo
// agregados sin PII/HC (R6).

import { useEffect, useState } from "react";
import type { ReactElement } from "react";
import { RequireRol } from "../../shared/auth/guards";
import { AdminNav } from "./AdminNav";
import { mensajeParaUsuario, obtenerSesion } from "../../shared/auth/auth";
import {
  construirCsvAusentismo,
  construirCsvIngresos,
  construirCsvOcupacion,
  nombreCsv,
  obtenerAusentismo,
  obtenerIngresos,
  obtenerOcupacion,
} from "../../features/admin/apiReportes";
import type {
  Ausentismo,
  Ingresos,
  Ocupacion,
  RangoFechas,
  TipoReporte,
} from "../../features/admin/tipos";
import { AUSENTISMO_EJEMPLO, INGRESOS_EJEMPLO, OCUPACION_EJEMPLO } from "../../features/admin/tipos";

function hoyAR(fecha: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Argentina/Buenos_Aires",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(fecha);
}

function haceDiasAR(dias: number): string {
  return hoyAR(new Date(Date.now() - dias * 24 * 60 * 60 * 1000));
}

interface DatosReportes {
  readonly ocupacion: Ocupacion;
  readonly ausentismo: Ausentismo;
  readonly ingresos: Ingresos;
}

const DATOS_INICIALES: DatosReportes = {
  ocupacion: OCUPACION_EJEMPLO,
  ausentismo: AUSENTISMO_EJEMPLO,
  ingresos: INGRESOS_EJEMPLO,
};

function BloqueOcupacion({ datos }: { readonly datos: Ocupacion }): ReactElement {
  return (
    <section aria-label="Ocupacion">
      <h2>Ocupacion</h2>
      <h3>Por profesional</h3>
      <table>
        <thead>
          <tr>
            <th scope="col">Profesional</th>
            <th scope="col">Turnos totales</th>
            <th scope="col">Turnos activos</th>
            <th scope="col">Horas ocupadas</th>
            <th scope="col">Porcentaje</th>
          </tr>
        </thead>
        <tbody>
          {datos.por_profesional.map((fila) => (
            <tr key={fila.profesional_id ?? "sin-profesional"}>
              <td>{fila.profesional_id ?? "—"}</td>
              <td>{fila.turnos_totales}</td>
              <td>{fila.turnos_activos}</td>
              <td>{fila.horas_ocupadas}</td>
              <td>{fila.ocupacion_pct}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Por sillon</h3>
      <table>
        <thead>
          <tr>
            <th scope="col">Sillon</th>
            <th scope="col">Turnos totales</th>
            <th scope="col">Turnos activos</th>
            <th scope="col">Horas ocupadas</th>
            <th scope="col">Porcentaje</th>
          </tr>
        </thead>
        <tbody>
          {datos.por_sillon.map((fila) => (
            <tr key={fila.sillon_id ?? "sin-sillon"}>
              <td>{fila.sillon_id ?? "—"}</td>
              <td>{fila.turnos_totales}</td>
              <td>{fila.turnos_activos}</td>
              <td>{fila.horas_ocupadas}</td>
              <td>{fila.ocupacion_pct}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function BloqueAusentismo({ datos }: { readonly datos: Ausentismo }): ReactElement {
  return (
    <section aria-label="Ausentismo">
      <h2>Ausentismo</h2>
      <p>
        Finalizados: {datos.turnos_finalizados} · Ausentes: {datos.ausentes} · Tasa:{" "}
        {datos.ausentismo_pct} %
      </p>
      <table>
        <thead>
          <tr>
            <th scope="col">Profesional</th>
            <th scope="col">Finalizados</th>
            <th scope="col">Ausentes</th>
            <th scope="col">Tasa %</th>
          </tr>
        </thead>
        <tbody>
          {datos.por_profesional.map((fila) => (
            <tr key={fila.profesional_id}>
              <td>{fila.profesional_id}</td>
              <td>{fila.turnos_finalizados}</td>
              <td>{fila.ausentes}</td>
              <td>{fila.ausentismo_pct}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function BloqueIngresos({ datos }: { readonly datos: Ingresos }): ReactElement {
  return (
    <section aria-label="Ingresos">
      <h2>Ingresos</h2>
      <p>
        Total: {datos.total} · Acreditado MP: {datos.acreditado_mp} · Diferencia: {datos.diferencia}
      </p>
      <table>
        <thead>
          <tr>
            <th scope="col">Metodo</th>
            <th scope="col">Monto</th>
          </tr>
        </thead>
        <tbody>
          {Object.keys(datos.por_metodo)
            .sort()
            .map((metodo) => (
              <tr key={metodo}>
                <td>{metodo}</td>
                <td>{datos.por_metodo[metodo] ?? 0}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </section>
  );
}

/** Descarga inmediata del bloque visible (blob con BOM, sin round-trip). */
function descargarBloque(tipo: TipoReporte, rango: RangoFechas, datos: DatosReportes): void {
  const csv =
    tipo === "ocupacion"
      ? construirCsvOcupacion(rango, datos.ocupacion)
      : tipo === "ausentismo"
        ? construirCsvAusentismo(rango, datos.ausentismo)
        : construirCsvIngresos(rango, datos.ingresos);
  // BOM explicito (Excel AR) + contenido con los headers del contrato.
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const enlace = document.createElement("a");
  enlace.href = url;
  enlace.download = nombreCsv(tipo, rango);
  document.body.appendChild(enlace);
  enlace.click();
}

async function traerReportes(filtros: {
  readonly desde: string;
  readonly hasta: string;
  readonly profesional_id?: string | undefined;
  readonly sillon_id?: string | undefined;
  readonly sede?: string | undefined;
}): Promise<DatosReportes> {
  const [ocupacion, ausentismo, ingresos] = await Promise.all([
    obtenerOcupacion({
      desde: filtros.desde,
      hasta: filtros.hasta,
      profesional_id: filtros.profesional_id,
      sillon_id: filtros.sillon_id,
      sede: filtros.sede,
    }),
    obtenerAusentismo({
      desde: filtros.desde,
      hasta: filtros.hasta,
      profesional_id: filtros.profesional_id,
      sede: filtros.sede,
    }),
    obtenerIngresos({ desde: filtros.desde, hasta: filtros.hasta, sede: filtros.sede }),
  ]);
  return { ocupacion, ausentismo, ingresos };
}

function VistaAdmin(): ReactElement {
  const [desde, setDesde] = useState<string>(() => haceDiasAR(7));
  const [hasta, setHasta] = useState<string>(() => hoyAR(new Date()));
  const [profesionalId, setProfesionalId] = useState<string>("");
  const [sillonId, setSillonId] = useState<string>("");
  const [sede, setSede] = useState<string>("Consultorio");
  const [datos, setDatos] = useState<DatosReportes>(DATOS_INICIALES);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let vigente = true;
    traerReportes({ desde, hasta, profesional_id: "", sillon_id: "", sede: "Consultorio" })
      .then((cargados) => {
        if (vigente) setDatos(cargados);
      })
      .catch((fallo: unknown) => {
        if (vigente) setError(mensajeParaUsuario(fallo));
      });
    return () => {
      vigente = false;
    };
    // Carga inicial con el rango por defecto; los cambios van con "Filtrar".
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rango: RangoFechas = { desde, hasta };

  return (
    <section aria-label="Reportes del consultorio">
      <h1>Reportes</h1>
      {error !== null ? <p role="alert">{error}</p> : null}
      <form
        aria-label="Filtros de reportes"
        onSubmit={(evento) => {
          evento.preventDefault();
          setError(null);
          traerReportes({ desde, hasta, profesional_id: profesionalId, sillon_id: sillonId, sede })
            .then(setDatos)
            .catch((fallo: unknown) => {
              setError(mensajeParaUsuario(fallo));
            });
        }}
      >
        <div>
          <label htmlFor="reportes-desde">Desde</label>
          <input
            id="reportes-desde"
            type="date"
            value={desde}
            onChange={(evento) => { setDesde(evento.target.value); }}
          />
        </div>
        <div>
          <label htmlFor="reportes-hasta">Hasta</label>
          <input
            id="reportes-hasta"
            type="date"
            value={hasta}
            onChange={(evento) => { setHasta(evento.target.value); }}
          />
        </div>
        <div>
          <label htmlFor="reportes-profesional">Profesional</label>
          <select
            id="reportes-profesional"
            value={profesionalId}
            onChange={(evento) => { setProfesionalId(evento.target.value); }}
          >
            <option value="">Todos</option>
            <option value="profesional-propio">Propio</option>
          </select>
        </div>
        <div>
          <label htmlFor="reportes-sillon">Sillon</label>
          <input
            id="reportes-sillon"
            type="text"
            autoComplete="off"
            value={sillonId}
            onChange={(evento) => { setSillonId(evento.target.value); }}
          />
        </div>
        <div>
          <label htmlFor="reportes-sede">Sede</label>
          <input
            id="reportes-sede"
            type="text"
            autoComplete="off"
            value={sede}
            onChange={(evento) => { setSede(evento.target.value); }}
          />
        </div>
        <button type="submit">Filtrar</button>
      </form>
      <BloqueOcupacion datos={datos.ocupacion} />
      <p>
        <button
          type="button"
          onClick={() => { descargarBloque("ocupacion", rango, datos); }}
        >
          Descargar ocupacion
        </button>
      </p>
      <BloqueAusentismo datos={datos.ausentismo} />
      <p>
        <button
          type="button"
          onClick={() => { descargarBloque("ausentismo", rango, datos); }}
        >
          Descargar ausentismo
        </button>
      </p>
      <BloqueIngresos datos={datos.ingresos} />
      <p>
        <button
          type="button"
          onClick={() => { descargarBloque("ingresos", rango, datos); }}
        >
          Descargar ingresos
        </button>
      </p>
    </section>
  );
}

/** Carga de solo-lectura con rango fijo (el scoping lo impone el backend). */
function useCargaReportes(rango: RangoFechas): { readonly datos: DatosReportes; readonly error: string | null } {
  const [datos, setDatos] = useState<DatosReportes>(DATOS_INICIALES);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let vigente = true;
    traerReportes(rango)
      .then((cargados) => {
        if (vigente) setDatos(cargados);
      })
      .catch((fallo: unknown) => {
        if (vigente) setError(mensajeParaUsuario(fallo));
      });
    return () => {
      vigente = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { datos, error };
}

function VistaPropia(): ReactElement {
  const [rango] = useState<RangoFechas>(() => ({ desde: haceDiasAR(7), hasta: hoyAR(new Date()) }));
  // El alcance propio lo impone el backend; el rango es fijo de 7 dias.
  const { datos, error } = useCargaReportes(rango);

  return (
    <section aria-label="Reportes propios">
      <h1>Reportes</h1>
      <p>Mostrando tus reportes propios.</p>
      {error !== null ? <p role="alert">{error}</p> : null}
      <BloqueOcupacion datos={datos.ocupacion} />
      <p>
        <button
          type="button"
          aria-label="Descargar ocupacion propia"
          onClick={() => { descargarBloque("ocupacion", rango, datos); }}
        >
          Descargar CSV
        </button>
      </p>
      <BloqueAusentismo datos={datos.ausentismo} />
      <p>
        <button
          type="button"
          aria-label="Descargar ausentismo propio"
          onClick={() => { descargarBloque("ausentismo", rango, datos); }}
        >
          Descargar CSV
        </button>
      </p>
      <BloqueIngresos datos={datos.ingresos} />
      <p>
        <button
          type="button"
          aria-label="Descargar ingresos propios"
          onClick={() => { descargarBloque("ingresos", rango, datos); }}
        >
          Descargar CSV
        </button>
      </p>
    </section>
  );
}

function VistaDia(): ReactElement {
  const [rango] = useState<RangoFechas>(() => {
    const hoy = hoyAR(new Date());
    return { desde: hoy, hasta: hoy };
  });
  // Recepcion solo ve el dia operativo (el backend lo exige); sin filtros.
  const { datos, error } = useCargaReportes(rango);

  return (
    <section aria-label="Operativo del dia">
      <h1>Reportes</h1>
      <p>Mostrando el operativo de hoy.</p>
      {error !== null ? <p role="alert">{error}</p> : null}
      <BloqueOcupacion datos={datos.ocupacion} />
      <BloqueAusentismo datos={datos.ausentismo} />
      <BloqueIngresos datos={datos.ingresos} />
    </section>
  );
}

function ContenidoReportes({ roles }: { readonly roles: readonly string[] }): ReactElement {
  if (roles.includes("admin")) return <VistaAdmin />;
  if (roles.includes("odontologo")) return <VistaPropia />;
  return <VistaDia />;
}

export function ReportesPage(): ReactElement {
  const sesion = obtenerSesion();
  const roles: readonly string[] = sesion !== null ? sesion.roles : [];
  return (
    <main>
      <RequireRol roles={roles} recurso="reportes">
        {roles.includes("admin") ? <AdminNav /> : null}
        <ContenidoReportes roles={roles} />
      </RequireRol>
    </main>
  );
}
