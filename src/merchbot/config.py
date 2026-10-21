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
    # Modelos de respaldo, separados por coma: si el principal se queda sin cuota
    # (429) o fue dado de baja (404), la consulta sigue con el siguiente.
    gemini_modelos_respaldo: str = ""

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

    # --- RAG de políticas ---
    politicas_path: Path = BASE_DIR / "data" / "politicas.md"
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensiones: int = 768
    rag_top_k: int = 3
    # Similitud de coseno mínima para considerar relevante un fragmento.
    rag_min_score: float = 0.55

    # --- Sentimiento y prioridad de reclamos ---
    # "auto": transformers si está instalado (pip install -e ".[nlp]"), si no el léxico propio.
    sentimiento_motor: str = "auto"
    sentimiento_modelo: str = "pysentimiento/robertuito-sentiment-analysis"

    # --- Horario de atención humana ---
    # Fuera de este horario el asistente atiende igual y lo aclara; los reclamos
    # quedan registrados para que una persona los vea el próximo día hábil.
    timezone: str = "America/Argentina/Buenos_Aires"
    atencion_desde: str = "09:00"
    atencion_hasta: str = "18:00"
    atencion_dias: str = "0,1,2,3,4"   # 0 = lunes ... 6 = domingo

    # --- Seguridad de la web ---
    # Usuarios del chat: "ana:clave,beto:pbkdf2_sha256$..." (ver `merchbot hashear-clave`).
    # Vacío = chat abierto, solo para usar en tu máquina.
    chat_usuarios: str = ""
    # Clave para firmar las sesiones. Vacía = se genera una al arrancar (las sesiones
    # se cierran al reiniciar). Generala con: python -c "import secrets; print(secrets.token_hex(32))"
    secret_key: str = ""
    sesion_horas: int = 12
    limite_chat_por_minuto: int = 20
    limite_login_intentos: int = 5
    limite_login_minutos: int = 5
    # IPs de proxies cuyo X-Forwarded-For se acepta (para el límite por IP detrás de Caddy/nginx).
    proxies_confiables: str = "127.0.0.1"

    # --- Panel admin (/admin) ---
    # Sin clave, el panel queda deshabilitado.
    admin_key: str = ""

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
