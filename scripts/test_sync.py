"""Prueba el sync con Google Sheets sin pasar por Telegram.

Uso:
    python scripts/test_sync.py

Lee el SHEETS_ID del .env, descarga las hojas Stock y Pedidos,
las inserta en la DB y muestra un resumen.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.database import init_db, get_session  # noqa: E402
from src.models import StockItem, Pedido  # noqa: E402
from src.sheets_sync import sync_from_sheets  # noqa: E402


def main() -> int:
    print("=" * 60)
    print(" SYNC TEST - Google Sheets -> DB")
    print("=" * 60)

    if not settings.sheets_id:
        print("[ERROR] SHEETS_ID no configurado en .env")
        return 1

    print(f"[1/3] SHEETS_ID: {settings.sheets_id}")
    print(f"[2/3] Inicializando DB...")
    init_db()

    print(f"[3/3] Ejecutando sync...\n")
    result = sync_from_sheets()
    print(result.resumen())

    if not result.ok:
        return 1

    # Resumen del estado del stock
    print("\n" + "-" * 60)
    print(" RESUMEN DEL STOCK SINCRONIZADO")
    print("-" * 60)
    with get_session() as session:
        total = session.query(StockItem).count()
        en_rojo = session.query(StockItem).filter(StockItem.stock_actual <= 0).all()
        total_pedidos = session.query(Pedido).count()

        print(f"Productos en stock:    {total}")
        print(f"Total de pedidos:      {total_pedidos}")
        print(f"Productos COMPRAR:     {len(en_rojo)}")

        if en_rojo:
            print("\nProductos en rojo:")
            for p in en_rojo:
                print(f"  - {p.descripcion_completa} ({p.sku}) "
                      f"stock={p.stock_actual} (inicial={p.stock_inicial}, "
                      f"ing={p.ingresos}, ped={p.pedidos})")

    print("\n[OK] Sync completado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
