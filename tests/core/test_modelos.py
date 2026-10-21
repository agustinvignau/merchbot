"""Cadena de modelos de respaldo ante cuota agotada o modelo dado de baja."""
from unittest.mock import patch

import pytest

from merchbot.config import settings
from merchbot.core import modelos as mod
from merchbot.core.assistant import MerchBot
from tests.core.test_assistant import _mock_fc, _mock_response_with_calls, _mock_response_with_text

MINUTO = ("429 RESOURCE_EXHAUSTED. {'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}, "
          "{'retryDelay': '20s'}")
DIA = "429 RESOURCE_EXHAUSTED. {'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}"
BAJA = "404 NOT_FOUND. models/gemini-viejo is not found"


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_modelos_configurados_sin_repetidos(monkeypatch):
    monkeypatch.setattr(settings, "gemini_modelos_respaldo", " b, a ,, c,b")
    assert mod.modelos_configurados("a") == ["a", "b", "c"]


@pytest.mark.parametrize("texto,motivo,pausa", [
    (MINUTO, "cuota_minuto", 21), (DIA, "cuota_diaria", mod.PAUSA_DIARIA),
    (BAJA, "modelo_no_disponible", mod.PAUSA_MODELO_INEXISTENTE),
])
def test_motivo_y_pausa(texto, motivo, pausa):
    e = Exception(texto)
    assert mod.motivo_para_cambiar(e) == motivo
    assert mod.segundos_de_pausa(e, motivo) == pausa


def test_otros_errores_no_cambian_de_modelo():
    assert mod.motivo_para_cambiar(Exception("400 INVALID_ARGUMENT")) is None
    sel = mod.SelectorDeModelos(["a", "b"])
    llamados = []

    def llamada(m):
        llamados.append(m)
        raise ValueError("roto")

    with pytest.raises(ValueError):
        sel.ejecutar(llamada)
    assert llamados == ["a"]


def test_pasa_al_respaldo_y_vuelve_cuando_se_libera():
    reloj = Reloj()
    sel = mod.SelectorDeModelos(["a", "b"], reloj=reloj)
    agotado = {"a"}

    def llamada(m):
        if m in agotado:
            raise Exception(MINUTO)
        return f"ok-{m}"

    assert sel.ejecutar(llamada) == ("ok-b", "b")
    assert sel.orden() == ["b", "a"]          # 'a' en pausa: ya no se intenta primero
    agotado.clear()
    reloj.t += 22
    assert sel.ejecutar(llamada) == ("ok-a", "a")


def test_si_todos_fallan_sube_el_ultimo_error():
    sel = mod.SelectorDeModelos(["a", "b"], reloj=Reloj())
    with pytest.raises(Exception, match="PerDay"):
        sel.ejecutar(lambda m: (_ for _ in ()).throw(Exception(DIA)))


def test_el_asistente_sigue_con_el_respaldo_sin_repetir_funciones(monkeypatch, db_with_data):
    monkeypatch.setattr(settings, "gemini_modelos_respaldo", "respaldo-lite")
    respuestas = [
        _mock_response_with_calls(_mock_fc("buscar_stock", {"producto": "remera"})),
        Exception(MINUTO),                       # el principal se queda sin cuota a mitad del turno
        _mock_response_with_text("Tenés 100 remeras."),
    ]
    with patch("merchbot.core.assistant.genai.Client") as MockClient:
        client = MockClient.return_value
        client.models.generate_content.side_effect = respuestas
        bot = MerchBot(api_key="fake", modelo="principal")
        with patch("merchbot.core.assistant.ejecutar_tool", return_value={"items": []}) as tool:
            r = bot.responder(1, "¿cuántas remeras?")
    assert r.texto == "Tenés 100 remeras." and r.modelo == "respaldo-lite"
    usados = [c.kwargs["model"] for c in client.models.generate_content.call_args_list]
    assert usados == ["principal", "principal", "respaldo-lite"]
    assert tool.call_count == 1
