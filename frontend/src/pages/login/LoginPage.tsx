// Inicio de sesión del staff (spec `api-client-auth`): email + contraseña
// contra C-02, errores 401/403/429 sanitizados en español (R6), y redirección
// al área del rol. Sin persistencia: el access queda en memoria (R7).

import { useState } from "react";
import type { ReactElement } from "react";
import { useNavigate } from "react-router-dom";
import { areaPorRol } from "../../shared/auth/guards";
import { iniciarSesion } from "../../shared/auth/auth";

export function LoginPage(): ReactElement {
  const navegar = useNavigate();
  const [email, setEmail] = useState<string>("admin.demo@consultorio.example");
  const [contrasena, setContrasena] = useState<string>("cambiar-esta-demo-no-real");
  const [mostrarPassword, setMostrarPassword] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState<boolean>(false);

  async function entrar(): Promise<void> {
    if (enviando) return;
    setEnviando(true);
    setError(null);
    try {
      const sesion = await iniciarSesion({
        email: email.trim(),
        password: contrasena.trim(),
      });
      navegar(areaPorRol(sesion.roles[0] ?? ""));
    } catch (fallo) {
      setError(fallo instanceof Error ? fallo.message : "Ocurrió un error inesperado.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <main style={{ maxWidth: "420px", margin: "2rem auto", padding: "1.5rem" }}>
      <h1>Iniciar sesión</h1>
      {error !== null ? <p role="alert" style={{ color: "#b91c1c" }}>{error}</p> : null}
      <form
        onSubmit={(evento) => {
          evento.preventDefault();
          void entrar();
        }}
      >
        <div style={{ marginBottom: "1rem" }}>
          <label htmlFor="login-email" style={{ display: "block", marginBottom: "0.25rem" }}>Email</label>
          <input
            id="login-email"
            name="email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(evento) => { setEmail(evento.target.value); }}
            style={{ width: "100%", padding: "0.5rem", boxSizing: "border-box" }}
          />
        </div>
        <div style={{ marginBottom: "1rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.25rem" }}>
            <label htmlFor="login-contrasena">Contraseña</label>
            <button
              type="button"
              onClick={() => { setMostrarPassword((prev) => !prev); }}
              style={{ background: "none", border: "none", color: "#2563eb", cursor: "pointer", fontSize: "0.8rem", padding: 0 }}
            >
              {mostrarPassword ? "Ocultar" : "Mostrar"}
            </button>
          </div>
          <input
            id="login-contrasena"
            name="password"
            type={mostrarPassword ? "text" : "password"}
            autoComplete="current-password"
            value={contrasena}
            onChange={(evento) => { setContrasena(evento.target.value); }}
            style={{ width: "100%", padding: "0.5rem", boxSizing: "border-box" }}
          />
        </div>
        <button type="submit" disabled={enviando} style={{ width: "100%", padding: "0.6rem", cursor: "pointer" }}>
          {enviando ? "Iniciando sesión..." : "Iniciar sesión"}
        </button>
      </form>

      <div style={{ marginTop: "1.5rem", padding: "0.85rem", background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "6px" }}>
        <p style={{ fontSize: "0.85rem", fontWeight: "600", margin: "0 0 0.5rem 0", color: "#334155" }}>
          Accesos rápidos de prueba (Demo):
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
          <button
            type="button"
            onClick={() => {
              setEmail("admin.demo@consultorio.example");
              setContrasena("cambiar-esta-demo-no-real");
            }}
            style={{ textAlign: "left", fontSize: "0.8rem", padding: "0.35rem 0.6rem", cursor: "pointer", background: "#fff", border: "1px solid #cbd5e1", borderRadius: "4px" }}
          >
            🔑 <strong>Admin</strong> (admin.demo@consultorio.example)
          </button>
          <button
            type="button"
            onClick={() => {
              setEmail("recepcion.demo@consultorio.example");
              setContrasena("cambiar-esta-demo-no-real");
            }}
            style={{ textAlign: "left", fontSize: "0.8rem", padding: "0.35rem 0.6rem", cursor: "pointer", background: "#fff", border: "1px solid #cbd5e1", borderRadius: "4px" }}
          >
            🔑 <strong>Recepción</strong> (recepcion.demo@consultorio.example)
          </button>
          <button
            type="button"
            onClick={() => {
              setEmail("odontologo.demo@consultorio.example");
              setContrasena("cambiar-esta-demo-no-real");
            }}
            style={{ textAlign: "left", fontSize: "0.8rem", padding: "0.35rem 0.6rem", cursor: "pointer", background: "#fff", border: "1px solid #cbd5e1", borderRadius: "4px" }}
          >
            🔑 <strong>Odontólogo</strong> (odontologo.demo@consultorio.example)
          </button>
        </div>
      </div>
    </main>
  );
}
