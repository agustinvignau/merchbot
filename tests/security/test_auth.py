"""Tests de claves, usuarios y tokens de sesión."""
import pytest

from merchbot.config import settings
from merchbot.security import auth


@pytest.fixture
def con_usuarios(monkeypatch):
    monkeypatch.setattr(settings, "secret_key", "secreto-de-prueba")
    monkeypatch.setattr(settings, "chat_usuarios", f"Ana:clave-ana-123, beto:{auth.hashear_clave('clave-beto-456', 1000)}")


class TestClaves:
    def test_hash_y_verificacion(self):
        h = auth.hashear_clave("una clave larga", iteraciones=1000)
        assert h.startswith("pbkdf2_sha256$1000$")
        assert auth.verificar_clave(h, "una clave larga")
        assert not auth.verificar_clave(h, "otra clave")

    def test_cada_hash_tiene_su_sal(self):
        assert auth.hashear_clave("x" * 12, 1000) != auth.hashear_clave("x" * 12, 1000)

    def test_texto_plano(self):
        assert auth.verificar_clave("abc", "abc") and not auth.verificar_clave("abc", "abd")

    def test_hash_mal_formado(self):
        assert not auth.verificar_clave("pbkdf2_sha256$nope", "x")


class TestUsuarios:
    def test_parseo(self, con_usuarios):
        assert set(auth.usuarios()) == {"ana", "beto"}
        assert auth.login_requerido()

    def test_entradas_rotas_se_ignoran(self, monkeypatch):
        monkeypatch.setattr(settings, "chat_usuarios", "sinclave, :x, ok:1234567890")
        assert set(auth.usuarios()) == {"ok"}

    def test_vacio_no_requiere_login(self, monkeypatch):
        monkeypatch.setattr(settings, "chat_usuarios", "")
        assert not auth.login_requerido()

    def test_autenticar(self, con_usuarios):
        assert auth.autenticar("ANA ", "clave-ana-123") == "ana"
        assert auth.autenticar("beto", "clave-beto-456") == "beto"
        assert auth.autenticar("beto", "mala") is None
        assert auth.autenticar("nadie", "clave-ana-123") is None


class TestTokens:
    def test_ida_y_vuelta(self, con_usuarios):
        assert auth.leer_token(auth.crear_token("ana")) == "ana"

    def test_firma_alterada(self, con_usuarios):
        token = auth.crear_token("ana")
        datos, firma = token.rsplit(".", 1)
        otro = auth.crear_token("beto").rsplit(".", 1)[0]
        assert auth.leer_token(f"{otro}.{firma}") is None
        assert auth.leer_token(f"{datos}.{'0' * 64}") is None

    def test_vencido(self, con_usuarios):
        token = auth.crear_token("ana", horas=1, ahora=1_000_000)
        assert auth.leer_token(token, ahora=1_000_000 + 3599) == "ana"
        assert auth.leer_token(token, ahora=1_000_000 + 3601) is None

    def test_otra_clave_secreta_invalida(self, con_usuarios, monkeypatch):
        token = auth.crear_token("ana")
        monkeypatch.setattr(settings, "secret_key", "otra")
        assert auth.leer_token(token) is None

    def test_usuario_borrado_pierde_la_sesion(self, con_usuarios, monkeypatch):
        token = auth.crear_token("beto")
        monkeypatch.setattr(settings, "chat_usuarios", "ana:clave-ana-123")
        assert auth.leer_token(token) is None

    @pytest.mark.parametrize("basura", [None, "", "sinpunto", "a.b", "!!!.???"])
    def test_basura(self, con_usuarios, basura):
        assert auth.leer_token(basura) is None
