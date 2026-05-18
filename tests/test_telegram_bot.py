"""Tests de utilidades del bot de Telegram (sin red)."""
from unittest.mock import patch

import pytest

import src.config as config_module
from src.telegram_bot import (
    _chunk_message,
    es_usuario_autorizado,
    TELEGRAM_MAX_MSG_LEN,
)


class TestChunkMessage:
    def test_texto_corto_no_se_parte(self):
        assert _chunk_message("hola mundo") == ["hola mundo"]

    def test_texto_largo_se_parte(self):
        texto = "linea de prueba\n" * 500
        chunks = _chunk_message(texto, max_len=4000)
        assert len(chunks) > 1
        assert all(len(c) <= 4000 for c in chunks)

    def test_reconstruccion_no_pierde_caracteres(self):
        texto = "\n".join(f"linea {i}" for i in range(300))
        chunks = _chunk_message(texto, max_len=500)
        # Reconstruyendo sin saltos finales/internos
        assert "\n".join(chunks).replace("\n", "") == texto.replace("\n", "")

    def test_respeta_limite_default_telegram(self):
        assert TELEGRAM_MAX_MSG_LEN <= 4096

    def test_no_corta_lineas_innecesariamente(self):
        texto = "primera linea\nsegunda linea\ntercera linea"
        chunks = _chunk_message(texto, max_len=20)
        for chunk in chunks:
            for linea in chunk.split("\n"):
                assert linea in texto


class TestAuthorization:
    """La whitelist es lo único entre el bot y un extraño que vea los datos."""

    def _set_whitelist(self, monkeypatch, raw: str):
        """Helper: pisa la setting de whitelist con un valor de prueba."""
        monkeypatch.setattr(config_module.settings,
                            "telegram_allowed_user_ids", raw)

    def test_whitelist_vacia_permite_a_cualquiera(self, monkeypatch):
        """Modo abierto: si la lista está vacía, todos pasan."""
        self._set_whitelist(monkeypatch, "")
        assert es_usuario_autorizado(123) is True
        assert es_usuario_autorizado(999999) is True

    def test_solo_los_ids_de_la_whitelist_pasan(self, monkeypatch):
        self._set_whitelist(monkeypatch, "111,222,333")
        assert es_usuario_autorizado(111) is True
        assert es_usuario_autorizado(222) is True
        assert es_usuario_autorizado(333) is True
        assert es_usuario_autorizado(444) is False
        assert es_usuario_autorizado(0) is False

    def test_ignora_espacios_y_basura(self, monkeypatch):
        self._set_whitelist(monkeypatch, " 111 , 222 ,abc, , 333")
        # Los espacios se ignoran, 'abc' se descarta porque no es número
        assert es_usuario_autorizado(111) is True
        assert es_usuario_autorizado(222) is True
        assert es_usuario_autorizado(333) is True

    def test_id_negativo_no_pasa(self, monkeypatch):
        """Un user_id es siempre positivo en Telegram. -1 nunca debería pasar."""
        self._set_whitelist(monkeypatch, "111,222")
        assert es_usuario_autorizado(-1) is False

    def test_whitelist_con_un_solo_id(self, monkeypatch):
        self._set_whitelist(monkeypatch, "987654321")
        assert es_usuario_autorizado(987654321) is True
        assert es_usuario_autorizado(123456789) is False
