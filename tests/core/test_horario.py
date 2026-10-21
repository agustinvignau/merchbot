"""Tests de la hora de la consulta (real o simulada) y el horario de atención."""
from datetime import datetime

import pytest

from merchbot.config import settings
from merchbot.core.horario import esta_fuera_de_horario, resolver_momento, validar_hora

MARTES_15 = datetime(2026, 10, 20, 15, 0)
SABADO_11 = datetime(2026, 10, 24, 11, 0)


class TestValidarHora:
    @pytest.mark.parametrize("entrada,esperado", [
        ("03:20", "03:20"), ("3:20", "03:20"), (" 23:59 ", "23:59"),
        ("", None), (None, None), ("  ", None),
    ])
    def test_validas(self, entrada, esperado):
        assert validar_hora(entrada) == esperado

    @pytest.mark.parametrize("entrada", ["24:00", "12:60", "mediodía", "1230", "3:2"])
    def test_invalidas(self, entrada):
        with pytest.raises(ValueError):
            validar_hora(entrada)


class TestHorarioDeAtencion:
    @pytest.mark.parametrize("hora,fuera", [
        ("08:59", True), ("09:00", False), ("13:30", False), ("17:59", False), ("18:00", True), ("03:20", True),
    ])
    def test_dia_habil(self, hora, fuera):
        assert esta_fuera_de_horario(hora, dia_semana=1) is fuera

    def test_fin_de_semana_siempre_fuera(self):
        assert esta_fuera_de_horario("11:00", dia_semana=5) is True

    def test_configurable(self, monkeypatch):
        monkeypatch.setattr(settings, "atencion_desde", "07:00")
        monkeypatch.setattr(settings, "atencion_dias", "0,1,2,3,4,5")
        assert esta_fuera_de_horario("07:30", dia_semana=5) is False


class TestResolverMomento:
    def test_sin_hora_usa_la_real(self):
        m = resolver_momento(None, ahora=MARTES_15)
        assert (m.hora, m.simulada, m.fuera_de_horario, m.dia) == ("15:00", False, False, "martes")

    def test_hora_simulada_usa_el_dia_real(self):
        m = resolver_momento("03:20", ahora=MARTES_15)
        assert (m.hora, m.simulada, m.fuera_de_horario) == ("03:20", True, True)
        assert m.franja == "madrugada"

    def test_sabado(self):
        assert resolver_momento(None, ahora=SABADO_11).fuera_de_horario is True

    @pytest.mark.parametrize("hora,franja", [("07:00", "mañana"), ("14:00", "tarde"), ("21:00", "noche"), ("02:00", "madrugada")])
    def test_franjas(self, hora, franja):
        assert resolver_momento(hora, ahora=MARTES_15).franja == franja

    def test_contexto_para_el_modelo(self):
        dentro = resolver_momento("10:00", ahora=MARTES_15).contexto_para_el_modelo()
        fuera = resolver_momento("23:00", ahora=MARTES_15).contexto_para_el_modelo()
        assert "martes 10:00" in dentro and "dentro del horario" in dentro
        assert "FUERA del horario" in fuera
        assert "lunes a viernes" in fuera
