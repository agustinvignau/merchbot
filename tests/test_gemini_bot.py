"""Tests del MerchBot: formateadores, queries a DB, memoria, ask con mock."""
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.database import get_session
from src.gemini_bot import (
    MerchBot,
    Turno,
    format_stock_for_prompt,
    format_comprar_message,
    format_resumen_message,
)
from src.models import StockItem, Pedido


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_stock():
    return [
        StockItem(sku="REM-CR-BCO-M", producto="Remera", modelo="Cuello Redondo",
                  color="Blanco", talle="M", stock_inicial=100, ingresos=100,
                  pedidos=180, stock_actual=20, estado="OK"),
        StockItem(sku="REM-DF-NEG-M", producto="Remera", modelo="Dry-Fit",
                  color="Negro", talle="M", stock_inicial=30, ingresos=0,
                  pedidos=45, stock_actual=-15, estado="COMPRAR"),
        StockItem(sku="BUZ-CN-NEG-L", producto="Buzo", modelo="Canguro",
                  color="Negro", talle="L", stock_inicial=45, ingresos=30,
                  pedidos=50, stock_actual=25, estado="OK"),
        StockItem(sku="GOR-RES-ROJ", producto="Gorra", modelo="Con Respiración",
                  color="Rojo", talle="Único", stock_inicial=20, ingresos=0,
                  pedidos=40, stock_actual=-20, estado="COMPRAR"),
    ]


@pytest.fixture
def sample_pedidos():
    return [
        Pedido(fecha=date(2026, 5, 14), cliente="Globant - Welcome Kit",
               sku="BUZ-CN-NEG-L", producto="Buzo Canguro Negro L", cantidad=50),
        Pedido(fecha=date(2026, 4, 15), cliente="Coca-Cola - Evento",
               sku="REM-CR-BCO-M", producto="Remera Cuello Redondo Blanco M",
               cantidad=120),
        Pedido(fecha=date(2026, 4, 28), cliente="Movistar - Día del Padre",
               sku="REM-DF-NEG-M", producto="Remera Dry-Fit Negro M", cantidad=45),
    ]


@pytest.fixture
def db_with_data(test_session_factory, sample_stock, sample_pedidos):
    session = test_session_factory()
    session.add_all(sample_stock)
    session.add_all(sample_pedidos)
    session.commit()
    session.close()
    return sample_stock, sample_pedidos


# ---------------------------------------------------------------------------
# Formateadores
# ---------------------------------------------------------------------------

class TestFormatStock:
    def test_header_y_filas(self, sample_stock):
        out = format_stock_for_prompt(sample_stock)
        lineas = out.split("\n")
        assert lineas[0].startswith("SKU |")
        assert len(lineas) == 1 + len(sample_stock)

    def test_incluye_estado(self, sample_stock):
        out = format_stock_for_prompt(sample_stock)
        assert "COMPRAR" in out
        assert "OK" in out


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
        assert "35" in msg  # total faltante


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


# ---------------------------------------------------------------------------
# DB queries (usan la DB en memoria via fixture _patch_db)
# ---------------------------------------------------------------------------

class TestSnapshotStock:
    def test_devuelve_tabla_completa(self, db_with_data):
        bot = MerchBot.__new__(MerchBot)
        bot.PEDIDOS_EN_CONTEXTO = 25
        snap = bot._snapshot_stock()
        assert "REM-CR-BCO-M" in snap
        assert "GOR-RES-ROJ" in snap
        # debería tener exactamente 1 header + N filas
        assert len(snap.split("\n")) == 1 + 4


class TestSnapshotPedidos:
    def test_ordena_descendente_por_fecha(self, db_with_data):
        bot = MerchBot.__new__(MerchBot)
        bot.PEDIDOS_EN_CONTEXTO = 25
        snap = bot._snapshot_pedidos_recientes()
        lineas = snap.split("\n")
        # primer pedido (después del header) debería ser el más reciente
        assert "2026-05-14" in lineas[1]


class TestGetProductosAComprar:
    def test_solo_estado_comprar(self, db_with_data):
        bot = MerchBot.__new__(MerchBot)
        productos = bot.get_productos_a_comprar()
        skus = {p["sku"] for p in productos}
        assert skus == {"REM-DF-NEG-M", "GOR-RES-ROJ"}

    def test_devuelve_dicts_no_orm(self, db_with_data):
        """Crítico: si devuelve ORM, fuera de sesión truena DetachedInstance."""
        bot = MerchBot.__new__(MerchBot)
        productos = bot.get_productos_a_comprar()
        for p in productos:
            assert isinstance(p, dict)
            assert p["descripcion"]   # accesible fuera de sesión

    def test_orden_por_urgencia(self, db_with_data):
        bot = MerchBot.__new__(MerchBot)
        productos = bot.get_productos_a_comprar()
        # GOR-RES-ROJ tiene -20, REM-DF-NEG-M tiene -15 → gorra primero
        assert productos[0]["sku"] == "GOR-RES-ROJ"
        assert productos[1]["sku"] == "REM-DF-NEG-M"


