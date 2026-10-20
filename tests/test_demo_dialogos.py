"""El guion de demo corre de punta a punta (con un asistente falso)."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

from merchbot.core.assistant import Respuesta
from merchbot.core.chat_service import ChatService
from merchbot.core.registro import listar_interacciones

RUTA = Path(__file__).resolve().parents[1] / "scripts" / "demo_dialogos.py"
spec = importlib.util.spec_from_file_location("demo_dialogos", RUTA)
demo = importlib.util.module_from_spec(spec)
sys.modules["demo_dialogos"] = demo   # dataclasses lo necesitan registrado
spec.loader.exec_module(demo)


def _servicio():
    asistente = MagicMock()
    asistente.responder.side_effect = lambda uid, q, momento, canal: Respuesta(f"respuesta a: {q}", ["buscar_stock"])
    return ChatService(assistant=asistente)


def test_cubre_al_menos_cuatro_situaciones_a_horas_distintas():
    assert len(demo.GUION) >= 4
    assert len({e.hora for e in demo.GUION}) == len(demo.GUION)
    assert any(e.hora < "06:00" for e in demo.GUION)       # madrugada
    assert any("09:00" <= e.hora < "18:00" for e in demo.GUION)


def test_corre_y_registra_cada_mensaje():
    resultados = demo.correr_guion(_servicio())
    total = sum(len(e.mensajes) for e in demo.GUION)
    assert sum(len(r["turnos"]) for r in resultados) == total
    interacciones = listar_interacciones()
    assert len(interacciones) == total
    assert {i["canal"] for i in interacciones} == {"demo"}
    assert {i["hora_simulada"] for i in interacciones} == {e.hora for e in demo.GUION}


def test_genera_markdown():
    md = demo.a_markdown(demo.correr_guion(_servicio()), "gemini-test")
    assert md.startswith("# Diálogos de demostración")
    for esc in demo.GUION:
        assert esc.titulo in md
    assert "fuera de horario" in md and "en horario" in md
