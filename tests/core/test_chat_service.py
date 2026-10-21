"""Tests de ChatService: la puerta de entrada común a todas las interfaces."""
from unittest.mock import MagicMock, patch

import pytest

from merchbot.core import chat_service as cs_module
from merchbot.core.assistant import Respuesta
from merchbot.core.chat_service import (
    MAX_MESSAGE_LEN,
    MENSAJE_DEMASIADO_LARGO,
    MENSAJE_VACIO,
    ChatService,
    get_chat_service,
)
from merchbot.core.memory import InMemoryConversationStore
from merchbot.core.registro import listar_interacciones


@pytest.fixture
def assistant():
    fake = MagicMock()
    fake.responder.return_value = Respuesta("Tenés 20 unidades.", ["buscar_stock"])
    fake.clear_memory.return_value = 4
    return fake


class TestAtender:
    def test_delega_en_el_asistente(self, assistant):
        service = ChatService(assistant=assistant)
        assert service.ask(1, "cuántas remeras?") == "Tenés 20 unidades."
        args, kwargs = assistant.responder.call_args
        assert args == (1, "cuántas remeras?")
        assert kwargs["canal"] == "web"

    def test_recorta_espacios_antes_de_delegar(self, assistant):
        ChatService(assistant=assistant).ask(1, "   hola   ")
        assert assistant.responder.call_args.args[1] == "hola"

    @pytest.mark.parametrize("mensaje", ["", "   ", None])
    def test_mensaje_vacio_no_llama_al_modelo(self, assistant, mensaje):
        assert ChatService(assistant=assistant).ask(1, mensaje) == MENSAJE_VACIO
        assistant.responder.assert_not_called()

    def test_mensaje_demasiado_largo_no_llama_al_modelo(self, assistant):
        texto = "a" * (MAX_MESSAGE_LEN + 1)
        assert ChatService(assistant=assistant).ask(1, texto) == MENSAJE_DEMASIADO_LARGO
        assistant.responder.assert_not_called()

    def test_acepta_ids_de_texto_para_la_web(self, assistant):
        ChatService(assistant=assistant).ask("sesion-abc", "hola")
        assert assistant.responder.call_args.args[0] == "sesion-abc"

    def test_hora_simulada_llega_al_asistente(self, assistant):
        a = ChatService(assistant=assistant).atender(1, "hola", hora_simulada="03:20")
        momento = assistant.responder.call_args.kwargs["momento"]
        assert momento.hora == "03:20" and momento.simulada
        assert a.hora == "03:20"
        assert a.fuera_de_horario is True

    def test_hora_invalida(self, assistant):
        with pytest.raises(ValueError):
            ChatService(assistant=assistant).atender(1, "hola", hora_simulada="25:99")

    def test_devuelve_el_tipo_de_consulta(self, assistant):
        assert ChatService(assistant=assistant).atender(1, "hola").tipo == "stock"


class TestRegistroDeInteracciones:
    def test_cada_consulta_queda_registrada(self, assistant):
        ChatService(assistant=assistant).atender("s1", "cuántas remeras?", canal="telegram",
                                                 hora_simulada="22:45")
        [i] = listar_interacciones()
        assert i["canal"] == "telegram"
        assert i["user_id"] == "s1"
        assert i["hora_simulada"] == "22:45" and i["hora_es_simulada"]
        assert i["fuera_de_horario"] is True
        assert i["tipo"] == "stock"
        assert i["herramientas"] == ["buscar_stock"]
        assert i["respuesta"] == "Tenés 20 unidades."
        assert i["estado"] == "ok"

    def test_un_error_del_modelo_tambien_se_registra(self, assistant):
        assistant.responder.side_effect = RuntimeError("Gemini caído")
        with pytest.raises(RuntimeError):
            ChatService(assistant=assistant).atender("s1", "hola")
        [i] = listar_interacciones()
        assert i["estado"] == "error"
        assert i["respuesta"] is None

    def test_respuesta_de_respaldo_queda_como_error(self, assistant):
        assistant.responder.return_value = Respuesta("No pude armar...", [], completa=False)
        ChatService(assistant=assistant).atender("s1", "hola")
        assert listar_interacciones()[0]["estado"] == "error"

    def test_mensaje_vacio_no_se_registra(self, assistant):
        ChatService(assistant=assistant).atender("s1", "  ")
        assert listar_interacciones() == []

    def test_atajos_se_registran_si_hay_usuario(self, assistant, db_with_data):
        service = ChatService(assistant=assistant)
        service.productos_a_comprar()                       # sin usuario: no registra
        service.productos_a_comprar("s1", hora_simulada="03:00")
        service.resumen_ejecutivo("s1")
        tipos = [i["tipo"] for i in listar_interacciones()]
        assert tipos == ["resumen", "reposicion"]


