// Validadores argentinos (spec `api-client-auth` + R6).
// DNI: 7–8 dígitos (se aceptan puntos de miles). Teléfono: E.164 AR `+54…`.
// Devuelven el valor normalizado/validado o lanzan `Error` en español.

import { MENSAJES } from "../i18n/es-AR";

/** Valida un DNI argentino y devuelve sus dígitos (sin puntos ni espacios). */
export function validarDniAr(dni: string): string {
  const normalizado = dni.replace(/\./g, "").replace(/\s+/g, "");
  if (!/^\d{7,8}$/.test(normalizado)) {
    throw new Error(MENSAJES.dniInvalido);
  }
  return normalizado;
}

/** Valida un teléfono E.164 argentino y devuelve el valor original intacto. */
export function validarTelefonoAr(telefono: string): string {
  const compacto = telefono.replace(/[\s\-.()]/g, "");
  if (!/^\+54\d{10,11}$/.test(compacto)) {
    throw new Error(MENSAJES.telefonoInvalido);
  }
  return telefono;
}
