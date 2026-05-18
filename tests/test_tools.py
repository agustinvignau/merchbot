"""Tests de src/tools.py — las funciones puras que después expondremos a Gemini."""
from datetime import date

import pytest

from src.models import StockItem, Pedido
from src.tools import (
    buscar_stock,
    listar_productos_a_comprar,
    obtener_pedidos_de_cliente,
    listar_pedidos_recientes,
    obtener_resumen_ejecutivo,
    listar_categorias_disponibles,
    ejecutar_tool,
)


# ---------------------------------------------------------------------------
# Fixtures locales (reusan _patch_db del conftest)
# ---------------------------------------------------------------------------

@pytest.fixture
def db_lleno(test_session_factory):
    """DB poblada con stock y pedidos realistas para los tests."""
    stock = [
        StockItem(sku="REM-CR-BCO-M", producto="Remera", modelo="Cuello Redondo",
                  color="Blanco", talle="M", stock_inicial=100, ingresos=100,
                  pedidos=180, stock_actual=20, estado="OK"),
        StockItem(sku="REM-CR-NEG-M", producto="Remera", modelo="Cuello Redondo",
                  color="Negro", talle="M", stock_inicial=60, ingresos=40,
                  pedidos=0, stock_actual=100, estado="OK"),
        StockItem(sku="REM-CR-NEG-L", producto="Remera", modelo="Cuello Redondo",
                  color="Negro", talle="L", stock_inicial=40, ingresos=20,
                  pedidos=0, stock_actual=60, estado="OK"),
        StockItem(sku="REM-DF-NEG-M", producto="Remera", modelo="Dry-Fit",
                  color="Negro", talle="M", stock_inicial=30, ingresos=0,
                  pedidos=45, stock_actual=-15, estado="COMPRAR"),
        StockItem(sku="BUZ-CN-GRI-L", producto="Buzo", modelo="Canguro",
                  color="Gris", talle="L", stock_inicial=50, ingresos=50,
                  pedidos=70, stock_actual=30, estado="OK"),
        StockItem(sku="GOR-RES-ROJ", producto="Gorra", modelo="Con Respiración",
                  color="Rojo", talle="Único", stock_inicial=20, ingresos=0,
                  pedidos=40, stock_actual=-20, estado="COMPRAR"),
        StockItem(sku="TAZ-CER-BCA", producto="Taza", modelo="Cerámica",
                  color="Blanco", talle="Único", stock_inicial=200, ingresos=150,
                  pedidos=280, stock_actual=70, estado="OK"),
    ]
    pedidos = [
        Pedido(fecha=date(2026, 5, 14), cliente="Globant - Welcome Kit",
               sku="BUZ-CN-GRI-L", producto="Buzo Canguro Gris L", cantidad=70),
        Pedido(fecha=date(2026, 5, 10), cliente="Coca-Cola - Evento Verano",
               sku="REM-CR-BCO-M", producto="Remera CR Blanco M", cantidad=120),
        Pedido(fecha=date(2026, 4, 28), cliente="Movistar - Día del Padre",
               sku="REM-DF-NEG-M", producto="Remera Dry-Fit Negro M", cantidad=45),
        Pedido(fecha=date(2026, 4, 18), cliente="Banco Nación",
               sku="REM-CR-BCO-M", producto="Remera CR Blanco M", cantidad=60),
        Pedido(fecha=date(2026, 4, 15), cliente="Coca-Cola - Evento Verano",
               sku="GOR-RES-ROJ", producto="Gorra Respiración Rojo", cantidad=40),
    ]
    s = test_session_factory()
    s.add_all(stock + pedidos)
    s.commit()
    s.close()


# ---------------------------------------------------------------------------
# buscar_stock
# ---------------------------------------------------------------------------

class TestBuscarStock:
    def test_sin_filtros_devuelve_todo(self, db_lleno):
        r = buscar_stock()
        assert r["encontrados"] == 7

    def test_filtro_por_producto(self, db_lleno):
        r = buscar_stock(producto="Remera")
        assert r["encontrados"] == 4

    def test_filtro_por_color(self, db_lleno):
        r = buscar_stock(color="Negro")
        assert r["encontrados"] == 3

    def test_filtros_combinados_AND(self, db_lleno):
        # Remera + Negro + M -> REM-CR-NEG-M y REM-DF-NEG-M
        r = buscar_stock(producto="Remera", color="Negro", talle="M")
        skus = {it["sku"] for it in r["items"]}
        assert skus == {"REM-CR-NEG-M", "REM-DF-NEG-M"}

    def test_case_insensitive(self, db_lleno):
        r = buscar_stock(color="negro")  # minúscula
        assert r["encontrados"] == 3

    def test_busqueda_parcial(self, db_lleno):
        """Si filtra por 'Cuell' debería matchear 'Cuello Redondo'."""
        r = buscar_stock(modelo="Cuell")
        # 3 cuello redondo: REM-CR-BCO-M, REM-CR-NEG-M, REM-CR-NEG-L
        assert r["encontrados"] == 3

    def test_sin_resultados_devuelve_lista_vacia(self, db_lleno):
        r = buscar_stock(producto="Inexistente")
        assert r["encontrados"] == 0
        assert r["items"] == []
        assert r["stock_total"] == 0

    def test_stock_total_suma_correcta(self, db_lleno):
        r = buscar_stock(color="Negro")
        # REM-CR-NEG-M=100, REM-CR-NEG-L=60, REM-DF-NEG-M=-15 → 145
        assert r["stock_total"] == 145


# ---------------------------------------------------------------------------
# listar_productos_a_comprar
# ---------------------------------------------------------------------------