class TestReclamos:
    def test_registrar_desde_formulario(self, assistant):
        r = ChatService(assistant=assistant).registrar_reclamo(
            "s1", "Llegaron 10 gorras rotas", "producto_defectuoso", "Globant",
            hora_simulada="02:10",
        )
        assert r["ok"] and r["numero"] == 1
        assert r["fuera_de_horario"] is True
        assert r["hora"] == "02:10"
        assert listar_interacciones()[0]["tipo"] == "reclamo"

    def test_consultar(self, assistant):
        service = ChatService(assistant=assistant)
        numero = service.registrar_reclamo("s1", "Pedido demorado")["numero"]
        assert service.consultar_reclamo(numero)["estado"] == "abierto"


class TestCreacionDiferida:
    def test_no_crea_el_asistente_hasta_usarlo(self):
        factory = MagicMock()
        factory.return_value.responder.return_value = Respuesta("ok")
        service = ChatService(assistant_factory=factory)
        factory.assert_not_called()
        service.ask(1, "hola")
        factory.assert_called_once()

    def test_reusa_la_misma_instancia(self):
        factory = MagicMock()
        factory.return_value.responder.return_value = Respuesta("ok")
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

    def test_history_devuelve_la_conversacion_guardada(self):
        store = InMemoryConversationStore()
        store.append("s1", "user", "hola", hora="10:00")
        service = ChatService(assistant=MagicMock(memoria=store))
        [turno] = service.history("s1")
        assert (turno.text, turno.hora) == ("hola", "10:00")


def test_el_asistente_por_defecto_guarda_en_la_base():
    from merchbot.core.chat_service import crear_asistente_persistente
    from merchbot.core.memory import SqlConversationStore

    with patch("merchbot.core.assistant.genai.Client"):
        bot = crear_asistente_persistente()
    assert isinstance(bot.memoria, SqlConversationStore)


def test_get_chat_service_es_singleton(monkeypatch):
    monkeypatch.setattr(cs_module, "_chat_service", None)
    assert get_chat_service() is get_chat_service()


def test_el_reclamo_queda_en_la_conversacion(assistant):
    store = InMemoryConversationStore()
    assistant.memoria = store
    ChatService(assistant=assistant).registrar_reclamo("s1", "Faltan 5 gorras", hora_simulada="02:00")
    textos = [t.text for t in store.history("s1")]
    assert textos[0] == "Reclamo: Faltan 5 gorras"
    assert "#1" in textos[1]
    assert {t.hora for t in store.history("s1")} == {"02:00"}


def test_reclamo_sin_asistente_disponible_igual_se_registra():
    def sin_clave():
        raise ValueError("No API key")
    r = ChatService(assistant_factory=sin_clave).registrar_reclamo("s1", "Faltan 5 gorras")
    assert r["ok"]


def test_created_at_lleva_zona_horaria(assistant):
    r = ChatService(assistant=assistant).registrar_reclamo("s1", "Faltan 5 gorras")
    assert r["created_at"].endswith("+00:00")

