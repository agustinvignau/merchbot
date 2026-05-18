"""Tests del módulo sheets_sync: parser de CSV + upsert en DB.

NO tocamos la API real de Google Sheets en estos tests — usamos un CSV
guardado como fixture que tiene la estructura idéntica a la respuesta real.
"""
from datetime import date

from src.database import get_session
from src.models import StockItem, Pedido
from src.sheets_sync import (
    parse_stock_csv,
    parse_pedidos_csv,
    _upsert_stock,
    _replace_pedidos,
    _safe_int,
    _parse_fecha,
)
from datetime import datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestSafeInt:
    def test_int_string(self):
        assert _safe_int("42") == 42

    def test_negative(self):
        assert _safe_int("-15") == -15

    def test_empty(self):
        assert _safe_int("") == 0

    def test_none(self):
        assert _safe_int(None) == 0

    def test_garbage_devuelve_default(self):
        assert _safe_int("abc", default=99) == 99


class TestParseFecha:
    def test_iso_format(self):
        assert _parse_fecha("2026-05-14") == date(2026, 5, 14)

    def test_slash_dmy(self):
        assert _parse_fecha("14/05/2026") == date(2026, 5, 14)

    def test_empty(self):
        assert _parse_fecha("") is None

    def test_garbage(self):
        assert _parse_fecha("not a date") is None


# ---------------------------------------------------------------------------
# Parser CSV de Stock
# ---------------------------------------------------------------------------

class TestParseStockCsv:
    def test_cantidad_de_filas(self, stock_csv):
        items = parse_stock_csv(stock_csv)
        # El fixture tiene 11 filas
        assert len(items) == 11

    def test_estructura_basica(self, stock_csv):
        items = parse_stock_csv(stock_csv)
        first = items[0]
        assert first["sku"] == "REM-CR-BCO-S"
        assert first["producto"] == "Remera"
        assert first["modelo"] == "Cuello Redondo"
        assert first["color"] == "Blanco"
        assert first["talle"] == "S"
        assert first["stock_actual"] == 130
        assert first["estado"] == "OK"

    def test_stock_negativo_marcado_como_comprar(self, stock_csv):
        items = parse_stock_csv(stock_csv)
        comprar = [i for i in items if i["estado"] == "COMPRAR"]
        # En el fixture: REM-DF-NEG-M, REM-DF-NEG-L, BUZ-CR-GRI-M, GOR-RES-ROJ, TAZ-MAG
        assert len(comprar) == 5
        # Todos los COMPRAR deberían tener stock_actual <= 0
        for item in comprar:
            assert item["stock_actual"] <= 0

    def test_ignora_filas_sin_sku(self):
        csv = (
            "SKU,Producto,Modelo,Color,Talle,Stock Inicial,Ingresos,Pedidos,Stock Actual,Estado\n"
            "REM-1,Remera,Cuello Redondo,Blanco,M,10,5,2,13,OK\n"
            ",,,,,,,,,\n"      # fila vacía
            "REM-2,Remera,Dry-Fit,Negro,L,5,0,8,-3,COMPRAR\n"
        )
        items = parse_stock_csv(csv)
        assert len(items) == 2


# ---------------------------------------------------------------------------
# Parser CSV de Pedidos
# ---------------------------------------------------------------------------

class TestParsePedidosCsv:
    def test_cantidad_de_filas(self, pedidos_csv):
        items = parse_pedidos_csv(pedidos_csv)
        # El fixture tiene 9 pedidos
        assert len(items) == 9

    def test_estructura(self, pedidos_csv):
        items = parse_pedidos_csv(pedidos_csv)
        first = items[0]
        assert first["fecha"] == date(2026, 4, 15)
        assert first["cliente"] == "Coca-Cola - Evento Verano"
        assert first["sku"] == "REM-CR-BCO-M"
        assert first["cantidad"] == 120

    def test_ignora_filas_sin_sku_o_cantidad(self):
        csv = (
            "Fecha,Cliente,SKU,Producto,Cantidad\n"
            "2026-05-01,Cliente A,SKU-1,Producto X,10\n"
            ",,,,\n"                              # vacía
            "2026-05-02,Cliente B,,Producto Y,5\n" # sin SKU
            "2026-05-03,Cliente C,SKU-2,Producto Z,0\n"  # cantidad cero
        )
        items = parse_pedidos_csv(csv)
        assert len(items) == 1
        assert items[0]["sku"] == "SKU-1"


# ---------------------------------------------------------------------------
# Upsert en DB
# ---------------------------------------------------------------------------

class TestUpsertStock:
    def test_insert_nuevos(self, stock_csv):
        items = parse_stock_csv(stock_csv)
        now = datetime.utcnow()
        ins, upd = _upsert_stock(items, now)
        assert ins == len(items)
        assert upd == 0

        with get_session() as s:
            assert s.query(StockItem).count() == len(items)

    def test_update_no_duplica(self, stock_csv):
        items = parse_stock_csv(stock_csv)
        now = datetime.utcnow()
        # Primer sync
        _upsert_stock(items, now)
        # Segundo sync con los mismos datos
        ins, upd = _upsert_stock(items, now)
        assert ins == 0
        assert upd == len(items)
        # No deberían haberse duplicado filas
        with get_session() as s:
            assert s.query(StockItem).count() == len(items)

    def test_update_refleja_cambios(self, stock_csv):
        items = parse_stock_csv(stock_csv)
        now = datetime.utcnow()
        _upsert_stock(items, now)

        # Simular que en el Sheets se actualizó el stock
        items_modificados = [dict(it) for it in items]
        items_modificados[0]["stock_actual"] = 999
        items_modificados[0]["estado"] = "OK"
        _upsert_stock(items_modificados, now)

        with get_session() as s:
            sku = items[0]["sku"]
            updated = s.query(StockItem).filter_by(sku=sku).first()
            assert updated.stock_actual == 999

    def test_property_en_rojo(self, stock_csv):
        items = parse_stock_csv(stock_csv)
        _upsert_stock(items, datetime.utcnow())
        with get_session() as s:
            rojos = [p for p in s.query(StockItem).all() if p.en_rojo]
            # 5 productos del fixture están en rojo
            assert len(rojos) == 5


class TestReplacePedidos:
    def test_insert_inicial(self, pedidos_csv):
        items = parse_pedidos_csv(pedidos_csv)
        count = _replace_pedidos(items, datetime.utcnow())
        assert count == len(items)
        with get_session() as s:
            assert s.query(Pedido).count() == len(items)

    def test_replace_borra_anteriores(self, pedidos_csv):
        items = parse_pedidos_csv(pedidos_csv)
        _replace_pedidos(items, datetime.utcnow())

        # Sync de nuevo con menos pedidos
        nuevos = items[:3]
        _replace_pedidos(nuevos, datetime.utcnow())

        with get_session() as s:
            # Solo deberían quedar los 3 últimos
            assert s.query(Pedido).count() == 3
