// Sanitizador central R6 (design decisión 8): elimina DNI, teléfono, historia
// clínica, hashes y tokens de errores, consola y reportes. Ningún componente
// filtra PII por su cuenta: todo pasa por acá.

import { MENSAJES } from "../i18n/es-AR";

const MAX_MENSAJE_VISIBLE = 280;

const PATRONES: ReadonlyArray<readonly [RegExp, string]> = [
  // JWT (tolerante a comillas del JSON serializado).
  [/eyJ[A-Za-z0-9_+=/.:,"'_-]*/g, "[TOKEN]"],
  [/Bearer\s+[^\s"']+/gi, "Bearer [TOKEN]"],
  [/token[-_ ]?p[uú]blico[^\s"']*/gi, "[TOKEN]"],
  [/\btoken[-_]?[A-Za-z0-9-]{4,}\b/gi, "[TOKEN]"],
  [/refresh[_-]?token[^\s"']*/gi, "[SECRETO]"],
  [/argon2[A-Za-z0-9$./=,;:+_-]*/gi, "[SECRETO]"],
  [/contrase[ñn]a[^\s"']*/gi, "[SECRETO]"],
  [/password[^\s"']*/gi, "[SECRETO]"],
  // Clínica: la oración completa, no solo la palabra clave.
  [/historia\s+cl[ií]nica\s*:[^.!?\n]*/gi, "[DATO CLÍNICO]"],
  [/diagn[oó]stico\s*:[^.!?\n]*/gi, "[DATO CLÍNICO]"],
  // Contacto.
  [/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, "[EMAIL]"],
  [/\+54[\d\s().-]{6,}/g, "[TELÉFONO]"],
  // DNI con puntos de miles y 7–8 dígitos corridos.
  [/\b\d{1,2}\.\d{3}\.\d{3}\b/g, "[DNI]"],
  [/\b\d{7,8}\b/g, "[DNI]"],
];

function aTexto(valor: unknown): string {
  if (typeof valor === "string") return valor;
  if (typeof valor === "number" || typeof valor === "boolean" || typeof valor === "bigint") {
    return String(valor);
  }
  if (valor instanceof Error) return valor.message;
  if (valor === null || valor === undefined) return "";
  try {
    const json = JSON.stringify(valor);
    return typeof json === "string" ? json : "[valor no visible]";
  } catch {
    return "";
  }
}

function truncar(texto: string): string {
  if (texto.length <= MAX_MENSAJE_VISIBLE) return texto;
  return `${texto.slice(0, MAX_MENSAJE_VISIBLE - 1)}…`;
}

/** Texto visible/registrable sin PII, truncado a un máximo visible. */
export function sanitizarError(valor: unknown): string {
  let limpio = aTexto(valor);
  for (const [patron, reemplazo] of PATRONES) {
    limpio = limpio.replace(patron, reemplazo);
  }
  limpio = limpio.replace(/\s+/g, " ").trim();
  if (limpio.length === 0) return MENSAJES.errorInesperado;
  return truncar(limpio);
}

/** Reporte de error que nunca incluye PII aunque el error la contenga. */
export function reportarError(error: unknown): void {
  console.error("[turnos]", sanitizarError(error));
}
