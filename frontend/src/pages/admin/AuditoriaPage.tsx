// Bitácora consultable solo admin (specs `auditoria/registro-acciones`,
// `frontend/administracion`): filtra por entidad/id/acción/rango y pagina,
// muestra `{hora, usuario, acción, entidad, entidad_id}` sin columnas de
// PII/HC (R6). Sin permiso muestra denegado SIN llamar a la API. Copy en
// español, tablas semánticas, cero `any` (R4).

import { useEffect, useState } from "react";
import type { ReactElement } from "react";
import { RequireRol } from "../../shared/auth/guards";
import { AdminNav } from "./AdminNav";
import { mensajeParaUsuario, obtenerSesion } from "../../shared/auth/auth";
import { ApiError } from "../../shared/api-client/apiClient";
import { MENSAJES } from "../../shared/i18n/es-AR";
import { obtenerAuditoria } from "../../features/admin/apiAdmin";
import type { EventoAuditoria } from "../../features/admin/tipos";

const TAMANO_PAGINA = 20;

const ENTIDADES: readonly string[] = ["turno", "pago", "cierre", "ficha", "usuario", "reporte"];

const ACCIONES: readonly string[] = [
  "turno_creado",
  "turno_cancelado",
  "pago_acreditado",
  "cierre_creado",
  "evolucion_registrada",
  "usuario_creado",
  "rol_cambiado",
  "usuario_desactivado",
];

function traducirErrorAuditoria(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.estado === 401) return MENSAJES.sesionExpirada;
    if (error.estado === 403) return MENSAJES.accesoDenegado;
    if (error.estado === 422) return MENSAJES.datosInvalidos;
    if (error.estado >= 500) return MENSAJES.errorServidor;
    if (error.estado === 0) return MENSAJES.errorRed;
  }
  return mensajeParaUsuario(error);
}

function ContenidoAuditoria(): ReactElement {
  const [eventos, setEventos] = useState<readonly EventoAuditoria[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [entidad, setEntidad] = useState<string>("");
  const [entidadId, setEntidadId] = useState<string>("");
  const [accion, setAccion] = useState<string>("");
  const [desde, setDesde] = useState<string>("");
  const [hasta, setHasta] = useState<string>("");
  const [pagina, setPagina] = useState<number>(1);
  const [cargando, setCargando] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let vigente = true;
    setCargando(true);
    setError(null);
    obtenerAuditoria({
      entidad,
      entidad_id: entidadId,
      accion,
      desde,
      hasta,
      page: pagina,
      page_size: TAMANO_PAGINA,
    })
      .then((resultado) => {
        if (!vigente) return;
        setEventos(resultado.items);
        setTotal(resultado.total);
      })
      .catch((fallo: unknown) => {
        if (!vigente) return;
        setError(traducirErrorAuditoria(fallo));
      })
      .finally(() => {
        if (vigente) setCargando(false);
      });
    return () => {
      vigente = false;
    };
    // Los filtros se aplican con "Filtrar" (evita fetches por tecla).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pagina]);

  function filtrar(): void {
    setPagina(1);
    setCargando(true);
    setError(null);
    obtenerAuditoria({
      entidad,
      entidad_id: entidadId,
      accion,
      desde,
      hasta,
      page: 1,
      page_size: TAMANO_PAGINA,
    })
      .then((resultado) => {
        setEventos(resultado.items);
        setTotal(resultado.total);
      })
      .catch((fallo: unknown) => {
        setError(traducirErrorAuditoria(fallo));
      })
      .finally(() => {
        setCargando(false);
      });
  }

  const hayMas = pagina * TAMANO_PAGINA < total;

  return (
    <section aria-label="Bitácora de auditoría">
      <h1>Auditoría</h1>
      {error !== null ? <p role="alert">{error}</p> : null}
      <form
        aria-label="Filtros de auditoría"
        onSubmit={(evento) => {
          evento.preventDefault();
          filtrar();
        }}
      >
        <div>
          <label htmlFor="auditoria-entidad">Entidad</label>
          <select
            id="auditoria-entidad"
            value={entidad}
            onChange={(evento) => { setEntidad(evento.target.value); }}
          >
            <option value="">Todas</option>
            {ENTIDADES.map((e) => (
              <option key={e} value={e}>
                {e}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="auditoria-entidad-id">ID de entidad</label>
          <input
            id="auditoria-entidad-id"
            name="entidad_id"
            type="text"
            autoComplete="off"
            value={entidadId}
            onChange={(evento) => { setEntidadId(evento.target.value); }}
          />
        </div>
        <div>
          <label htmlFor="auditoria-accion">Acción</label>
          <select
            id="auditoria-accion"
            value={accion}
            onChange={(evento) => { setAccion(evento.target.value); }}
          >
            <option value="">Todas</option>
            {ACCIONES.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="auditoria-desde">Desde</label>
          <input
            id="auditoria-desde"
            name="desde"
            type="date"
            value={desde}
            onChange={(evento) => { setDesde(evento.target.value); }}
          />
        </div>
        <div>
          <label htmlFor="auditoria-hasta">Hasta</label>
          <input
            id="auditoria-hasta"
            name="hasta"
            type="date"
            value={hasta}
            onChange={(evento) => { setHasta(evento.target.value); }}
          />
        </div>
        <button type="submit">Filtrar</button>
      </form>
      {cargando ? (
        <p>{MENSAJES.cargandoSeccion}</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th scope="col">Hora</th>
              <th scope="col">Usuario</th>
              <th scope="col">Acción</th>
              <th scope="col">Entidad</th>
              <th scope="col">ID de entidad</th>
            </tr>
          </thead>
          <tbody>
            {eventos.map((fila) => (
              <tr key={fila.id}>
                <td>{fila.hora}</td>
                <td>{fila.usuario_id ?? "—"}</td>
                <td>{fila.accion}</td>
                <td>{fila.entidad}</td>
                <td>{fila.entidad_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {eventos.length === 0 && !cargando ? <p>{MENSAJES.sinResultados}</p> : null}
      <nav aria-label="Paginación de auditoría">
        <button
          type="button"
          disabled={pagina <= 1}
          onClick={() => { setPagina((p) => Math.max(1, p - 1)); }}
        >
          Anterior
        </button>{" "}
        <button type="button" disabled={!hayMas} onClick={() => { setPagina((p) => p + 1); }}>
          Siguiente
        </button>
      </nav>
    </section>
  );
}

export function AuditoriaPage(): ReactElement {
  const sesion = obtenerSesion();
  const roles: readonly string[] = sesion !== null ? sesion.roles : [];
  return (
    <main>
      <RequireRol roles={roles} recurso="auditoria">
        <AdminNav />
        <ContenidoAuditoria />
      </RequireRol>
    </main>
  );
}
