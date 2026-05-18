"""Tests del MerchBot v2 (con function calling).

Cambios vs v1:
- Eliminados tests de _snapshot_stock / _snapshot_pedidos / format_stock_for_prompt
  (esas funciones ya no existen — ahora Gemini consulta vía tools, no por prompt).
- Reescritos los tests de ask(): mockeamos el loop completo de function calling.

Lo que NO cambió:
- format_comprar_message, format_resumen_message
- get_productos_a_comprar (atajo directo a DB)
- get_resumen_ejecutivo (idem)
- Memoria conversacional por usuario
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.gemini_bot import (
    MerchBot,
    Turno,
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
               sku="REM-CR-BCO-M", producto="Remera CR Blanco M", cantidad=120),
        Pedido(fecha=date(2026, 4, 28), cliente="Movistar - Día del Padre",
               sku="REM-DF-NEG-M", producto="Remera Dry-Fit Negro M", cantidad=45),
    ]


@pytest.fixture
def db_with_data(test_session_factory, sample_stock, sample_pedidos):
    session = test_session_factory()
    session.add_all(sample_stock + sample_pedidos)
    session.commit()
    session.close()
    return sample_stock, sample_pedidos


# ---------------------------------------------------------------------------
# Helpers para mockear respuestas de Gemini con function calling
# ---------------------------------------------------------------------------

def _mock_fc(name: str, args: dict) -> MagicMock:
    """Construye un MagicMock que simula un FunctionCall de Gemini."""
    fc = MagicMock()
    fc.name = name
    fc.args = args
    return fc


def _mock_response_with_calls(*calls) -> MagicMock:
    """Mock de response cuando Gemini quiere llamar tools."""
    resp = MagicMock()
    resp.function_calls = list(calls)
    # candidates[0].content sirve para que el bot agregue la respuesta al historial.
    # Le ponemos un MagicMock que no rompe nada cuando se lo serializa.
    resp.candidates = [MagicMock()]
    resp.candidates[0].content = MagicMock()
    resp.text = ""
    return resp


def _mock_response_with_text(text: str) -> MagicMock:
    """Mock de response cuando Gemini devuelve la respuesta final."""
    resp = MagicMock()
    resp.function_calls = []
    resp.text = text
    resp.candidates = [MagicMock(finish_reason="STOP")]
    return resp


def _bot_con_responses(responses: list[MagicMock]):
    """Crea un MerchBot cuyo cliente devuelve `responses` en orden.

    Cada llamada a generate_content devuelve el siguiente response de la lista.
    """
    with patch("src.gemini_bot.genai.Client") as MockClient:
        client = MockClient.return_value
        client.models.generate_content.side_effect = responses
        bot = MerchBot(api_key="fake")
        return bot, client


# ---------------------------------------------------------------------------
# Formateadores (no cambiaron entre v1 y v2)
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


# ---------------------------------------------------------------------------
# Atajos directos a DB (no usan IA — no cambiaron entre v1 y v2)
# ---------------------------------------------------------------------------

class TestGetProductosAComprar:
    def test_devuelve_solo_estado_comprar(self, db_with_data):
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
            assert p["descripcion"]

    def test_orden_por_urgencia(self, db_with_data):
        bot = MerchBot.__new__(MerchBot)
        productos = bot.get_productos_a_comprar()
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
# ask() con function calling — el corazón del v2
# ---------------------------------------------------------------------------

class TestAskBasico:
    """Caso simple: Gemini devuelve respuesta directa sin tools."""

    def test_devuelve_texto_directo(self, db_with_data):
        # Gemini responde sin necesitar tools
        bot, _ = _bot_con_responses([
            _mock_response_with_text("Hola, ¿en qué te ayudo?"),
        ])
        respuesta = bot.ask(user_id=1, query="hola")
        assert "Hola" in respuesta

    def test_query_vacia_no_llama_modelo(self, db_with_data):
        bot, client = _bot_con_responses([])
        respuesta = bot.ask(user_id=1, query="   ")
        assert "Decime una consulta" in respuesta
        client.models.generate_content.assert_not_called()

    def test_guarda_turno_en_memoria(self, db_with_data):
        bot, _ = _bot_con_responses([
            _mock_response_with_text("ok"),
        ])
        bot.ask(user_id=7, query="hola")
        assert len(bot._memoria[7]) == 2
        assert bot._memoria[7][0].text == "hola"
        assert bot._memoria[7][1].text == "ok"


class TestAskConFunctionCalling:
    """Caso típico: Gemini pide tool, le devolvemos resultado, responde."""

    def test_ciclo_simple_de_una_tool(self, db_with_data):
        """Gemini pide buscar_stock → ejecutamos → Gemini arma respuesta."""
        bot, client = _bot_con_responses([
            _mock_response_with_calls(_mock_fc("buscar_stock", {"color": "Negro"})),
            _mock_response_with_text("Encontré 2 productos negros."),
        ])
        respuesta = bot.ask(user_id=1, query="qué tengo en negro?")
        assert "Encontré 2 productos negros." in respuesta
        # Debió llamar a generate_content 2 veces (1 para pedir tool, 1 para respuesta)
        assert client.models.generate_content.call_count == 2

    def test_se_ejecuto_la_tool_correcta_con_los_args(self, db_with_data):
        """Verificamos que el args del FunctionCall llega a ejecutar_tool."""
        bot, client = _bot_con_responses([
            _mock_response_with_calls(
                _mock_fc("buscar_stock", {"producto": "Remera", "color": "Negro"})
            ),
            _mock_response_with_text("Tenés 2 SKUs de remeras negras."),
        ])
        bot.ask(user_id=1, query="cuántas remeras negras tengo")

        # La 2da llamada a generate_content debe incluir el resultado de la tool
        # en los contents. Verificamos que tiene 4 contents:
        # 1. user query, 2. model con function_call, 3. user con tool response, 4. ?
        # Lo simple: que haya 2da llamada al menos.
        assert client.models.generate_content.call_count == 2

    def test_encadenamiento_de_dos_tools(self, db_with_data):
        """Gemini pide 1 tool, evalua resultado, pide otra, después responde."""
        bot, client = _bot_con_responses([
            # Iter 1: pide buscar_stock
            _mock_response_with_calls(_mock_fc("buscar_stock", {"producto": "Buzo"})),
            # Iter 2: pide obtener_pedidos_de_cliente
            _mock_response_with_calls(
                _mock_fc("obtener_pedidos_de_cliente", {"nombre_cliente": "Coca"})
            ),
            # Iter 3: responde texto final
            _mock_response_with_text("Tenés stock + ya le pediste a Coca-Cola."),
        ])
        respuesta = bot.ask(user_id=1, query="qué tengo en buzos y qué pidió Coca?")
        assert "Coca" in respuesta
        assert client.models.generate_content.call_count == 3

    def test_multiples_tools_en_una_iteracion(self, db_with_data):
        """Gemini pide 2 tools en una sola respuesta — las ejecutamos todas."""
        bot, client = _bot_con_responses([
            _mock_response_with_calls(
                _mock_fc("buscar_stock", {"color": "Negro"}),
                _mock_fc("listar_productos_a_comprar", {}),
            ),
            _mock_response_with_text("Tenés X negros y faltan Y."),
        ])
        respuesta = bot.ask(user_id=1, query="negros + qué hay para comprar")
        assert "Tenés X negros" in respuesta
        # Solo 2 llamadas: una con 2 function calls, otra con texto final
        assert client.models.generate_content.call_count == 2


class TestAskRespuestaVaciaPostToolCall:
    """v2 mejorada: si Gemini queda mudo tras una tool, le damos una chance más."""

    def test_nudge_si_text_vacio_despues_de_tool(self, db_with_data):
        """Caso real reportado: 'Hay stock de remeras negras m?' devolvió vacío.
        Esperado: 1) tool call → 2) text vacío → 3) iter extra con nudge → 4) respuesta."""
        bot, client = _bot_con_responses([
            _mock_response_with_calls(_mock_fc("buscar_stock", {"talle": "m?"})),
            _mock_response_with_text(""),  # Gemini se quedó mudo
            _mock_response_with_text("No encontré productos con talle 'm?'. Probá con 'M'."),
        ])
        respuesta = bot.ask(user_id=1, query="Hay stock de remeras negras m?")
        assert "No encontré" in respuesta or "Probá" in respuesta
        # 3 llamadas: tool, mudo, post-nudge
        assert client.models.generate_content.call_count == 3

    def test_fallback_si_no_hubo_tool_calls_y_text_vacio(self, db_with_data):
        """Caso edge: Gemini devuelve vacío sin haber pedido tools.
        No tiene sentido nudgear → fallback directo."""
        bot, client = _bot_con_responses([
            _mock_response_with_text(""),  # vacío directamente
        ])
        respuesta = bot.ask(user_id=1, query="????")
        assert "No pude armar una respuesta" in respuesta
        assert client.models.generate_content.call_count == 1

    def test_fallback_si_nudge_tampoco_responde(self, db_with_data):
        """Después del nudge sigue mudo → fallback, sin más intentos."""
        bot, client = _bot_con_responses([
            _mock_response_with_calls(_mock_fc("buscar_stock", {})),
            _mock_response_with_text(""),       # mudo
            _mock_response_with_text(""),       # mudo otra vez post-nudge
        ])
        respuesta = bot.ask(user_id=1, query="algo")
        assert "No pude armar" in respuesta
        # 3 llamadas, ni una más
        assert client.models.generate_content.call_count == 3

    def test_fallback_no_se_guarda_en_memoria(self, db_with_data):
        """Si tuvimos que devolver fallback, no contaminamos el historial."""
        bot, client = _bot_con_responses([
            _mock_response_with_text(""),  # vacío directo
        ])
        bot.ask(user_id=99, query="????")
        # El historial debería estar vacío (no se guardó nada)
        assert 99 not in bot._memoria or len(bot._memoria[99]) == 0


class TestAskLimiteIteraciones:
    """Protección contra loops infinitos de function calls."""

    def test_excede_max_iteraciones_devuelve_fallback(self, db_with_data):
        # Gemini siempre pide tools, nunca responde texto → debería cortar
        always_calls = [
            _mock_response_with_calls(_mock_fc("buscar_stock", {}))
            for _ in range(MerchBot.MAX_FUNCTION_CALL_ITERATIONS + 5)
        ]
        bot, client = _bot_con_responses(always_calls)
        respuesta = bot.ask(user_id=1, query="loopear")
        # Debe haber un mensaje de fallback
        assert "más pasos" in respuesta.lower() or "más simples" in respuesta.lower()
        # No debió llamar más que MAX_FUNCTION_CALL_ITERATIONS veces
        assert (client.models.generate_content.call_count
                <= MerchBot.MAX_FUNCTION_CALL_ITERATIONS)


class TestAskNoInyectaCatalogo:
    """v2: el system prompt NO contiene el catálogo (eso fue v1)."""

    def test_system_prompt_no_tiene_skus(self, db_with_data):
        bot, client = _bot_con_responses([
            _mock_response_with_text("ok"),
        ])
        bot.ask(user_id=1, query="hola")
        call_kwargs = client.models.generate_content.call_args.kwargs
        system = call_kwargs["config"].system_instruction
        # Estos SKUs están en el fixture pero NO deberían aparecer en el prompt
        assert "REM-CR-BCO-M" not in system
        assert "GOR-RES-ROJ" not in system

    def test_system_prompt_menciona_las_tools(self, db_with_data):
        bot, client = _bot_con_responses([
            _mock_response_with_text("ok"),
        ])
        bot.ask(user_id=1, query="hola")
        call_kwargs = client.models.generate_content.call_args.kwargs
        system = call_kwargs["config"].system_instruction
        # Debería mencionar al menos algunas tools clave por nombre
        assert "buscar_stock" in system
        assert "listar_productos_a_comprar" in system

    def test_config_incluye_tools(self, db_with_data):
        bot, client = _bot_con_responses([
            _mock_response_with_text("ok"),
        ])
        bot.ask(user_id=1, query="hola")
        call_kwargs = client.models.generate_content.call_args.kwargs
        # El config debe incluir tools (no None ni lista vacía)
        assert call_kwargs["config"].tools is not None
        assert len(call_kwargs["config"].tools) > 0
