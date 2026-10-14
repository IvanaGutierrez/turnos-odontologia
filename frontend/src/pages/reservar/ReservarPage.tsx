// Ruta `/reservar/:slug`: compone el stepper con datos reales.
// Carga disponibilidad + catálogos en paralelo (`Promise.all`, design 7);
// ante un corte, avisa y ofrece el catálogo inicial para no bloquear.
// Copy en español, cero `any` (R4).

import { useEffect, useState } from "react";
import type { ReactElement } from "react";
import { Link, useParams } from "react-router-dom";
import { mensajeParaUsuario } from "../../shared/auth/auth";
import { obtenerDisponibilidad } from "../../features/reserva-publica/apiReserva";
import { ReservaStepper } from "../../features/reserva-publica/ReservaStepper";
import {
  CATALOGO_PRESTACIONES,
  SLOTS_INICIALES,
  type SlotLibre,
} from "../../features/reserva-publica/tipos";

export function ReservarPage(): ReactElement {
  const { slug } = useParams();
  const [slots, setSlots] = useState<readonly SlotLibre[] | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    async function cargar(): Promise<void> {
      try {
        // Disponibilidad (red) + catálogos (locales) en paralelo: sin waterfall.
        const [disponibilidad] = await Promise.all([
          obtenerDisponibilidad(),
          Promise.resolve(CATALOGO_PRESTACIONES),
        ]);
        if (vivo) setSlots(disponibilidad);
      } catch (error) {
        if (vivo) {
          setAviso(mensajeParaUsuario(error));
          setSlots(SLOTS_INICIALES);
        }
      }
    }
    void cargar();
    return () => {
      vivo = false;
    };
  }, []);

  if (slug === undefined || slug === "") {
    return (
      <main>
        <h1>No encontramos esa sede</h1>
        <p>Revisá el enlace o empezá de nuevo desde el consultorio.</p>
        <p>
          <Link to="/">Volver al inicio</Link>
        </p>
      </main>
    );
  }

  if (slots === null) {
    return (
      <main>
        <h1>Reservar turno</h1>
        <p>Cargando disponibilidad…</p>
      </main>
    );
  }

  return (
    <main>
      <h1>Reservar turno</h1>
      {aviso !== null ? <p role="alert">{aviso}</p> : null}
      <ReservaStepper slug={slug} slotsIniciales={slots} />
    </main>
  );
}
