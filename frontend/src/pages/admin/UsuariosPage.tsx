// Gestión de usuarios solo admin (specs `admin/gestion-usuarios`,
// `frontend/administracion`): lista/pagina, crea (email+rol+password),
// cambia rol y desactiva con confirmación. Sin permiso muestra denegado SIN
// llamar a la API (la lista solo se monta tras la guarda). Copy en español,
// tablas semánticas, cero `any` (R4), sin PII/HC ni secretos en pantalla (R6).

import { useEffect, useState } from "react";
import type { ReactElement } from "react";
import { RequireRol } from "../../shared/auth/guards";
import { AdminNav } from "./AdminNav";
import { mensajeParaUsuario, obtenerSesion } from "../../shared/auth/auth";
import { ApiError } from "../../shared/api-client/apiClient";
import { MENSAJES } from "../../shared/i18n/es-AR";
import {
  actualizarUsuario,
  crearUsuario,
  desactivarUsuario,
  listarUsuarios,
} from "../../features/admin/apiAdmin";
import type { RolStaff, UsuarioAdmin } from "../../features/admin/tipos";
import { esRolStaff, ROLES_STAFF } from "../../features/admin/tipos";

const TAMANO_PAGINA = 20;
const CONTRASENA_INICIAL = "Ficticia-segura-01";

function traducirErrorUsuarios(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.estado === 401) return MENSAJES.sesionExpirada;
    if (error.estado === 403) return MENSAJES.accesoDenegado;
    if (error.estado === 404) return MENSAJES.noEncontrado;
    if (error.estado === 409) return "El email ya está registrado.";
    if (error.estado === 422) return MENSAJES.datosInvalidos;
    if (error.estado >= 500) return MENSAJES.errorServidor;
    if (error.estado === 0) return MENSAJES.errorRed;
  }
  return mensajeParaUsuario(error);
}

