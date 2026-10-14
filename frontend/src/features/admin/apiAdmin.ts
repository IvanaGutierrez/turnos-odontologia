// Acceso a usuarios y bitácora (C-11) desde las páginas `/admin/*`.
// Reutiliza el cliente con sesión en memoria (R2-front); los errores se
// traducen a mensajes genéricos en español en las páginas (R6).
// Cero `any` (R4).

import type { ParametrosConsulta } from "../../shared/api-client/apiClient";
import { clienteSesion } from "../../shared/auth/auth";
import type {
  FiltrosAuditoria,
  NuevoUsuario,
  PaginaAuditoria,
  PaginaUsuarios,
  RolStaff,
  UsuarioAdmin,
} from "./tipos";
import {
  esRolStaff,
  normalizarPaginaAuditoria,
  normalizarPaginaUsuarios,
  normalizarUsuario,
} from "./tipos";

const cliente = clienteSesion();

/** `GET /api/v1/usuarios` paginado (solo admin; otro rol → 403). */
export async function listarUsuarios(page: number, pageSize: number): Promise<PaginaUsuarios> {
  const params: ParametrosConsulta = {
    page: String(page),
    page_size: String(pageSize),
  };
  const respuesta = await cliente.get<unknown>("/usuarios", params);
  return normalizarPaginaUsuarios(respuesta);
}

/** `POST /api/v1/usuarios` (solo admin; 201 sin `password_hash` — R6). */
export async function crearUsuario(nuevo: NuevoUsuario): Promise<UsuarioAdmin> {
  const respuesta = await cliente.post<unknown>("/usuarios", {
    email: nuevo.email,
    rol: nuevo.rol,
    password: nuevo.password,
  });
  const fila = normalizarUsuario(respuesta);
  if (fila === null) throw new Error("Respuesta de alta inválida.");
  return fila;
}

export interface CambiosUsuario {
  readonly rol?: RolStaff;
  readonly activo?: boolean;
}

/** `PATCH /api/v1/usuarios/:id` (cambiar rol y/o activo, solo admin). */
export async function actualizarUsuario(id: string, cambios: CambiosUsuario): Promise<UsuarioAdmin> {
  const cuerpo: Record<string, string | boolean> = {};
  if (cambios.rol !== undefined && esRolStaff(cambios.rol)) cuerpo["rol"] = cambios.rol;
  if (cambios.activo !== undefined) cuerpo["activo"] = cambios.activo;
  const respuesta = await cliente.patch<unknown>(`/usuarios/${encodeURIComponent(id)}`, cuerpo);
  const fila = normalizarUsuario(respuesta);
  if (fila === null) throw new Error("Respuesta de actualización inválida.");
  return fila;
}

/** `DELETE /api/v1/usuarios/:id` (baja lógica → `activo=false`, solo admin). */
export async function desactivarUsuario(id: string): Promise<UsuarioAdmin> {
  const respuesta = await cliente.del<unknown>(`/usuarios/${encodeURIComponent(id)}`);
  const fila = normalizarUsuario(respuesta);
  if (fila === null) throw new Error("Respuesta de baja inválida.");
  return fila;
}

/** `GET /api/v1/auditoria` filtrable y paginada (solo admin). */
export async function obtenerAuditoria(filtros: FiltrosAuditoria): Promise<PaginaAuditoria> {
  const params: ParametrosConsulta = {};
  if (filtros.entidad !== undefined && filtros.entidad !== "") params["entidad"] = filtros.entidad;
  if (filtros.entidad_id !== undefined && filtros.entidad_id !== "") {
    params["entidad_id"] = filtros.entidad_id;
  }
  if (filtros.accion !== undefined && filtros.accion !== "") params["accion"] = filtros.accion;
  if (filtros.desde !== undefined && filtros.desde !== "") params["desde"] = filtros.desde;
  if (filtros.hasta !== undefined && filtros.hasta !== "") params["hasta"] = filtros.hasta;
  params["page"] = String(filtros.page ?? 1);
  params["page_size"] = String(filtros.page_size ?? 20);
  const respuesta = await cliente.get<unknown>("/auditoria", params);
  return normalizarPaginaAuditoria(respuesta);
}
