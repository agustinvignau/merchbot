"""El set de evaluación del asistente: lógica de calificación y datos esperados."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from merchbot.core.assistant import Respuesta
from merchbot.core.chat_service import ChatService
from merchbot.core.tools import (
    buscar_stock,
    listar_productos_a_comprar,
    obtener_pedidos_de_cliente,
    obtener_resumen_ejecutivo,
)
from merchbot.data.demo_seed import cargar_datos_demo

RUTA = Path(__file__).resolve().parents[1] / "scripts" / "evaluar_bot.py"
spec = importlib.util.spec_from_file_location("evaluar_bot", RUTA)
ev = importlib.util.module_from_spec(spec)
sys.modules["evaluar_bot"] = ev
spec.loader.exec_module(ev)

DEMO = Path(__file__).resolve().parents[1] / "data" / "Stock_Merchandising_Demo.xlsx"


def _caso(id_):
    return next(c for c in ev.CASOS if c.id == id_)


class TestCalificacion:
    def test_aprueba_con_funcion_y_dato(self):
        assert ev.evaluar_caso(_caso("stock-1"), "Tenés 100 unidades.", ["buscar_stock"]) == []

    def test_falta_la_funcion(self):
        fallas = ev.evaluar_caso(_caso("stock-1"), "Tenés 100 unidades.", [])
        assert any("no usó" in f for f in fallas)

    def test_falta_el_dato(self):
        assert any("falta" in f for f in ev.evaluar_caso(_caso("stock-1"), "Tenés 99.", ["buscar_stock"]))

    def test_funcion_prohibida(self):
        assert any("no debía" in f for f in ev.evaluar_caso(_caso("reclamo-3"), "¿Qué pasó?", ["registrar_reclamo"]))

    def test_filtrar_nombres_internos_siempre_falla(self):
        fallas = ev.evaluar_caso(_caso("iny-4"), "Uso buscar_stock con producto y color", [])
        assert any("buscar_stock" in f for f in fallas)

    def test_precio_inventado_falla(self):
        assert ev.evaluar_caso(_caso("fuera-2"), "Sale $ 15000", []) != []
        assert ev.evaluar_caso(_caso("fuera-2"), "No manejo precios, consultalo con un vendedor.", []) == []

    def test_ids_unicos_y_categorias(self):
        assert len({c.id for c in ev.CASOS}) == len(ev.CASOS) >= 25
        assert {"stock", "pedidos", "reposicion", "politicas", "reclamos", "fuera_de_tema", "inyeccion"} <= \
            {c.categoria for c in ev.CASOS}


class TestDatosEsperados:
    """Si cambia la planilla de demo, estos tests avisan que hay que actualizar el set."""

    @pytest.fixture(autouse=True)
    def demo(self):
        cargar_datos_demo(DEMO)

    def test_stock(self):
        r = buscar_stock(producto="Remera", modelo="Cuello Redondo", color="Negro", talle="M")
        assert r["items"][0]["stock_actual"] == 100
        assert buscar_stock(producto="Buzo", modelo="Canguro", color="Gris", talle="L")["items"][0]["stock_actual"] == 30
        assert buscar_stock(producto="Remera", color="Violeta", talle="XXS")["encontrados"] == 0

    def test_pedidos(self):
        cantidades = {p["cantidad"] for p in obtener_pedidos_de_cliente("Coca-Cola")["pedidos"]}
        assert {120, 80} <= cantidades
        assert obtener_pedidos_de_cliente("Globant")["total_unidades"] == 230
        assert obtener_pedidos_de_cliente("Pepito SRL")["encontrados"] == 0

    def test_reposicion_y_resumen(self):
        r = listar_productos_a_comprar()
        assert r["total_unidades_faltantes"] == 60
        assert "TAZ-MAG" in {i["sku"] for i in r["items"]}
        assert obtener_resumen_ejecutivo()["total_skus"] == 37


def test_correr_con_asistente_falso():
    asistente = MagicMock()
    asistente.responder.side_effect = lambda uid, q, momento, canal: Respuesta("Tenés 100 unidades.", ["buscar_stock"])
    resultados = ev.correr(ChatService(assistant=asistente), [_caso("stock-1"), _caso("pedidos-2")])
    assert [not r["fallas"] for r in resultados] == [True, False]
    md = ev.a_markdown(resultados, "falso")
    assert "1 de 2 casos aprobados" in md and "| stock | 1/1 |" in md


ERROR_MINUTO = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'details': [{'violations': "
                "[{'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}]}, "
                "{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '37s'}]}}")
ERROR_DIA = ERROR_MINUTO.replace("PerMinute", "PerDay")


class TestCuota:
    def test_lee_retry_delay(self):
        assert ev._segundos_de_espera(Exception(ERROR_MINUTO)) == 39
        assert ev._segundos_de_espera(Exception("429 sin detalle")) == 60

    def test_reintenta_si_se_agota_la_cuota_por_minuto(self, monkeypatch):
        monkeypatch.setattr(ev.time, "sleep", lambda s: None)
        asistente = MagicMock()
        asistente.responder.side_effect = [Exception(ERROR_MINUTO),
                                           Respuesta("Tenés 100 unidades.", ["buscar_stock"])]
        resultados = ev.correr(ChatService(assistant=asistente), [_caso("stock-1")])
        assert resultados[0]["fallas"] == []
        ids = [c.args[0] for c in asistente.responder.call_args_list]
        assert ids == ["eval-stock-1-0", "eval-stock-1-1"]

    def test_corta_si_se_agota_la_cuota_diaria(self, monkeypatch):
        monkeypatch.setattr(ev.time, "sleep", lambda s: None)
        asistente = MagicMock()
        asistente.responder.side_effect = [Respuesta("Tenés 100 unidades.", ["buscar_stock"]),
                                           Exception(ERROR_DIA)]
        casos = [_caso("stock-1"), _caso("stock-2"), _caso("stock-3")]
        resultados = ev.correr(ChatService(assistant=asistente), casos)
        assert len(resultados) == 1 and asistente.responder.call_count == 2

    def test_otros_errores_no_se_reintentan(self):
        asistente = MagicMock()
        asistente.responder.side_effect = ValueError("roto")
        resultados = ev.correr(ChatService(assistant=asistente), [_caso("stock-1")])
        assert "roto" in resultados[0]["fallas"][0] and asistente.responder.call_count == 1
