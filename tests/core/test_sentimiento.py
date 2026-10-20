"""Tests del análisis de sentimiento y la prioridad de reclamos."""
import csv
from pathlib import Path

import pytest

from merchbot.config import settings
from merchbot.core import sentimiento as sent_module
from merchbot.core.prioridad import calcular_prioridad
from merchbot.core.sentimiento import (
    AnalizadorLexico,
    AnalizadorTransformers,
    Sentimiento,
    obtener_analizador,
    reiniciar_analizador,
)
from merchbot.core.tools import consultar_estado_reclamo, registrar_reclamo

SET = Path(__file__).resolve().parents[2] / "data" / "evaluacion" / "reclamos_etiquetados.csv"
lexico = AnalizadorLexico()


@pytest.fixture(autouse=True)
def _analizador_limpio(monkeypatch):
    monkeypatch.setattr(settings, "sentimiento_motor", "lexico")
    reiniciar_analizador()
    yield
    reiniciar_analizador()


class TestLexico:
    @pytest.mark.parametrize("texto", [
        "Llegaron todas manchadas, un desastre",
        "Estoy muy enojado, nadie me responde",
        "Los buzos no llegaron y sigo esperando",
    ])
    def test_negativos(self, texto):
        assert lexico.analizar(texto).etiqueta == "NEG"

    @pytest.mark.parametrize("texto", ["Excelente trabajo, gracias", "Quedó perfecto, muy contentos"])
    def test_positivos(self, texto):
        assert lexico.analizar(texto).etiqueta == "POS"

    def test_neutro(self):
        assert lexico.analizar("Quiero cambiar el color de las gorras").etiqueta == "NEU"

    def test_negacion(self):
        assert lexico.analizar("No está bien lo que mandaron").etiqueta == "NEG"
        assert lexico.analizar("No hay ningún problema, gracias").etiqueta == "POS"

    def test_intensificadores_bajan_el_puntaje(self):
        assert lexico.analizar("muy mal").puntaje < lexico.analizar("mal").puntaje

    def test_exclamaciones_intensifican(self):
        assert lexico.analizar("Inaceptable!!!").puntaje < lexico.analizar("Inaceptable").puntaje

    def test_atenuantes(self):
        assert lexico.analizar("un poco corrido, nada grave").etiqueta != "NEG"

    def test_explica_las_senales(self):
        assert "manchadas" in lexico.analizar("Vinieron manchadas").senales

    def test_puntaje_en_rango(self):
        s = lexico.analizar("pésimo horrible desastre inaceptable vergüenza enojado " * 3)
        assert s.puntaje == -1.0

    def test_vacio(self):
        assert lexico.analizar("").etiqueta == "NEU"


class TestPrioridad:
    def test_alta_con_urgencia_volumen_y_enojo(self):
        texto = "Faltan 200 buzos y el evento es mañana, un desastre"
        p = calcular_prioridad(texto, "faltante", lexico.analizar(texto))
        assert p.nivel == "alta" and p.requiere_humano
        assert any("urgencia" in m for m in p.motivos)
        assert any("200 unidades" in m for m in p.motivos)

    def test_baja_con_tono_positivo(self):
        texto = "Gracias, solo aviso que faltó una gorra"
        p = calcular_prioridad(texto, "faltante", lexico.analizar(texto))
        assert p.nivel == "baja" and not p.requiere_humano

    def test_reincidencia_suma(self):
        neutro = Sentimiento("NEU", 0.0, "test")
        a = calcular_prioridad("vinieron mal las gorras", "producto_defectuoso", neutro)
        b = calcular_prioridad("otra vez vinieron mal las gorras", "producto_defectuoso", neutro)
        assert b.puntaje == a.puntaje + 10

    def test_tipo_desconocido_cuenta_como_otro(self):
        p = calcular_prioridad("algo", "inventado", Sentimiento("NEU", 0.0, "test"))
        assert p.puntaje == 5

    def test_enojo_fuerte_requiere_humano_aunque_no_sea_alta(self):
        p = calcular_prioridad("x", "otro", Sentimiento("NEG", -0.9, "test"))
        assert p.requiere_humano

    def test_puntaje_acotado(self):
        p = calcular_prioridad("urgente hoy 999 unidades otra vez", "producto_defectuoso",
                               Sentimiento("NEG", -1.0, "test"))
        assert p.puntaje <= 100


class TestSetEtiquetado:
    """Piso de calidad sobre el set de evaluación (los números completos, en scripts/evaluar_sentimiento.py)."""

    def test_el_lexico_supera_el_piso(self):
        filas = list(csv.DictReader(SET.open(encoding="utf-8")))
        aciertos_s = sum(lexico.analizar(f["texto"]).etiqueta == f["sentimiento"] for f in filas)
        aciertos_p = sum(
            calcular_prioridad(f["texto"], f["tipo"], lexico.analizar(f["texto"])).nivel == f["prioridad"]
            for f in filas
        )
        assert len(filas) == 24
        assert aciertos_s / len(filas) >= 0.75
        assert aciertos_p / len(filas) >= 0.7


class TestTransformers:
    def test_adaptador_con_pipeline_falso(self):
        def fabrica(tarea, model, top_k):
            assert tarea == "text-classification" and top_k is None
            return lambda texto: [[{"label": "NEG", "score": 0.8}, {"label": "NEU", "score": 0.15},
                                   {"label": "POS", "score": 0.05}]]
        a = AnalizadorTransformers(modelo="falso", pipeline_factory=fabrica)
        s = a.analizar("llegó roto")
        assert (s.etiqueta, s.motor) == ("NEG", "transformers")
        assert s.puntaje == pytest.approx(-0.75)

    def test_sin_transformers_auto_usa_el_lexico(self, monkeypatch):
        monkeypatch.setattr(settings, "sentimiento_motor", "auto")

        def roto(*a, **k):
            raise ImportError("no transformers")
        monkeypatch.setattr(sent_module, "AnalizadorTransformers", roto)
        reiniciar_analizador()
        assert obtener_analizador().nombre == "lexico"


class TestRegistroConPrioridad:
    def test_el_reclamo_queda_analizado(self):
        r = registrar_reclamo("Me mandaron 100 llaveros con el logo de otro cliente!!! Inaceptable",
                              "error_en_pedido")
        assert r["prioridad"] == "alta" and r["requiere_humano"]
        assert r["sentimiento"] == "NEG" and r["analisis_motor"] == "lexico"
        assert consultar_estado_reclamo(r["numero"])["motivos"]

    def test_si_el_analisis_falla_el_reclamo_se_guarda_igual(self, monkeypatch):
        class Roto:
            nombre = "roto"

            def analizar(self, texto):
                raise RuntimeError("modelo caído")
        monkeypatch.setattr(sent_module, "_analizador", Roto())
        r = registrar_reclamo("Faltan 5 tazas", "faltante")
        assert r["ok"] and r["prioridad"] is None
