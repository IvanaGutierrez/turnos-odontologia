// Catálogo centralizado de mensajes en español argentino neutro (design decisión 5).
// Claves por flujo para reutilizar en C-11/C-12. Sin PII jamás (R6).

export const MENSAJES = {
  sesionExpirada: "Sesión inválida. Iniciá sesión nuevamente.",
  credencialesInvalidas: "Credenciales inválidas. Verificá el email y la contraseña.",
  accesoDenegado: "Acceso denegado. No tenés permiso para esta acción.",
  noEncontrado: "No se encontró el recurso solicitado.",
  datosInvalidos: "Datos inválidos. Revisá los campos indicados.",
  esperaRateLimit: "Demasiados intentos. Esperá unos minutos antes de reintentar.",
  errorRed: "Error de red. Revisá tu conexión e intentá nuevamente.",
  errorServidor: "Error del servidor. Intentá nuevamente en unos minutos.",
  errorInesperado: "Ocurrió un error inesperado. Intentá nuevamente.",
  slotOcupado: "El horario ya fue reservado. Elegí otra opción disponible.",
  dniInvalido: "DNI inválido. Ingresá 7 u 8 dígitos sin letras.",
  telefonoInvalido: "Teléfono inválido. Usá el formato +54 seguido del número.",
  usuarioCreado: "Usuario creado correctamente.",
  rolActualizado: "Rol actualizado correctamente.",
  usuarioDesactivado: "Usuario desactivado correctamente.",
  sinResultados: "No hay datos para los filtros elegidos.",
  cargandoSeccion: "Cargando…",
} as const;

export type ClaveMensaje = keyof typeof MENSAJES;
