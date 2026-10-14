"""Matriz única de permisos (espejo de `03_actores_y_roles.md`).

Roles internos: `admin`, `odontologo`, `recepcion`. Deny-by-default: toda
combinación no listada se deniega con 403 genérico + auditoría. C-11 la
reusa en reportes; RLS no se introduce (design §8).
"""

from __future__ import annotations

ROL_ADMIN = "admin"
ROL_ODONTOLOGO = "odontologo"
ROL_RECEPCION = "recepcion"

ROLES_VALIDOS: frozenset[str] = frozenset({ROL_ADMIN, ROL_ODONTOLOGO, ROL_RECEPCION})

# Recurso → roles habilitados (matriz §RBAC de la KB).
MATRIZ_PERMISOS: dict[str, frozenset[str]] = {
    # Gestión de usuarios y roles: solo admin (KB: CRUD admin, resto —).
    "usuarios": frozenset({ROL_ADMIN}),
    # Configuración de agenda: admin CRUD; odontólogo solo propia; recep. R.
    "configuracion_agenda": frozenset({ROL_ADMIN}),
    "agenda_propia": frozenset({ROL_ADMIN, ROL_ODONTOLOGO}),
    # Turnos: admin/recepción CRUD; odontólogo sus propios (check-in clínico).
    "turnos": frozenset({ROL_ADMIN, ROL_ODONTOLOGO, ROL_RECEPCION}),
    # C-07 clínica (RN-CL-04): escritura clínica solo odontólogo.
    # `admin` NO entra en `ficha_clinica|odontograma|evolucion` (test 1.2
    # exige `GET /fichas/:id` con admin → 403; el admin audita en C-11).
    # Desvío documentado respecto al "admin(R)" de design §6: esa R es
    # lectura de auditoría, no de HCE directa (Ley 25.326 minimización).
    "ficha_clinica": frozenset({ROL_ODONTOLOGO}),
    "odontograma": frozenset({ROL_ODONTOLOGO}),
    "evolucion": frozenset({ROL_ODONTOLOGO}),
    # Presupuesto/planes: odontólogo crea/firma; admin lee para caja/C-11.
    "presupuesto": frozenset({ROL_ADMIN, ROL_ODONTOLOGO}),
    "plan_tratamiento": frozenset({ROL_ADMIN, ROL_ODONTOLOGO}),
    # Contacto del paciente: recepción edita (nombre/teléfono), clínica no.
    "pacientes": frozenset({ROL_ADMIN, ROL_ODONTOLOGO, ROL_RECEPCION}),
    # C-09 caja y cierre diario (RN-PA-04/05): movimientos, cierre y
    # consultas solo `admin|recepcion`; reapertura solo `admin`.
    # Odontólogo → `403` en todo caja (deny-by-default intacto).
    "caja": frozenset({ROL_ADMIN, ROL_RECEPCION}),
    "reapertura_caja": frozenset({ROL_ADMIN}),
    # Exportación Ley 25.326: el gate fino es ser tratante (firmante);
    # la matriz solo deja pasar a odontólogo, el servicio decide (R6).
    "exportacion_datos": frozenset({ROL_ODONTOLOGO}),
    # C-13 validación OS preventiva (RN-OS-01/02): validar la puede el
    # staff clínico-administrativo (el odontólogo necesita la cobertura
    # antes de atender); el padrón de afiliaciones es administrativo
    # (odontólogo → `403`, el padrón no es lectura clínica).
    "obras_sociales": frozenset({ROL_ADMIN, ROL_ODONTOLOGO, ROL_RECEPCION}),
    "afiliaciones": frozenset({ROL_ADMIN, ROL_RECEPCION}),
    # C-11 roles/reportes/auditoría: bitácora legible solo admin; reportes agregados por rol con scoping
    # en servicio; CSV sin recepción (superficie de fuga PII).
    "auditoria": frozenset({ROL_ADMIN}),
    "reportes": frozenset({ROL_ADMIN, ROL_ODONTOLOGO, ROL_RECEPCION}),
    "reportes_csv": frozenset({ROL_ADMIN, ROL_ODONTOLOGO}),
}


def puede(rol: str, recurso: str) -> bool:
    """`True` si el rol opera el recurso; desconocidos → `False` (deny)."""
    habilitados = MATRIZ_PERMISOS.get(recurso)
    if habilitados is None:
        return False
    return rol in habilitados
