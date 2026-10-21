"""Configuración centralizada del proyecto.

Lee variables de entorno desde .env y las expone como un objeto `settings`.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


# src/merchbot/config.py -> raíz del proyecto
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # --- Gemini ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # --- Telegram ---
    telegram_bot_token: str = ""
    # IDs de usuarios autorizados a usar el bot, separados por coma.
    # Si está vacío -> el bot funciona en "modo abierto" (cualquiera lo usa).
    # Para obtener el ID de un usuario: que escriba /whoami al bot.
    telegram_allowed_user_ids: str = ""

    # Rate limiting para usuarios NO autorizados (anti-spam).
    # Después de unauth_max_attempts rechazos en unauth_window_minutes,
    # el bot deja de responderle (silenciosamente) hasta que pase la ventana.
    # Los usuarios autorizados NO tienen rate limit.
    unauth_max_attempts: int = 3
    unauth_window_minutes: int = 10

    @property
    def allowed_user_ids_set(self) -> set[int]:
        """Devuelve los IDs autorizados como set de ints, ignorando basura."""
        if not self.telegram_allowed_user_ids.strip():
            return set()
        ids = set()
        for raw in self.telegram_allowed_user_ids.split(","):
            raw = raw.strip()
            if raw.isdigit():
                ids.add(int(raw))
        return ids

    # --- Origen de los datos ---
    # "sheets": sincroniza desde Google Sheets (requiere SHEETS_ID).
    # "demo":   carga la planilla de ejemplo data/Stock_Merchandising_Demo.xlsx.
    # "auto":   sheets si hay SHEETS_ID, demo si no.
    data_source: str = "auto"
    demo_xlsx_path: Path = BASE_DIR / "data" / "Stock_Merchandising_Demo.xlsx"

    @property
    def fuente_de_datos(self) -> str:
        fuente = self.data_source.strip().lower()
        if fuente == "auto":
            return "sheets" if self.sheets_id.strip() else "demo"
        if fuente not in ("sheets", "demo"):
            raise ValueError(f"DATA_SOURCE inválido: {self.data_source!r} (usá auto, sheets o demo)")
        return fuente

    # --- Google Sheets ---
    sheets_id: str = ""
    sheets_stock_tab: str = "Stock"
    sheets_pedidos_tab: str = "Pedidos"
    sync_interval_min: int = 15

    # --- DB ---
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'merchbot.db'}"

    # --- Web ---
    # 127.0.0.1 = solo accesible desde esta máquina. En Docker se usa 0.0.0.0
    # y el puerto se publica solo en localhost (ver docker-compose.yml).
    web_host: str = "127.0.0.1"
    web_port: int = 8000

    # --- App ---
    log_level: str = "INFO"
    app_env: str = "development"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
