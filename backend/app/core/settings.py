"""Configuración por variables de entorno (R7: jamás hardcodear secretos)."""

from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://turnos:turnos@localhost:5432/turnos"
    test_database_url: str = (
        "postgresql+asyncpg://turnos:turnos@localhost:5432/turnos_test"
    )
    slot_minutes_before: int = 120
    slot_minutes_after: int = 120
    slot_limit: int = 5
    seed_demo: bool = False
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"

    # --- C-02 auth JWT (fail-fast: sin JWT_SECRET válido la app no levanta) ---
    jwt_secret: str = ""
    jwt_access_min: int = 15
    jwt_refresh_days: int = 7

    # --- C-02 Redis (prod: compose; tests: fakeredis vía capa de abstracción) ---
    redis_url: str = "redis://localhost:6379/0"
    usar_redis_falso: bool = False

    # --- C-02 rate limit + bloqueo (claves, topes y TTLs parametrizados) ---
    rate_login_max: int = 5
    rate_login_window_s: int = 60
    lockout_max_intentos: int = 10
    lockout_s: int = 900

    # --- C-02 cookie de refresh (secure=true por default; solo dev la apaga) ---
    cookie_secure: bool = True

    # --- C-03 agenda pública (topes/ventanas por env; secretos jamás en código) ---
    dispon_max_dias: int = 30
    rate_public_ip_max: int = 60
    rate_public_ip_window_s: int = 60
    rate_public_tel_max: int = 10
    rate_public_tel_window_s: int = 60
    verif_ttl_min: int = 10
    verif_max_intentos: int = 5
    verif_lock_s: int = 900
    idempotencia_ttl_h: int = 24
    # Firma opaca del link de seña (placeholder no real; C-08 define el cobro).
    pago_link_secret: str = "cambiar-firma-link-sena-no-real-32b-min"
    pago_link_base: str = "https://pagos.ejemplo.local/sena"

    # --- C-04 grilla día/semana (ventana máxima y tope de items por env) ---
    agenda_semana_max_dias: int = 7
    agenda_grilla_max_items: int = 500

    # --- C-05 autogestión (antelación de cancelación + texto de política) ---
    cancel_min_hours: int = 12
    cancel_policy_text: str = (
        "Podés cancelar o reprogramar hasta 12 h antes del turno. "
        "Pasado ese plazo, comunicate con el consultorio."
    )

    # --- C-06 recordatorios WhatsApp (todo secreto por env, R7) ---
    # Placeholders no reales: prod los pisa por env (ver `.env.example`).
    # Los valores de verificación/firma igualan a los fakes de la suite.
    whatsapp_token: str = "cambiar-token-whatsapp-no-real"
    whatsapp_phone_id: str = "cambiar-phone-id-whatsapp-no-real"
    whatsapp_verify_token: str = "token-verificacion-ficticio-no-real"
    whatsapp_webhook_secret: str = "secreto-webhook-ficticio-no-real-32b-min"
    wa_template_confirm: str = "confirmacion_utility"
    wa_template_24h: str = "recordatorio_24h_utility"
    wa_template_3h: str = "aviso_3h_utility"
    # C-14 lista de espera: 4.º tipo utility (oferta de hueco liberado).
    wa_template_oferta: str = "oferta_lista_espera_utility"
    # C-14: top-N ofertados por hueco + TTL de cada oferta pendiente.
    lista_espera_top_n: int = 3
    lista_espera_oferta_ttl_min: int = 30
    recordatorio_24h_min: int = 1440
    aviso_3h_min: int = 180
    wa_timeout_s: float = 10.0
    wa_max_reintentos: int = 5
    wa_backoff_base_s: float = 60.0
    wa_transport: str = "fake"
    wa_dry_run: bool = True
    smtp_url: str = "smtp://localhost:1025"
    sms_gateway_key: str = "cambiar-sms-gateway-key-no-real"

    # --- C-07 HCE cifrada (clave 32+ bytes solo por env, fail-fast, R7) ---
    # `HCE_CIFRADO_KEY` es la clave vigente (`clave_id=hce-v1`);
    # `HCE_CIFRADO_KEY_ANTERIOR` (opcional) abre ventana de gracia en
    # lectura durante la rotación (runbook en design §Decisión 2).
    # Solo placeholders en `.env.example`; jamás secretos en código.
    hce_cifrado_key: str = ""
    hce_cifrado_key_anterior: str | None = None

    # --- C-08 seña Mercado Pago (todo secreto por env, R7) ---
    # Placeholders no reales: prod los pisa por env (ver `.env.example`).
    # `mp_client=fake` (default, dev/tests: jamás red real, R0/R5) usa el
    # `FakeMercadoPagoClient` inyectado en `app.state.mp_fake`; `http`
    # (prod) exige secretos y falla en arranque sin ellos (fail-fast).
    mp_client: str = "fake"
    mp_access_token: str = ""
    mp_webhook_secret: str = "secreto-mp-webhook-ficticio-no-real-32b"
    mp_timeout_s: float = 10.0
    mp_public_key: str | None = None
    # Moneda fija de las señas (el monto vive por prestación, nunca global).
    sena_moneda: str = "ARS"

    # --- C-09 caja y cierre diario (zona operativa, solo env — R7) ---
    # `CAJA_TZ` default zona AR (no sensible); la fecha operativa del
    # pago (`webhook_recibido_at`) se interpreta en esta zona.
    caja_tz: str = "America/Argentina_Buenos_Aires"

    # --- C-12 conversación WhatsApp (efímero en Redis, sin secretos — R7) ---
    # `wa:conv:{hash}` con TTL minutos; rate por remitente-hash.
    wa_conv_ttl_min: int = 60
    wa_conv_rate_max: int = 30
    wa_conv_rate_window_s: int = 60

    @model_validator(mode="after")
    def _validar_secreto(self) -> Self:
        """Fail-fast (R7): la app no levanta sin `JWT_SECRET` de 32+ bytes."""
        if len(self.jwt_secret) < 32:
            raise ValueError(
                "JWT_SECRET de 32+ bytes es obligatorio (ver .env.example)."
            )
        if len(self.hce_cifrado_key) < 32:
            raise ValueError(
                "HCE_CIFRADO_KEY de 32+ bytes es obligatoria (ver .env.example)."
            )
        if self.mp_client not in ("fake", "http"):
            raise ValueError("MP_CLIENT debe ser 'fake' o 'http' (ver .env.example).")
        if self.mp_client == "http" and (
            not self.mp_access_token or not self.mp_webhook_secret
        ):
            raise ValueError(
                "MP_ACCESS_TOKEN y MP_WEBHOOK_SECRET son obligatorios "
                "con MP_CLIENT=http (ver .env.example)."
            )
        return self


settings = Settings()
