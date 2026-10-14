// Shell de rutas del MVP C-10 (GREEN): inicio, reserva pública por sede
// (`/reservar/:slug`), autogestión por token (`/gestionar/:token`), pago de
// seña (`/pagar/:token`, C-08), agenda operativa (`/agenda`, C-04) con guarda
// por rol, login del staff y área admin mínima; el comodín guía sin filtrar
// datos.

import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import type { ReactElement } from "react";
import { GestionarTurno } from "./pages/gestionar/GestionarTurno";
import { ReservarPage } from "./pages/reservar/ReservarPage";
import { PagarSena } from "./pages/pagar/PagarSena";
import { AgendaPage } from "./pages/agenda/AgendaPage";
import { LoginPage } from "./pages/login/LoginPage";
import { UsuariosPage } from "./pages/admin/UsuariosPage";
import { AuditoriaPage } from "./pages/admin/AuditoriaPage";
import { ReportesPage } from "./pages/admin/ReportesPage";

function Inicio(): ReactElement {
  return (
    <main>
      <h1>Turnos · Consultorio odontológico</h1>
      <p>Reservá tu turno en tres pasos, sin crear una cuenta.</p>
      <p>
        <Link to="/reservar/consultorio">Reservar turno</Link>
      </p>
    </main>
  );
}

function NoEncontrada(): ReactElement {
  return (
    <main>
      <h1>Página no encontrada</h1>
      <p>La dirección no existe o cambió.</p>
      <p>
        <Link to="/">Volver al inicio</Link>
      </p>
    </main>
  );
}

export function App(): ReactElement {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Inicio />} />
        <Route path="/reservar/:slug" element={<ReservarPage />} />
        <Route path="/gestionar/:token" element={<GestionarTurno />} />
        <Route path="/pagar/:token" element={<PagarSena />} />
        <Route path="/agenda" element={<AgendaPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/admin/usuarios" element={<UsuariosPage />} />
        <Route path="/admin/auditoria" element={<AuditoriaPage />} />
        <Route path="/admin/reportes" element={<ReportesPage />} />
        <Route path="*" element={<NoEncontrada />} />
      </Routes>
    </BrowserRouter>
  );
}
