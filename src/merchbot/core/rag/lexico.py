"""Búsqueda léxica BM25: el respaldo cuando no hay embeddings.

Sirve sin API key ni internet, y como línea de base para comparar contra los
embeddings en `scripts/evaluar_rag.py`.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

STOPWORDS = set("""
a al algo algun alguna algunas alguno algunos ante antes como con contra cual cuales cuando de del
desde donde dos el ella ellas ellos en entre era es esa esas ese eso esos esta estan estas este esto
estos fue ha hay la las le les lo los mas me mi mis mucho muy nada ni no nos o otra otro para pero
poco por porque que quien se si sin sobre son su sus tambien tan te tiene tengo ti todo todos tu tus
un una uno unos unas usted vos y ya yo cuanto cuanta cuantos cuantas puedo puede hago hacer tener
""".split())


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _raiz(palabra: str) -> str:
    """Reducción mínima: plurales, género y algunos sufijos frecuentes."""
    for sufijo in ("aciones", "acion", "mente", "es", "s"):
        if palabra.endswith(sufijo) and len(palabra) - len(sufijo) >= 4:
            palabra = palabra[: -len(sufijo)]
            break
    if len(palabra) >= 5 and palabra[-1] in "aoe":
        palabra = palabra[:-1]
    return palabra


# Expansión de consultas: palabras con que la gente pregunta → palabras del documento.
# La búsqueda léxica no entiende sinónimos; esto la ayuda en los casos frecuentes.
# Los embeddings no lo necesitan (ver docs/RAG.md).
SINONIMOS = {
    "tarda": "plazo", "demora": "plazo", "tiempo": "plazo", "listo": "plazo", "cuando": "plazo",
    "cambiar": "cambio", "devolver": "devolucion", "falla": "falla", "manchada": "falla",
    "lavar": "lavado cuidado", "lavo": "lavado cuidado", "planchar": "cuidado",
    "medida": "talle", "medidas": "talle", "tamano": "talle",
    "logo": "archivo diseno", "imagen": "archivo diseno",
    "cantidad": "minimo", "minima": "minimo",
    "mandan": "envio", "envian": "envio", "interior": "envio", "retirar": "retiro",
    "abierto": "horario", "abren": "horario", "cierran": "horario",
}


def tokenizar(texto: str, expandir: bool = False) -> list[str]:
    palabras = re.findall(r"[a-z0-9]+", _sin_tildes(texto.lower()))
    if expandir:
        palabras = [x for p in palabras for x in ([p] + SINONIMOS.get(p, "").split())]
    return [_raiz(p) for p in palabras if p not in STOPWORDS and len(p) > 1]


class BM25:
    def __init__(self, documentos: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.docs = [tokenizar(d) for d in documentos]
        self.k1, self.b = k1, b
        self.n = len(self.docs)
        self.largo_medio = (sum(len(d) for d in self.docs) / self.n) if self.n else 0.0
        self.frecuencias = [Counter(d) for d in self.docs]
        df = Counter(t for d in self.docs for t in set(d))
        self.idf = {t: math.log(1 + (self.n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def puntajes(self, consulta: str) -> list[float]:
        terminos = tokenizar(consulta, expandir=True)
        resultado = []
        for frec, doc in zip(self.frecuencias, self.docs):
            s = 0.0
            for t in terminos:
                if t not in frec:
                    continue
                tf = frec[t]
                norm = tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * len(doc) / (self.largo_medio or 1)))
                s += self.idf.get(t, 0.0) * norm
            resultado.append(s)
        return resultado
