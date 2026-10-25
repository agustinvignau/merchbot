"""Login del chat, límites de uso y cabeceras de seguridad en la web."""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from merchbot.config import settings
from merchbot.core.assistant import Respuesta
from merchbot.core.chat_service import ChatService
from merchbot.core.memory import InMemoryConversationStore
from merchbot.interfaces.web.app import AUTH_COOKIE, create_app
from merchbot.security import limites


def _servicio():
    asistente = MagicMock()
    asistente.memoria = InMemoryConversationStore()

    def responder(uid, q, momento=None, canal="web"):
        asistente.memoria.append(uid, "user", q, hora=momento.hora)
        return Respuesta(f"eco: {q}")
    asistente.responder.side_effect = responder
    return ChatService(assistant=asistente)


@pytest.fixture
def abierto():
    servicio = _servicio()
    with TestClient(create_app(service_factory=lambda: servicio)) as c:
        yield c


@pytest.fixture
def con_login(monkeypatch):
    monkeypatch.setattr(settings, "secret_key", "secreto")
    monkeypatch.setattr(settings, "chat_usuarios", "ana:clave-larga-ana,beto:clave-larga-beto")
    servicio = _servicio()
    with TestClient(create_app(service_factory=lambda: servicio)) as c:
        yield c


def _ingresar(c, usuario="ana", clave="clave-larga-ana"):
    return c.post("/api/login", json={"usuario": usuario, "clave": clave})


