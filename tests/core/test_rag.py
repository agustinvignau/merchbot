"""Tests del RAG de políticas: fragmentación, indexación, búsqueda semántica y léxica."""
import json
from pathlib import Path

import numpy as np
import pytest

from merchbot.config import settings
from merchbot.core.rag import buscar, indexar
from merchbot.core.rag.fragmentos import fragmentar
from merchbot.core.rag.lexico import BM25, tokenizar
from merchbot.data.database import get_session
from merchbot.data.models import Fragmento

POLITICAS = Path(__file__).resolve().parents[2] / "data" / "politicas.md"


class EmbedderFalso:
    """Vectores por bolsa de palabras con hashing: determinista y sin red."""

    modelo = "falso-v1"

    def __init__(self, dims=256):
        self.dims = dims
        self.llamadas = 0

    def _vec(self, texto):
        v = np.zeros(self.dims, dtype=np.float32)
        for t in tokenizar(texto):
            v[hash(t) % self.dims] += 1.0
        n = np.linalg.norm(v)
        return (v / n).tolist() if n else v.tolist()

    def documentos(self, textos):
        self.llamadas += 1
        return [self._vec(t) for t in textos]

    def consulta(self, texto):
        return self._vec(texto)


class EmbedderRoto(EmbedderFalso):
    def documentos(self, textos):
        raise RuntimeError("cuota agotada")


@pytest.fixture(autouse=True)
def politicas_de_prueba(monkeypatch):
    monkeypatch.setattr(settings, "politicas_path", POLITICAS)


class TestFragmentar:
    def test_una_seccion_por_titulo(self):
        frags = fragmentar(POLITICAS.read_text(encoding="utf-8"))
        secciones = {f.seccion for f in frags}
        assert {"Plazos de producción y entrega", "Guía de talles", "Cambios y devoluciones"} <= secciones
        assert all(f.texto for f in frags)

    def test_ignora_el_preambulo(self):
        frags = fragmentar("# Título\n\nAclaración\n\n## Uno\n\nTexto uno")
        assert [(f.seccion, f.texto) for f in frags] == [("Uno", "Texto uno")]

    def test_parte_secciones_largas_por_parrafo(self):
        largo = "\n\n".join(f"Párrafo {i} " + "x" * 300 for i in range(5))
        frags = fragmentar(f"## Larga\n\n{largo}", max_caracteres=700)
        assert len(frags) > 1
        assert all(f.seccion == "Larga" for f in frags)
        assert all(len(f.texto) <= 700 for f in frags)

    def test_hash_cambia_con_el_texto(self):
        a, = fragmentar("## A\n\nuno")
        b, = fragmentar("## A\n\ndos")
        assert a.hash != b.hash


class TestIndexar:
    def test_indexa_y_embebe(self):
        e = EmbedderFalso()
        r = indexar(embedder=e)
        assert r.fragmentos == r.nuevos > 5
        assert r.embebidos == r.fragmentos
        assert r.metodo == "semantico"

    def test_es_idempotente_y_no_reembebe(self):
        e = EmbedderFalso()
        indexar(embedder=e)
        r = indexar(embedder=e)
        assert (r.nuevos, r.borrados, r.embebidos) == (0, 0, 0)
        assert e.llamadas == 1

    def test_solo_reprocesa_lo_que_cambio(self, tmp_path, monkeypatch):
        doc = tmp_path / "politicas.md"
        doc.write_text("## A\n\nuno\n\n## B\n\ndos", encoding="utf-8")
        monkeypatch.setattr(settings, "politicas_path", doc)
        indexar(embedder=EmbedderFalso())
        doc.write_text("## A\n\nuno\n\n## B\n\ndos cambiado\n\n## C\n\ntres", encoding="utf-8")
        r = indexar(embedder=EmbedderFalso())
        assert (r.nuevos, r.borrados, r.embebidos) == (2, 1, 2)

    def test_cambio_de_modelo_reembebe(self):
        indexar(embedder=EmbedderFalso())
        otro = EmbedderFalso()
        otro.modelo = "falso-v2"
        assert indexar(embedder=otro).embebidos > 0

    def test_sin_embedder_queda_lexico(self):
        r = indexar(embedder=None)
        assert r.metodo == "lexico" and r.embebidos == 0

    def test_si_la_api_falla_queda_lexico(self):
        r = indexar(embedder=EmbedderRoto())
        assert r.metodo == "lexico"
        assert "léxica" in r.error

    def test_archivo_inexistente(self, tmp_path):
        assert "No encontré" in indexar(tmp_path / "nada.md", embedder=None).error

    def test_vector_guardado_normalizado(self):
        indexar(embedder=EmbedderFalso())
        with get_session() as s:
            v = np.array(json.loads(s.query(Fragmento).first().vector))
        assert abs(np.linalg.norm(v) - 1) < 1e-5