function GestionUsuarios(): ReactElement {
  const [usuarios, setUsuarios] = useState<readonly UsuarioAdmin[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [pagina, setPagina] = useState<number>(1);
  const [cargando, setCargando] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [mostrarFormulario, setMostrarFormulario] = useState<boolean>(false);
  const [email, setEmail] = useState<string>("");
  const [rol, setRol] = useState<RolStaff>("recepcion");
  const [contrasena, setContrasena] = useState<string>(CONTRASENA_INICIAL);
  const [confirmarId, setConfirmarId] = useState<string | null>(null);
  const [procesando, setProcesando] = useState<boolean>(false);

  useEffect(() => {
    let vigente = true;
    setCargando(true);
    setError(null);
    listarUsuarios(pagina, TAMANO_PAGINA)
      .then((resultado) => {
        if (!vigente) return;
        setUsuarios(resultado.items);
        setTotal(resultado.total);
      })
      .catch((fallo: unknown) => {
        if (!vigente) return;
        setError(traducirErrorUsuarios(fallo));
      })
      .finally(() => {
        if (vigente) setCargando(false);
      });
    return () => {
      vigente = false;
    };
  }, [pagina]);

  async function guardar(): Promise<void> {
    if (procesando) return;
    setProcesando(true);
    setError(null);
    setAviso(null);
    try {
      await crearUsuario({ email: email.trim(), rol, password: contrasena });
      setEmail("");
      setRol("recepcion");
      setContrasena(CONTRASENA_INICIAL);
      setMostrarFormulario(false);
      const resultado = await listarUsuarios(pagina, TAMANO_PAGINA);
      setUsuarios(resultado.items);
      setTotal(resultado.total);
      setAviso(MENSAJES.usuarioCreado);
    } catch (fallo) {
      setError(traducirErrorUsuarios(fallo));
    } finally {
      setProcesando(false);
    }
  }

  async function cambiarRol(id: string, nuevoRol: string): Promise<void> {
    if (!esRolStaff(nuevoRol)) {
      setError(MENSAJES.datosInvalidos);
      return;
    }
    setError(null);
    setAviso(null);
    try {
      const fila = await actualizarUsuario(id, { rol: nuevoRol });
      setUsuarios((previas) => previas.map((u) => (u.id === fila.id ? fila : u)));
      setAviso(MENSAJES.rolActualizado);
    } catch (fallo) {
      setError(traducirErrorUsuarios(fallo));
    }
  }

  async function confirmarDesactivacion(id: string): Promise<void> {
    if (procesando) return;
    setProcesando(true);
    setError(null);
    setAviso(null);
    try {
      const fila = await desactivarUsuario(id);
      setUsuarios((previas) => previas.map((u) => (u.id === fila.id ? fila : u)));
      setConfirmarId(null);
      setAviso(MENSAJES.usuarioDesactivado);
    } catch (fallo) {
      setError(traducirErrorUsuarios(fallo));
    } finally {
      setProcesando(false);
    }
  }

  const hayMas = pagina * TAMANO_PAGINA < total;

  return (
    <section aria-label="Gestión de usuarios">
      <h1>Usuarios</h1>
      {aviso !== null ? <p role="status">{aviso}</p> : null}
      {error !== null ? <p role="alert">{error}</p> : null}
      <p>
        <button type="button" onClick={() => { setMostrarFormulario((v) => !v); }}>
          Crear usuario
        </button>
      </p>
      {mostrarFormulario ? (
        <form
          aria-label="Alta de usuario"
          onSubmit={(evento) => {
            evento.preventDefault();
            void guardar();
          }}
        >
          <div>
            <label htmlFor="nuevo-usuario-email">Email</label>
            <input
              id="nuevo-usuario-email"
              name="email"
              type="email"
              autoComplete="off"
              value={email}
              onChange={(evento) => { setEmail(evento.target.value); }}
            />
          </div>
          <div>
            <label htmlFor="nuevo-usuario-rol">Rol</label>
            <select
              id="nuevo-usuario-rol"
              value={rol}
              onChange={(evento) => {
                const elegido: string = evento.target.value;
                if (esRolStaff(elegido)) setRol(elegido);
              }}
            >
              {ROLES_STAFF.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="nuevo-usuario-contrasena">Contraseña</label>
            <input
              id="nuevo-usuario-contrasena"
              name="password"
              type="password"
              autoComplete="new-password"
              value={contrasena}
              onChange={(evento) => { setContrasena(evento.target.value); }}
            />
          </div>
          <button type="submit" disabled={procesando}>
            Guardar
          </button>
        </form>
      ) : null}
      {cargando ? (
        <p>{MENSAJES.cargandoSeccion}</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th scope="col">Email</th>
              <th scope="col">Rol</th>
              <th scope="col">Estado</th>
              <th scope="col">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {usuarios.map((fila, indice) => (
              <tr key={fila.id}>
                <td>{fila.email}</td>
                <td>
                  <label htmlFor={`rol-${fila.id}`}>Rol (fila {indice + 1})</label>
                  <select
                    id={`rol-${fila.id}`}
                    value={esRolStaff(fila.rol) ? fila.rol : "recepcion"}
                    onChange={(evento) => { void cambiarRol(fila.id, evento.target.value); }}
                  >
                    {ROLES_STAFF.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                </td>
                <td>{fila.activo ? "Activa" : "Inactiva"}</td>
                <td>
                  {fila.activo ? (
                    <button type="button" onClick={() => { setConfirmarId(fila.id); }}>
                      Desactivar
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {usuarios.length === 0 && !cargando ? <p>{MENSAJES.sinResultados}</p> : null}
      {confirmarId !== null ? (
        <section aria-label="Confirmar desactivación">
          <p>Confirmar desactivación: la cuenta quedará inactiva y no podrá iniciar sesión.</p>
          <p>
            <button
              type="button"
              disabled={procesando}
              onClick={() => { void confirmarDesactivacion(confirmarId); }}
            >
              Sí, desactivar
            </button>{" "}
            <button type="button" onClick={() => { setConfirmarId(null); }}>
              Cancelar
            </button>
          </p>
        </section>
      ) : null}
      <nav aria-label="Paginación de usuarios">
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

export function UsuariosPage(): ReactElement {
  const sesion = obtenerSesion();
  const roles: readonly string[] = sesion !== null ? sesion.roles : [];
  return (
    <main>
      <RequireRol roles={roles} recurso="usuarios">
        <AdminNav />
        <GestionUsuarios />
      </RequireRol>
    </main>
  );
}