class TestListarAComprar:
    def test_devuelve_solo_estado_comprar(self, db_lleno):
        r = listar_productos_a_comprar()
        assert r["cantidad"] == 2
        skus = {it["sku"] for it in r["items"]}
        assert skus == {"REM-DF-NEG-M", "GOR-RES-ROJ"}

    def test_ordenado_por_urgencia(self, db_lleno):
        r = listar_productos_a_comprar()
        # GOR-RES-ROJ tiene -20, REM-DF-NEG-M tiene -15 → gorra primero
        assert r["items"][0]["sku"] == "GOR-RES-ROJ"

    def test_total_faltantes(self, db_lleno):
        r = listar_productos_a_comprar()
        # 20 + 15 = 35
        assert r["total_unidades_faltantes"] == 35


# ---------------------------------------------------------------------------
# obtener_pedidos_de_cliente
# ---------------------------------------------------------------------------

class TestPedidosDeCliente:
    def test_match_exacto(self, db_lleno):
        r = obtener_pedidos_de_cliente("Globant - Welcome Kit")
        assert r["encontrados"] == 1
        assert r["total_unidades"] == 70

    def test_busqueda_parcial(self, db_lleno):
        r = obtener_pedidos_de_cliente("Coca")
        assert r["encontrados"] == 2  # los 2 pedidos de Coca-Cola
        assert r["total_unidades"] == 160  # 120 + 40

    def test_case_insensitive(self, db_lleno):
        r = obtener_pedidos_de_cliente("globant")
        assert r["encontrados"] == 1

    def test_sin_resultados(self, db_lleno):
        r = obtener_pedidos_de_cliente("ClienteInventado")
        assert r["encontrados"] == 0
        assert r["pedidos"] == []
        assert r["total_unidades"] == 0


# ---------------------------------------------------------------------------
# listar_pedidos_recientes
# ---------------------------------------------------------------------------

class TestPedidosRecientes:
    def test_default_devuelve_hasta_10(self, db_lleno):
        r = listar_pedidos_recientes()
        # Hay 5 pedidos en el fixture
        assert r["cantidad"] == 5

    def test_orden_descendente_por_fecha(self, db_lleno):
        r = listar_pedidos_recientes()
        fechas = [p["fecha"] for p in r["pedidos"]]
        assert fechas == sorted(fechas, reverse=True)

    def test_clamp_a_50(self, db_lleno):
        """Si piden cantidad=1000 debería clampear a 50."""
        r = listar_pedidos_recientes(cantidad=1000)
        assert r["cantidad"] <= 50

    def test_clamp_min_1(self, db_lleno):
        r = listar_pedidos_recientes(cantidad=0)
        # Tras clamp queda 1, y hay 5 pedidos → devuelve 1
        assert r["cantidad"] == 1


# ---------------------------------------------------------------------------
# obtener_resumen_ejecutivo
# ---------------------------------------------------------------------------

class TestResumenEjecutivo:
    def test_totales_basicos(self, db_lleno):
        r = obtener_resumen_ejecutivo()
        assert r["total_skus"] == 7
        assert r["skus_a_comprar"] == 2
        assert r["skus_ok"] == 5

    def test_unidades_totales_solo_positivas(self, db_lleno):
        r = obtener_resumen_ejecutivo()
        # 20+100+60+30+70 = 280 (no incluye los negativos)
        assert r["unidades_totales_en_stock"] == 280

    def test_top_cliente_es_el_que_mas_unidades_pidio(self, db_lleno):
        r = obtener_resumen_ejecutivo()
        # Coca-Cola: 120+40=160; Globant: 70; Movistar: 45; Banco: 60 → Coca primero
        assert r["top_cliente"]["nombre"] == "Coca-Cola - Evento Verano"
        assert r["top_cliente"]["unidades"] == 160


# ---------------------------------------------------------------------------
# listar_categorias_disponibles
# ---------------------------------------------------------------------------

class TestCategoriasDisponibles:
    def test_agrupa_modelos_por_producto(self, db_lleno):
        r = listar_categorias_disponibles()
        # Productos en el fixture: Remera, Buzo, Gorra, Taza
        productos = {p["producto"] for p in r["productos"]}
        assert productos == {"Remera", "Buzo", "Gorra", "Taza"}

    def test_remera_tiene_dos_modelos(self, db_lleno):
        r = listar_categorias_disponibles()
        remera = next(p for p in r["productos"] if p["producto"] == "Remera")
        modelos = {m["modelo"] for m in remera["modelos"]}
        assert modelos == {"Cuello Redondo", "Dry-Fit"}


# ---------------------------------------------------------------------------
# ejecutar_tool (dispatcher)
# ---------------------------------------------------------------------------

class TestEjecutarTool:
    def test_ejecuta_funcion_existente(self, db_lleno):
        r = ejecutar_tool("listar_productos_a_comprar", {})
        assert "cantidad" in r
        assert r["cantidad"] == 2

    def test_pasa_args(self, db_lleno):
        r = ejecutar_tool("buscar_stock", {"color": "Negro"})
        assert r["encontrados"] == 3

    def test_args_none_es_dict_vacio(self, db_lleno):
        r = ejecutar_tool("listar_productos_a_comprar", None)
        assert "cantidad" in r

    def test_funcion_inexistente_devuelve_error(self, db_lleno):
        r = ejecutar_tool("funcion_que_no_existe", {})
        assert "error" in r
        assert "no existe" in r["error"]

    def test_args_invalidos_devuelve_error(self, db_lleno):
        # buscar_stock no acepta 'precio'
        r = ejecutar_tool("buscar_stock", {"precio": 100})
        assert "error" in r
        assert "Args inválidos" in r["error"] or "Inv" in r["error"]