PREGUNTAS = [
    ("¿Cuánto tarda en estar listo un pedido de 300 remeras?", "Plazos de producción y entrega"),
    ("¿Cuál es la cantidad mínima para pedir tazas?", "Pedido mínimo"),
    ("¿Puedo cambiar una remera que vino manchada?", "Cambios y devoluciones"),
    ("¿Qué medidas tiene el talle XL?", "Guía de talles"),
    ("¿En qué formato mando el logo?", "Archivos de diseño"),
    ("¿Hacen envíos al interior?", "Envíos y retiro"),
    ("¿Cómo lavo una remera sublimada?", "Cuidado de las prendas sublimadas"),
]


class TestBuscar:
    @pytest.mark.parametrize("pregunta,seccion", PREGUNTAS)
    def test_lexico_encuentra_la_seccion(self, pregunta, seccion):
        indexar(embedder=None)
        resultados = buscar(pregunta, embedder=None)
        assert resultados and resultados[0].seccion == seccion
        assert resultados[0].metodo == "lexico"

    def test_semantico_usa_los_vectores(self):
        """Mecánica de la búsqueda semántica (la calidad real se mide con scripts/evaluar_rag.py)."""
        e = EmbedderFalso()
        indexar(embedder=e)
        resultados = buscar("guía de talles ancho de pecho largo", embedder=e, min_score=0.05)
        assert resultados[0].metodo == "semantico"
        assert resultados[0].seccion == "Guía de talles"
        assert resultados[0].score >= resultados[-1].score

    def test_umbral_semantico_descarta_lo_irrelevante(self):
        e = EmbedderFalso()
        indexar(embedder=e)
        assert buscar("xyzzy plugh", embedder=e, min_score=0.5) == []

    def test_pregunta_sin_relacion_en_lexico(self):
        indexar(embedder=None)
        assert buscar("qué opinás de la fotosíntesis", embedder=None) == []

    def test_sin_indice_devuelve_vacio(self):
        assert buscar("plazos", embedder=None) == []

    def test_si_faltan_vectores_usa_lexico_aunque_haya_embedder(self):
        indexar(embedder=None)
        r = buscar("plazos de entrega", embedder=EmbedderFalso())
        assert r[0].metodo == "lexico"

    def test_respeta_k(self):
        indexar(embedder=None)
        assert len(buscar("pedido", k=1, embedder=None)) == 1


class TestBM25:
    def test_tokenizar_saca_stopwords_tildes_y_plurales(self):
        assert tokenizar("¿Cuántas remeras hay para los envíos?") == ["remer", "envi"]

    def test_expansion_de_sinonimos(self):
        assert "plaz" in tokenizar("¿cuánto tarda?", expandir=True)
        assert "plaz" not in tokenizar("¿cuánto tarda?")

    def test_puntaje_mayor_para_el_documento_relevante(self):
        m = BM25(["plazos de entrega", "guía de talles"])
        a, b = m.puntajes("entrega")
        assert a > b == 0


class TestToolYAsistente:
    def test_tool_devuelve_fragmentos(self):
        from merchbot.core.tools import ejecutar_tool

        indexar(embedder=None)
        r = ejecutar_tool("consultar_politicas", {"pregunta": "¿qué formato tiene que tener el logo?"})
        assert r["encontrado"] and r["fragmentos"][0]["seccion"] == "Archivos de diseño"

    def test_tool_sin_resultados_pide_no_inventar(self):
        from merchbot.core.tools import consultar_politicas

        indexar(embedder=None)
        r = consultar_politicas("¿quién ganó el mundial?")
        assert r["encontrado"] is False and "No inventes" in r["mensaje"]

    def test_el_asistente_devuelve_las_fuentes(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        from merchbot.core.assistant import MerchBot
        from merchbot.core.rag import embeddings

        monkeypatch.setattr(embeddings.settings, "gemini_api_key", "")   # búsqueda léxica
        indexar(embedder=None)
        fc = MagicMock()
        fc.name, fc.args = "consultar_politicas", {"pregunta": "plazos de entrega"}
        pide = MagicMock(function_calls=[fc], text="", candidates=[MagicMock()])
        responde = MagicMock(function_calls=[], text="Según Plazos...", candidates=[MagicMock()])
        with patch("merchbot.core.assistant.genai.Client") as Cliente:
            Cliente.return_value.models.generate_content.side_effect = [pide, responde]
            r = MerchBot(api_key="x").responder(1, "¿cuánto tarda un pedido?")
        assert r.fuentes[0] == "Plazos de producción y entrega"
        assert r.herramientas == ["consultar_politicas"]

    def test_clasifica_como_politicas(self):
        from merchbot.core.registro import clasificar

        assert clasificar(["consultar_politicas"]) == "politicas"
        assert clasificar(["buscar_stock", "consultar_politicas"]) == "stock"

    def test_indexar_sin_fallar(self, monkeypatch):
        from merchbot.core.rag import indice

        monkeypatch.setattr(indice, "indexar", lambda: (_ for _ in ()).throw(RuntimeError("x")))
        assert indice.indexar_sin_fallar() is None
