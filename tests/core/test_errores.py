"""Los errores de Gemini se traducen a mensajes accionables."""
import pytest
from google.genai import errors

from merchbot.core.errores import describir_error


def _api(code, status, message):
    return errors.ClientError(code, {"error": {"code": code, "status": status, "message": message}})


@pytest.mark.parametrize("exc,codigo", [
    (ValueError("No API key was provided. Please pass a valid API key."), "sin_api_key"),
    (_api(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key."), "api_key_invalida"),
    (_api(404, "NOT_FOUND", "This model models/gemini-2.5-flash is no longer available."), "modelo_no_disponible"),
    (_api(429, "RESOURCE_EXHAUSTED", "Quota exceeded"), "cuota_agotada"),
    (_api(403, "PERMISSION_DENIED", "Permission denied"), "sin_permiso"),
    (errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "overloaded"}}), "servicio_no_disponible"),
    (ConnectionError("Connection refused"), "sin_conexion"),
    (RuntimeError("algo raro"), "error_desconocido"),
])
def test_clasifica(exc, codigo):
    assert describir_error(exc).codigo == codigo


def test_el_mensaje_no_incluye_la_clave(monkeypatch):
    from merchbot.config import settings
    monkeypatch.setattr(settings, "gemini_api_key", "AIzaSECRETA")
    assert "AIzaSECRETA" not in describir_error(_api(400, "INVALID_ARGUMENT", "API key not valid")).mensaje


def test_modelo_no_disponible_nombra_el_modelo_configurado(monkeypatch):
    from merchbot.config import settings
    monkeypatch.setattr(settings, "gemini_model", "gemini-viejo")
    assert "gemini-viejo" in describir_error(_api(404, "NOT_FOUND", "x")).mensaje
