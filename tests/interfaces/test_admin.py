"""Tests de la API del panel admin."""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from merchbot.config import settings
from merchbot.core.horario import resolver_momento
from merchbot.core.registro import registrar_interaccion
from merchbot.core.tools import registrar_reclamo
from merchbot.interfaces.web.admin import ADMIN_COOKIE
from merchbot.interfaces.web.app import create_app

CLAVE = "clave-de-prueba"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "admin_key", CLAVE)
    with TestClient(create_app(service_factory=MagicMock)) as c:
        yield c


@pytest.fixture
def logueado(client):
    assert client.post("/api/admin/login", json={"clave": CLAVE}).status_code == 200
    return client


@pytest.fixture
def actividad():
    for hora, tools in [("10:00", ["buscar_stock"]), ("03:20", ["registrar_reclamo"]), ("22:45", [])]:
        registrar_interaccion(canal="web", user_id="u", momento=resolver_momento(hora), consulta="q",
                              respuesta="r", herramientas=tools, duracion_ms=50)
    registrar_reclamo("Remeras manchadas", "producto_defectuoso")


class TestAcceso:
    def test_la_pagina_se_sirve_siempre(self, client):
        r = client.get("/admin")
        assert r.status_code == 200 and "Panel" in r.text

    @pytest.mark.parametrize("ruta", ["/api/admin/metricas", "/api/admin/interacciones", "/api/admin/reclamos"])
    def test_sin_login_es_401(self, client, ruta):
        assert client.get(ruta).status_code == 401

    def test_clave_incorrecta(self, client):
        assert client.post("/api/admin/login", json={"clave": "otra"}).status_code == 401
        assert client.get("/api/admin/estado").json() == {"configurado": True, "autenticado": False}

    def test_login_deja_cookie_httponly_strict(self, client):
        r = client.post("/api/admin/login", json={"clave": CLAVE})
        cookie = r.headers["set-cookie"].lower()
        assert ADMIN_COOKIE in cookie and "httponly" in cookie and "samesite=strict" in cookie
        assert CLAVE not in r.headers["set-cookie"]   # la cookie no es la clave

    def test_header_para_scripts(self, client):
        assert client.get("/api/admin/metricas", headers={"X-Admin-Key": CLAVE}).status_code == 200

    def test_cookie_falsa(self, client):
        client.cookies.set(ADMIN_COOKIE, "0" * 64)
        assert client.get("/api/admin/metricas").status_code == 401

    def test_logout(self, logueado):
        logueado.post("/api/admin/logout")
        logueado.cookies.clear()
        assert logueado.get("/api/admin/metricas").status_code == 401

    def test_sin_admin_key_el_panel_esta_deshabilitado(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_key", "")
        with TestClient(create_app(service_factory=MagicMock)) as c:
            assert c.post("/api/admin/login", json={"clave": ""}).status_code == 503
            assert c.get("/api/admin/metricas").status_code == 503
            assert c.get("/api/admin/estado").json()["configurado"] is False

    def test_cambiar_la_clave_invalida_las_sesiones(self, logueado, monkeypatch):
        monkeypatch.setattr(settings, "admin_key", "clave-nueva")
        assert logueado.get("/api/admin/metricas").status_code == 401


class TestDatos:
    def test_metricas(self, logueado, actividad):
        m = logueado.get("/api/admin/metricas").json()
        assert m["totales"]["interacciones"] == 3
        assert m["totales"]["reclamos_abiertos"] == 1
        assert sum(m["por_hora"]) == 3

    def test_metricas_todo_el_historial(self, logueado, actividad):
        assert logueado.get("/api/admin/metricas", params={"todo": True}).json()["periodo_dias"] is None

    def test_interacciones_con_filtros(self, logueado, actividad):
        r = logueado.get("/api/admin/interacciones", params={"tipo": "reclamo"}).json()
        assert r["cantidad"] == 1

    def test_reclamos_y_cambio_de_estado(self, logueado, actividad):
        assert logueado.get("/api/admin/reclamos").json()["cantidad"] == 1
        r = logueado.patch("/api/admin/reclamos/1", json={"estado": "resuelto"})
        assert r.json()["estado"] == "resuelto"
        assert logueado.get("/api/admin/reclamos", params={"estado": "abierto"}).json()["cantidad"] == 0

    def test_estado_invalido_y_reclamo_inexistente(self, logueado, actividad):
        assert logueado.patch("/api/admin/reclamos/1", json={"estado": "x"}).status_code == 422
        assert logueado.patch("/api/admin/reclamos/9", json={"estado": "resuelto"}).status_code == 404
        assert logueado.get("/api/admin/reclamos", params={"estado": "x"}).status_code == 422
