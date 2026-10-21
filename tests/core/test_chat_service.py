"""Tests de ChatService: la puerta de entrada común a todas las interfaces."""
from unittest.mock import MagicMock

import pytest

from merchbot.core import chat_service as cs_module
from merchbot.core.chat_service import (
    MAX_MESSAGE_LEN,
    MENSAJE_DEMASIADO_LARGO,
    MENSAJE_VACIO,
    ChatService,
    get_chat_service,
)


@pytest.fixture
def assistant():
    fake = MagicMock()
    fake.ask.return_value = "Tenés 20 unidades."
    fake.clear_memory.return_value = 4
    return fake


class TestAsk:
    def test_delega_en_el_asistente(self, assistant):
        service = ChatService(assistant=assistant)
        assert service.ask(1, "cuántas remeras?") == "Tenés 20 unidades."
        assistant.ask.assert_called_once_with(1, "cuántas remeras?")

    def test_recorta_espacios_antes_de_delegar(self, assistant):
        ChatService(assistant=assistant).ask(1, "   hola   ")
        assistant.ask.assert_called_once_with(1, "hola")

    @pytest.mark.parametrize("mensaje", ["", "   ", None])
    def test_mensaje_vacio_no_llama_al_modelo(self, assistant, mensaje):
        assert ChatService(assistant=assistant).ask(1, mensaje) == MENSAJE_VACIO
        assistant.ask.assert_not_called()

    def test_mensaje_demasiado_largo_no_llama_al_modelo(self, assistant):
        texto = "a" * (MAX_MESSAGE_LEN + 1)
        assert ChatService(assistant=assistant).ask(1, texto) == MENSAJE_DEMASIADO_LARGO
        assistant.ask.assert_not_called()

    def test_acepta_ids_de_texto_para_la_web(self, assistant):
        ChatService(assistant=assistant).ask("sesion-abc", "hola")
        assistant.ask.assert_called_once_with("sesion-abc", "hola")


class TestCreacionDiferida:
    def test_no_crea_el_asistente_hasta_usarlo(self):
        factory = MagicMock()
        service = ChatService(assistant_factory=factory)
        factory.assert_not_called()
        service.ask(1, "hola")
        factory.assert_called_once()

    def test_reusa_la_misma_instancia(self):
        factory = MagicMock()
        service = ChatService(assistant_factory=factory)
        service.ask(1, "a")
        service.ask(1, "b")
        factory.assert_called_once()


class TestOtrasOperaciones:
    def test_clear_devuelve_turnos_borrados(self, assistant):
        assert ChatService(assistant=assistant).clear(9) == 4
        assistant.clear_memory.assert_called_once_with(9)

    def test_atajos_usan_los_reportes(self, db_with_data):
        service = ChatService(assistant=MagicMock())
        assert {p["sku"] for p in service.productos_a_comprar()} == {
            "REM-DF-NEG-M", "GOR-RES-ROJ",
        }
        assert service.resumen_ejecutivo()["total_skus"] == 4


def test_get_chat_service_es_singleton(monkeypatch):
    monkeypatch.setattr(cs_module, "_chat_service", None)
    assert get_chat_service() is get_chat_service()


def test_history_devuelve_la_conversacion_guardada():
    from merchbot.core.memory import InMemoryConversationStore

    store = InMemoryConversationStore()
    store.append("s1", "user", "hola")
    service = ChatService(assistant=MagicMock(memoria=store))
    assert [t.text for t in service.history("s1")] == ["hola"]


def test_el_asistente_por_defecto_guarda_en_la_base(monkeypatch):
    from unittest.mock import patch

    from merchbot.core.chat_service import crear_asistente_persistente
    from merchbot.core.memory import SqlConversationStore

    with patch("merchbot.core.assistant.genai.Client"):
        bot = crear_asistente_persistente()
    assert isinstance(bot.memoria, SqlConversationStore)