class TestGetResumenEjecutivo:
    def test_metricas_basicas(self, db_with_data):
        bot = MerchBot.__new__(MerchBot)
        r = bot.get_resumen_ejecutivo()
        assert r["total_skus"] == 4
        assert r["skus_comprar"] == 2
        assert r["skus_ok"] == 2
        # Suma de stocks positivos: 20 + 25 = 45
        assert r["unidades_totales"] == 45

    def test_pedidos_agregados(self, db_with_data):
        bot = MerchBot.__new__(MerchBot)
        r = bot.get_resumen_ejecutivo()
        assert r["total_pedidos"] == 3
        # 50 + 120 + 45 = 215
        assert r["unidades_vendidas"] == 215
        assert r["clientes_distintos"] == 3

    def test_top_cliente(self, db_with_data):
        bot = MerchBot.__new__(MerchBot)
        r = bot.get_resumen_ejecutivo()
        # Coca-Cola pidió 120 (más alto)
        assert r["top_cliente"][0] == "Coca-Cola - Evento"
        assert r["top_cliente"][1] == 120


# ---------------------------------------------------------------------------
# Memoria conversacional
# ---------------------------------------------------------------------------

class TestMemoria:
    def _bot_sin_red(self):
        with patch("src.gemini_bot.genai.Client"):
            return MerchBot(api_key="fake")

    def test_clear_memory_devuelve_cantidad(self):
        bot = self._bot_sin_red()
        bot._memoria[42].extend([
            Turno("user", "hola"), Turno("model", "hola"),
        ])
        assert bot.clear_memory(42) == 2

    def test_memoria_respeta_maxlen(self):
        bot = self._bot_sin_red()
        for i in range(30):
            bot._memoria[1].append(Turno("user", f"q{i}"))
        assert len(bot._memoria[1]) == MerchBot.HISTORIAL_MAX_TURNOS

    def test_memoria_aislada_por_usuario(self):
        bot = self._bot_sin_red()
        bot._memoria[1].append(Turno("user", "soy 1"))
        bot._memoria[2].append(Turno("user", "soy 2"))
        bot.clear_memory(1)
        assert 1 not in bot._memoria
        assert len(bot._memoria[2]) == 1


# ---------------------------------------------------------------------------
# ask() con cliente Gemini mockeado
# ---------------------------------------------------------------------------

class TestAsk:
    def _bot_con_mock(self, mock_text="Tenés 20 remeras blancas M.",
                      finish_reason="STOP"):
        with patch("src.gemini_bot.genai.Client") as MockClient:
            client_instance = MockClient.return_value
            response = MagicMock()
            response.text = mock_text
            response.candidates = [MagicMock(finish_reason=finish_reason)]
            client_instance.models.generate_content.return_value = response
            bot = MerchBot(api_key="fake")
            return bot, client_instance

    def test_query_vacia_no_llama_modelo(self, db_with_data):
        bot, client = self._bot_con_mock()
        respuesta = bot.ask(user_id=1, query="   ")
        assert "Decime una consulta" in respuesta
        client.models.generate_content.assert_not_called()

    def test_devuelve_texto_del_modelo(self, db_with_data):
        bot, _ = self._bot_con_mock("Tenés 25 buzos.")
        respuesta = bot.ask(user_id=1, query="cuantos buzos?")
        assert "25 buzos" in respuesta

    def test_guarda_turno_en_memoria(self, db_with_data):
        bot, _ = self._bot_con_mock("ok")
        bot.ask(user_id=7, query="hola")
        assert len(bot._memoria[7]) == 2
        assert bot._memoria[7][0].role == "user"
        assert bot._memoria[7][1].role == "model"

    def test_inyecta_stock_y_pedidos_en_prompt(self, db_with_data):
        bot, client = self._bot_con_mock("ok")
        bot.ask(user_id=1, query="hola")
        call_kwargs = client.models.generate_content.call_args.kwargs
        system = call_kwargs["config"].system_instruction
        assert "STOCK ACTUAL" in system
        assert "PEDIDOS RECIENTES" in system
        # SKU del fixture aparece
        assert "REM-CR-BCO-M" in system
        # Cliente del fixture también
        assert "Coca-Cola" in system

    def test_truncacion_avisa(self, db_with_data):
        bot, _ = self._bot_con_mock("largo...", finish_reason="MAX_TOKENS")
        respuesta = bot.ask(user_id=1, query="listame todo")
        assert "cortada" in respuesta.lower()
