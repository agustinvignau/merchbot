"""Entry point del MerchBot.

Flujo de arranque:
1. Inicializa la DB.
2. Sync inicial con Google Sheets (vía scheduler).
3. Programa sync recurrente cada SYNC_INTERVAL_MIN minutos.
4. Arranca el bot de Telegram (long-polling).

Uso:
    python -m src.main
"""
import logging

from src.config import settings
from src.database import init_db
from src.scheduler import start_scheduler, stop_scheduler
from src.telegram_bot import run as run_telegram_bot


def main() -> None:
    print(f"[main] Entorno: {settings.app_env}")
    print(f"[main] Modelo Gemini: {settings.gemini_model}")
    print(f"[main] Base de datos: {settings.database_url}")
    print(f"[main] Sheets ID: {settings.sheets_id}")
    print(f"[main] Sync cada: {settings.sync_interval_min} min")
    print(f"[main] Inicializando esquema de DB...")
    init_db()

    print(f"[main] Arrancando scheduler de sync...")
    start_scheduler()

    print(f"[main] Listo. Arrancando bot de Telegram...\n")
    try:
        run_telegram_bot()
    finally:
        # Shutdown limpio si alguien hace Ctrl+C
        logging.getLogger(__name__).info("Cerrando scheduler...")
        stop_scheduler()


if __name__ == "__main__":
    main()
