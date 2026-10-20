"""Tests de la carga de datos de demo desde la planilla de ejemplo."""
from pathlib import Path

import pytest

from merchbot.config import settings
from merchbot.data import refresh
from merchbot.data.database import get_session
from merchbot.data.demo_seed import cargar_datos_demo, leer_planilla_demo
from merchbot.data.models import Pedido, StockItem

DEMO_XLSX = Path(__file__).resolve().parents[2] / "data" / "Stock_Merchandising_Demo.xlsx"


class TestLeerPlanilla:
    def test_lee_stock_y_pedidos(self):
        stock, pedidos = leer_planilla_demo(DEMO_XLSX)
        assert len(stock) == 37
        assert len(pedidos) == 21

    def test_recalcula_las_formulas(self):
        """Pedidos, Stock Actual y Estado son fórmulas en la planilla."""
        stock, pedidos = leer_planilla_demo(DEMO_XLSX)
        for item in stock:
            vendidos = sum(p["cantidad"] for p in pedidos if p["sku"] == item["sku"])
            assert item["pedidos"] == vendidos
            assert item["stock_actual"] == item["stock_inicial"] + item["ingresos"] - vendidos
            assert item["estado"] == ("OK" if item["stock_actual"] > 0 else "COMPRAR")

    def test_hay_productos_para_comprar(self):
        stock, _ = leer_planilla_demo(DEMO_XLSX)
        assert any(i["estado"] == "COMPRAR" for i in stock)

    def test_fechas_son_date(self):
        _, pedidos = leer_planilla_demo(DEMO_XLSX)
        assert all(p["fecha"] is not None for p in pedidos)


class TestCargarEnLaBase:
    def test_carga_y_es_idempotente(self):
        primero = cargar_datos_demo(DEMO_XLSX)
        segundo = cargar_datos_demo(DEMO_XLSX)
        assert primero.ok and segundo.ok
        assert primero.stock_insertados == 37
        assert segundo.stock_insertados == 0 and segundo.stock_actualizados == 37
        with get_session() as s:
            assert s.query(StockItem).count() == 37
            assert s.query(Pedido).count() == 21

    def test_archivo_inexistente_devuelve_error_sin_romper(self, tmp_path):
        resultado = cargar_datos_demo(tmp_path / "no-existe.xlsx")
        assert not resultado.ok
        assert "No encontré" in resultado.error


class TestFuenteDeDatos:
    @pytest.mark.parametrize("fuente,sheets_id,esperado", [
        ("auto", "", "demo"),
        ("auto", "abc123", "sheets"),
        ("demo", "abc123", "demo"),
        ("SHEETS", "", "sheets"),
    ])
    def test_resolucion(self, monkeypatch, fuente, sheets_id, esperado):
        monkeypatch.setattr(settings, "data_source", fuente)
        monkeypatch.setattr(settings, "sheets_id", sheets_id)
        assert settings.fuente_de_datos == esperado

    def test_valor_invalido(self, monkeypatch):
        monkeypatch.setattr(settings, "data_source", "excel")
        with pytest.raises(ValueError):
            settings.fuente_de_datos

    def test_actualizar_datos_usa_demo(self, monkeypatch):
        monkeypatch.setattr(settings, "data_source", "demo")
        monkeypatch.setattr(settings, "demo_xlsx_path", DEMO_XLSX)
        assert refresh.actualizar_datos().stock_total == 37