class TestSinLogin:
    def test_chat_abierto(self, abierto):
        assert abierto.post("/api/chat", json={"message": "hola"}).status_code == 200
        assert abierto.get("/api/sesion").json() == {"login_requerido": False, "usuario": None}

    def test_login_redirige_al_chat(self, abierto):
        r = abierto.get("/login", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/"


class TestConLogin:
    def test_sin_ingresar_redirige_y_bloquea_la_api(self, con_login):
        r = con_login.get("/", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
        for metodo, ruta in [("post", "/api/chat"), ("get", "/api/historial"), ("get", "/api/comprar"),
                             ("get", "/api/resumen"), ("post", "/api/reclamos"), ("get", "/api/reclamos/1"),
                             ("post", "/api/sync")]:
            kwargs = {"json": {"message": "x", "descripcion": "algo que pasó"}} if metodo == "post" else {}
            assert getattr(con_login, metodo)(ruta, **kwargs).status_code == 401, ruta

    def test_pagina_de_login(self, con_login):
        r = con_login.get("/login")
        assert r.status_code == 200 and "Ingresar" in r.text

    def test_ingresar_y_usar_el_chat(self, con_login):
        r = _ingresar(con_login)
        assert r.status_code == 200 and r.json()["usuario"] == "ana"
        cookie = r.headers["set-cookie"].lower()
        assert AUTH_COOKIE in cookie and "httponly" in cookie and "clave-larga-ana" not in cookie
        assert con_login.post("/api/chat", json={"message": "hola"}).json()["reply"] == "eco: hola"
        assert con_login.get("/api/sesion").json()["usuario"] == "ana"
        assert con_login.get("/", follow_redirects=False).status_code == 200

    def test_la_conversacion_es_del_usuario(self, con_login):
        _ingresar(con_login)
        con_login.post("/api/chat", json={"message": "de ana"})
        con_login.cookies.clear()
        _ingresar(con_login, "beto", "clave-larga-beto")
        assert con_login.get("/api/historial").json()["mensajes"] == []
        con_login.cookies.clear()
        _ingresar(con_login)
        assert con_login.get("/api/historial").json()["mensajes"][0]["text"] == "de ana"

    def test_clave_incorrecta(self, con_login):
        assert _ingresar(con_login, clave="mala").status_code == 401

    def test_logout(self, con_login):
        _ingresar(con_login)
        con_login.post("/api/logout")
        con_login.cookies.clear()
        assert con_login.post("/api/chat", json={"message": "hola"}).status_code == 401

    def test_cookie_falsificada(self, con_login):
        con_login.cookies.set(AUTH_COOKIE, "eyJ1IjoiYW5hIiwiZXhwIjo5OTk5OTk5OTk5fQ." + "0" * 64)
        assert con_login.post("/api/chat", json={"message": "hola"}).status_code == 401


class TestLimites:
    def test_limite_de_intentos_de_login(self, con_login, monkeypatch):
        monkeypatch.setattr(settings, "limite_login_intentos", 3)
        limites.reiniciar()
        codigos = [_ingresar(con_login, clave="mala").status_code for _ in range(4)]
        assert codigos == [401, 401, 401, 429]
        assert _ingresar(con_login).status_code == 429   # bloqueado aunque ahora acierte

    def test_un_ingreso_correcto_limpia_los_intentos(self, con_login, monkeypatch):
        monkeypatch.setattr(settings, "limite_login_intentos", 3)
        limites.reiniciar()
        _ingresar(con_login, clave="mala")
        _ingresar(con_login, clave="mala")
        assert _ingresar(con_login).status_code == 200
        assert _ingresar(con_login, clave="mala").status_code == 401

    def test_limite_de_consultas_por_minuto(self, abierto, monkeypatch):
        monkeypatch.setattr(settings, "limite_chat_por_minuto", 3)
        limites.reiniciar()
        codigos = [abierto.post("/api/chat", json={"message": f"q{i}"}).status_code for i in range(4)]
        assert codigos == [200, 200, 200, 429]
        assert "Esperá un minuto" in abierto.post("/api/chat", json={"message": "x"}).json()["detail"]

    def test_el_limite_es_por_sesion(self, monkeypatch):
        monkeypatch.setattr(settings, "limite_chat_por_minuto", 1)
        limites.reiniciar()
        servicio = _servicio()
        app = create_app(service_factory=lambda: servicio)
        with TestClient(app) as a, TestClient(app) as b:
            assert a.post("/api/chat", json={"message": "1"}).status_code == 200
            assert a.post("/api/chat", json={"message": "2"}).status_code == 429
            assert b.post("/api/chat", json={"message": "1"}).status_code == 200

    def test_limite_de_ingreso_al_panel(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_key", "clave-admin")
        monkeypatch.setattr(settings, "limite_login_intentos", 2)
        limites.reiniciar()
        with TestClient(create_app(service_factory=_servicio)) as c:
            codigos = [c.post("/api/admin/login", json={"clave": "mala"}).status_code for _ in range(3)]
        assert codigos == [401, 401, 429]


class TestCabeceras:
    def test_paginas_con_csp_y_protecciones(self, abierto):
        h = abierto.get("/").headers
        assert "default-src 'self'" in h["content-security-policy"]
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert "microphone=(self)" in h["permissions-policy"]

    def test_api_sin_cache(self, abierto):
        assert abierto.get("/api/horario").headers["cache-control"] == "no-store"

    def test_docs_sin_csp(self, abierto):
        r = abierto.get("/docs")
        assert r.status_code == 200 and "content-security-policy" not in r.headers

    def test_sin_cors_abierto(self, abierto):
        r = abierto.options("/api/chat", headers={"Origin": "https://malicioso.example",
                                                 "Access-Control-Request-Method": "POST"})
        assert "access-control-allow-origin" not in r.headers


class TestHuecosCerrados:
    def test_borrar_la_cookie_no_saltea_el_limite(self, monkeypatch):
        """Sin login, pedir una sesión nueva en cada consulta choca con el límite por IP."""
        monkeypatch.setattr(settings, "limite_chat_por_minuto", 1)
        limites.reiniciar()
        servicio = _servicio()
        with TestClient(create_app(service_factory=lambda: servicio)) as c:
            codigos = []
            for i in range(4):
                c.cookies.clear()
                codigos.append(c.post("/api/chat", json={"message": f"q{i}"}).status_code)
        assert codigos == [200, 200, 200, 429]   # el límite por IP es el triple

    def test_el_header_del_panel_tiene_limite_de_intentos(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_key", "clave-admin-bien-larga")
        monkeypatch.setattr(settings, "limite_login_intentos", 2)
        limites.reiniciar()
        with TestClient(create_app(service_factory=_servicio)) as c:
            codigos = [c.get("/api/admin/metricas", headers={"X-Admin-Key": f"mala{i}"}).status_code
                       for i in range(3)]
            assert codigos == [401, 401, 429]
            # bloqueado aunque ahora acierte
            ok = c.get("/api/admin/metricas", headers={"X-Admin-Key": "clave-admin-bien-larga"})
            assert ok.status_code == 429

    def test_el_header_correcto_sigue_andando(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_key", "clave-admin-bien-larga")
        limites.reiniciar()
        with TestClient(create_app(service_factory=_servicio)) as c:
            r = c.get("/api/admin/metricas", headers={"X-Admin-Key": "clave-admin-bien-larga"})
        assert r.status_code == 200

    def test_sync_tiene_limite_global(self, abierto, monkeypatch):
        from merchbot.data import refresh

        resultado = MagicMock(ok=True, stock_total=1, pedidos_total=1, error=None)
        monkeypatch.setattr(refresh, "actualizar_datos", lambda: resultado)
        limites.reiniciar()
        codigos = [abierto.post("/api/sync").status_code for _ in range(3)]
        assert codigos == [200, 200, 429]

    def test_no_se_ven_reclamos_ajenos(self, monkeypatch):
        servicio = _servicio()
        app = create_app(service_factory=lambda: servicio)
        with TestClient(app) as a, TestClient(app) as b:
            r = a.post("/api/reclamos", json={"descripcion": "Llegaron gorras rotas", "tipo": "producto_fallado"})
            numero = r.json()["numero"]
            assert a.get(f"/api/reclamos/{numero}").status_code == 200
            ajeno = b.get(f"/api/reclamos/{numero}")
            assert ajeno.status_code == 404 and "gorras" not in ajeno.text
