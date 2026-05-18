"""REPL local para probar el MerchBot sin Telegram.

Útil para iterar prompts antes de conectar el bot real.

Uso:
    python scripts/test_bot_interactive.py

Comandos especiales:
    /comprar    -> productos en rojo (consulta directa a DB)
    /resumen    -> resumen ejecutivo
    /sync       -> recargar desde Google Sheets
    /clear      -> borrar memoria de conversación
    /salir      -> terminar
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.gemini_bot import (  # noqa: E402
    MerchBot,
    format_comprar_message,
    format_resumen_message,
)
from src.sheets_sync import sync_from_sheets  # noqa: E402


USER_ID = 1


def main() -> int:
    print("=" * 60)
    print(" MERCHBOT - prueba interactiva (sin Telegram)")
    print("=" * 60)
    print("Comandos: /comprar  /resumen  /sync  /clear  /salir\n")

    try:
        bot = MerchBot()
    except Exception as e:
        print(f"[ERROR] No pude inicializar el bot: {e}")
        return 1

    while True:
        try:
            q = input("vos > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not q:
            continue
        if q.lower() in ("/salir", "salir", "exit", "quit"):
            break
        if q.lower() == "/clear":
            n = bot.clear_memory(USER_ID)
            print(f"[memoria borrada: {n} turnos]\n")
            continue
        if q.lower() == "/comprar":
            productos = bot.get_productos_a_comprar()
            print(format_comprar_message(productos) + "\n")
            continue
        if q.lower() == "/resumen":
            print(format_resumen_message(bot.get_resumen_ejecutivo()) + "\n")
            continue
        if q.lower() == "/sync":
            print("Sincronizando con Google Sheets...")
            result = sync_from_sheets()
            print(result.resumen() + "\n")
            continue

        try:
            respuesta = bot.ask(USER_ID, q)
            print(f"bot > {respuesta}\n")
        except Exception as e:
            print(f"[ERROR] {type(e).__name__}: {e}\n")

    print("Chau.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
