"""Tests de los formateadores de mensajes de Telegram (sin red ni IA)."""
from merchbot.interfaces.telegram.formatters import (
    format_comprar_message,
    format_resumen_message,
)


# ---------------------------------------------------------------------------
# /comprar y /resumen
# ---------------------------------------------------------------------------

class TestFormatComprar:
    def test_lista_vacia(self):
        assert "Stock OK" in format_comprar_message([])

    def test_con_productos(self):
        productos = [
            {"sku": "X-1", "descripcion": "Remera Dry-Fit Negro M",
             "stock_actual": -15, "estado": "COMPRAR"},
            {"sku": "X-2", "descripcion": "Gorra Roja",
             "stock_actual": -20, "estado": "COMPRAR"},
        ]
        msg = format_comprar_message(productos)
        assert "2 producto(s)" in msg
        assert "Remera Dry-Fit Negro M" in msg
        assert "faltan 15" in msg
        assert "faltan 20" in msg


class TestFormatResumen:
    def test_estructura_basica(self):
        r = {
            "total_skus": 37, "skus_ok": 32, "skus_comprar": 5,
            "unidades_totales": 1500, "total_pedidos": 21,
            "unidades_vendidas": 1400, "clientes_distintos": 12,
            "top_cliente": ("Coca-Cola", 240),
            "top_producto": ("Remera Cuello Redondo Blanco M", 180),
        }
        msg = format_resumen_message(r)
        assert "37" in msg
        assert "Coca-Cola" in msg
        assert "1.500" in msg  # separador de miles
