"""Tests de la API web (FastAPI) con el asistente reemplazado por un doble."""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from merchbot.config import settings
from merchbot.core.chat_service import ChatService
from merchbot.core.memory import InMemoryConversationStore
from merchbot.interfaces.web.app import SESSION_COOKIE, create_app


class AsistenteFalso:
    """Responde con eco y guarda la conversación como el real."""

    HISTORIAL_MAX_TURNOS = 10

    def __init__(self):
        self.memoria = InMemoryConversationStore()
        self.falla = False

    def ask(self, user_id, query):
        if self.falla:
            raise RuntimeError("Gemini caído")
        respuesta = f"eco: {query}"
        self.memoria.append(user_id, "user", query)
        self.memoria.append(user_id, "model", respuesta)
        return respuesta

    def clear_memory(self, user_id):
        return self.memoria.clear(user_id)


@pytest.fixture
def asistente():
    return AsistenteFalso()


@pytest.fixture
def client(asistente):
    service = ChatService(assistant=asistente)
    with TestClient(create_app(service_factory=lambda: service)) as c:
        yield c


class TestPaginas:
    def test_index_sirve_el_chat(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "MerchBot" in r.text
        assert "text/html" in r.headers["content-type"]

    def test_health(self, client, monkeypatch):
        monkeypatch.setattr(settings, "data_source", "demo")
        r = client.get("/health")
        assert r.json()["status"] == "ok"
        assert r.json()["fuente_de_datos"] == "demo"


class TestChat:
    def test_responde_y_crea_cookie_de_sesion(self, client):
        r = client.post("/api/chat", json={"message": "hola"})
        assert r.status_code == 200
        assert r.json() == {"reply": "eco: hola"}
        assert SESSION_COOKIE in r.cookies

    def test_la_cookie_es_httponly(self, client):
        r = client.post("/api/chat", json={"message": "hola"})
        assert "httponly" in r.headers["set-cookie"].lower()

    def test_mantiene_la_misma_sesion(self, client, asistente):
        client.post("/api/chat", json={"message": "uno"})
        client.post("/api/chat", json={"message": "dos"})
        sesiones = list(asistente.memoria._data.keys())
        assert len(sesiones) == 1
        assert sesiones[0].startswith("web:")

    def test_cookie_manipulada_se_reemplaza(self, client, asistente):
        client.cookies.set(SESSION_COOKIE, "../../etc/passwd")
        client.post("/api/chat", json={"message": "hola"})
        sesion = next(iter(asistente.memoria._data))
        assert "passwd" not in sesion

    def test_mensaje_demasiado_largo_es_rechazado(self, client):
        r = client.post("/api/chat", json={"message": "a" * 2001})
        assert r.status_code == 422

    def test_falta_el_mensaje(self, client):
        assert client.post("/api/chat", json={}).status_code == 422

    def test_error_del_modelo_devuelve_502_con_mensaje_claro(self, client, asistente):
        asistente.falla = True
        r = client.post("/api/chat", json={"message": "hola"})
        assert r.status_code == 502
        assert "Probá de nuevo" in r.json()["detail"]
        assert "Gemini caído" not in r.text  # no se filtran detalles internos


class TestHistorial:
    def test_devuelve_la_conversacion(self, client):
        client.post("/api/chat", json={"message": "hola"})
        r = client.get("/api/historial")
        assert r.json()["mensajes"] == [
            {"role": "user", "text": "hola"},
            {"role": "model", "text": "eco: hola"},
        ]

    def test_cada_navegador_ve_solo_lo_suyo(self, asistente):
        service = ChatService(assistant=asistente)
        app = create_app(service_factory=lambda: service)
        with TestClient(app) as a, TestClient(app) as b:
            a.post("/api/chat", json={"message": "secreto de A"})
            assert b.get("/api/historial").json()["mensajes"] == []

    def test_borrar(self, client):
        client.post("/api/chat", json={"message": "hola"})
        assert client.delete("/api/historial").json() == {"borrados": 2}
        assert client.get("/api/historial").json()["mensajes"] == []


class TestAtajos:
    def test_comprar(self, client, db_with_data):
        r = client.get("/api/comprar").json()
        assert r["cantidad"] == 2
        assert {p["sku"] for p in r["productos"]} == {"REM-DF-NEG-M", "GOR-RES-ROJ"}

    def test_resumen_convierte_tuplas_en_objetos(self, client, db_with_data):
        r = client.get("/api/resumen").json()
        assert r["total_skus"] == 4
        assert r["top_cliente"] == {"nombre": "Coca-Cola - Evento", "unidades": 120}

    def test_resumen_con_base_vacia(self, client):
        r = client.get("/api/resumen").json()
        assert r["total_skus"] == 0
        assert r["top_cliente"] is None

    def test_sync_con_demo(self, client, monkeypatch):
        from pathlib import Path

        monkeypatch.setattr(settings, "data_source", "demo")
        monkeypatch.setattr(
            settings, "demo_xlsx_path",
            Path(__file__).resolve().parents[2] / "data" / "Stock_Merchandising_Demo.xlsx",
        )
        r = client.post("/api/sync")
        assert r.status_code == 200
        assert r.json() == {"fuente": "demo", "productos": 37, "pedidos": 21}

    def test_sync_que_falla_devuelve_502(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "data_source", "demo")
        monkeypatch.setattr(settings, "demo_xlsx_path", tmp_path / "no-existe.xlsx")
        assert client.post("/api/sync").status_code == 502


def test_on_startup_se_ejecuta_al_arrancar():
    arranque = MagicMock()
    with TestClient(create_app(service_factory=MagicMock, on_startup=arranque)):
        pass
    arranque.assert_called_once()
