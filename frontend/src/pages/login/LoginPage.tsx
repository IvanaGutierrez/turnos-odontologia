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
  const [email, setEmail] = useState<string>("");
  const [contrasena, setContrasena] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState<boolean>(false);

  async function entrar(): Promise<void> {
    if (enviando) return;
    setEnviando(true);
    setError(null);
    try {
      const sesion = await iniciarSesion({ email, password: contrasena });
      navegar(areaPorRol(sesion.roles[0] ?? ""));
    } catch (fallo) {
      setError(fallo instanceof Error ? fallo.message : "Ocurrió un error inesperado.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <main>
      <h1>Iniciar sesión</h1>
      {error !== null ? <p role="alert">{error}</p> : null}
      <form
        onSubmit={(evento) => {
          evento.preventDefault();
          void entrar();
        }}
      >
        <div>
          <label htmlFor="login-email">Email</label>
          <input
            id="login-email"
            name="email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(evento) => { setEmail(evento.target.value); }}
          />
        </div>
        <div>
          <label htmlFor="login-contrasena">Contraseña</label>
          <input
            id="login-contrasena"
            name="password"
            type="password"
            autoComplete="current-password"
            value={contrasena}
            onChange={(evento) => { setContrasena(evento.target.value); }}
          />
        </div>
        <button type="submit" disabled={enviando}>
          Iniciar sesión
        </button>
      </form>
    </main>
  );
}
