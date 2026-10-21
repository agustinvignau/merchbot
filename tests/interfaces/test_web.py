"""Tests de la API web (FastAPI) con el asistente reemplazado por un doble."""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from merchbot.config import settings
from merchbot.core.assistant import Respuesta
from merchbot.core.chat_service import ChatService
from merchbot.core.memory import InMemoryConversationStore
from merchbot.interfaces.web.app import SESSION_COOKIE, create_app


class AsistenteFalso:
    """Responde con eco y guarda la conversación como el real."""

    HISTORIAL_MAX_TURNOS = 10

    def __init__(self):
        self.memoria = InMemoryConversationStore()
        self.falla = False
        self.ultimo_momento = None

    def responder(self, user_id, query, momento=None, canal="web"):
        if self.falla:
            raise RuntimeError("Gemini caído")
        self.ultimo_momento = momento
        respuesta = f"eco: {query}"
        self.memoria.append(user_id, "user", query, hora=momento.hora)
        self.memoria.append(user_id, "model", respuesta, hora=momento.hora)
        fuentes = ["Guía de talles"] if "talle" in query else []
        return Respuesta(respuesta, ["buscar_stock"], fuentes=fuentes)

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
        assert r.json()["reply"] == "eco: hola"
        assert r.json()["tipo"] == "stock"
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
        assert "Probá de nuevo" in r.json()["detail"]   # error genérico: mensaje genérico
        assert "Gemini caído" not in r.text  # no se filtran detalles internos


class TestHistorial:
    def test_devuelve_la_conversacion(self, client):
        client.post("/api/chat", json={"message": "hola"})
        r = client.get("/api/historial")
        mensajes = r.json()["mensajes"]
        assert [(m["role"], m["text"]) for m in mensajes] == [("user", "hola"), ("model", "eco: hola")]
        assert all(m["hora"] for m in mensajes)

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


class TestHoraSimulada:
    def test_la_hora_simulada_llega_al_asistente_y_vuelve(self, client, asistente):
        r = client.post("/api/chat", json={"message": "hola", "hora": "03:20"}).json()
        assert r["hora"] == "03:20"
        assert r["fuera_de_horario"] is True
        assert asistente.ultimo_momento.simulada

    def test_sin_hora_usa_la_real(self, client, asistente):
        r = client.post("/api/chat", json={"message": "hola"}).json()
        assert not asistente.ultimo_momento.simulada
        assert len(r["hora"]) == 5

    def test_hora_invalida_es_422(self, client):
        r = client.post("/api/chat", json={"message": "hola", "hora": "27:00"})
        assert r.status_code == 422
        assert "HH:MM" in r.json()["detail"]

    def test_queda_en_el_historial(self, client):
        client.post("/api/chat", json={"message": "hola", "hora": "22:45"})
        assert client.get("/api/historial").json()["mensajes"][0]["hora"] == "22:45"

    def test_horario(self, client):
        r = client.get("/api/horario").json()
        assert {"hora_actual", "fuera_de_horario", "atencion_desde", "atencion_hasta"} <= r.keys()


class TestReclamosWeb:
    def test_crear_y_consultar(self, client):
        r = client.post("/api/reclamos", json={
            "descripcion": "Llegaron 10 gorras rojas descosidas",
            "tipo": "producto_defectuoso", "cliente": "Globant", "hora": "23:10",
        })
        assert r.status_code == 201
        numero = r.json()["numero"]
        assert r.json()["fuera_de_horario"] is True
        consulta = client.get(f"/api/reclamos/{numero}").json()
        assert consulta["estado"] == "abierto"
        assert consulta["cliente"] == "Globant"

    def test_descripcion_muy_corta(self, client):
        assert client.post("/api/reclamos", json={"descripcion": "mal"}).status_code == 422

    def test_reclamo_inexistente(self, client):
        assert client.get("/api/reclamos/999").status_code == 404

    def test_atajos_quedan_registrados_con_la_sesion(self, client, db_with_data):
        from merchbot.core.registro import listar_interacciones

        client.get("/api/comprar", params={"hora": "04:00"})
        [i] = listar_interacciones()
        assert i["user_id"].startswith("web:")
        assert i["hora_simulada"] == "04:00"


class TestVozWeb:
    def test_origen_voz_normaliza_y_devuelve_la_consulta(self, client):
        r = client.post("/api/chat", json={"message": "treinta remeras talle eme", "origen": "voz"}).json()
        assert r["consulta"] == "30 remeras talle M"
        assert r["reply"] == "eco: 30 remeras talle M"

    def test_por_defecto_es_texto(self, client):
        r = client.post("/api/chat", json={"message": "talle ele"}).json()
        assert r["consulta"] == "talle ele"

    def test_origen_invalido_es_422(self, client):
        assert client.post("/api/chat", json={"message": "hola", "origen": "otro"}).status_code == 422


def test_la_respuesta_incluye_las_fuentes(client):
    assert client.post("/api/chat", json={"message": "medidas del talle L"}).json()["fuentes"] == ["Guía de talles"]
    assert client.post("/api/chat", json={"message": "hola"}).json()["fuentes"] == []


def test_error_de_modelo_no_disponible_se_explica(client, asistente, monkeypatch):
    from google.genai import errors

    def falla(*a, **k):
        raise errors.ClientError(404, {"error": {"code": 404, "status": "NOT_FOUND", "message": "no longer available"}})
    monkeypatch.setattr(asistente, "responder", falla)
    r = client.post("/api/chat", json={"message": "hola"})
    assert r.status_code == 502
    assert "GEMINI_MODEL" in r.json()["detail"]

