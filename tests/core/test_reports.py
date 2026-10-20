"""Tests de merchbot.core.reports (consultas directas, sin IA)."""
from merchbot.core import reports


# ---------------------------------------------------------------------------
# Reportes directos a la base (sin IA)
# ---------------------------------------------------------------------------

class TestGetProductosAComprar:
    def test_devuelve_solo_estado_comprar(self, db_with_data):
        productos = reports.productos_a_comprar()
        skus = {p["sku"] for p in productos}
        assert skus == {"REM-DF-NEG-M", "GOR-RES-ROJ"}

    def test_devuelve_dicts_no_orm(self, db_with_data):
        """Crítico: si devuelve ORM, fuera de sesión truena DetachedInstance."""
        productos = reports.productos_a_comprar()
        for p in productos:
            assert isinstance(p, dict)
            assert p["descripcion"]

    def test_orden_por_urgencia(self, db_with_data):
        productos = reports.productos_a_comprar()
        assert productos[0]["sku"] == "GOR-RES-ROJ"
        assert productos[1]["sku"] == "REM-DF-NEG-M"


class TestGetResumenEjecutivo:
    def test_metricas_basicas(self, db_with_data):
        r = reports.resumen_ejecutivo()
        assert r["total_skus"] == 4
        assert r["skus_comprar"] == 2
        assert r["skus_ok"] == 2
        # Suma de stocks positivos: 20 + 25 = 45
        assert r["unidades_totales"] == 45

    def test_pedidos_agregados(self, db_with_data):
        r = reports.resumen_ejecutivo()
        assert r["total_pedidos"] == 3
        # 50 + 120 + 45 = 215
        assert r["unidades_vendidas"] == 215
        assert r["clientes_distintos"] == 3
