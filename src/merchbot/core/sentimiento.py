"""Análisis de sentimiento de los reclamos.

Dos motores con la misma interfaz:

- `AnalizadorTransformers`: modelo `pysentimiento/robertuito-sentiment-analysis`
  (RoBERTa entrenado con tuits en español). Necesita `pip install -e ".[nlp]"`
  y descarga el modelo la primera vez.
- `AnalizadorLexico`: diccionario propio en español rioplatense, con negación e
  intensificadores. No tiene dependencias y es explicable: dice qué palabras pesaron.

`obtener_analizador()` usa transformers si está instalado y el modelo carga; si no,
el léxico. VADER (NLTK) se evalúa en `scripts/evaluar_sentimiento.py` pero no se
usa: su diccionario es en inglés.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional, Protocol

from merchbot.config import settings

logger = logging.getLogger(__name__)

ETIQUETAS = ("NEG", "NEU", "POS")


@dataclass
class Sentimiento:
    etiqueta: str            # "NEG" | "NEU" | "POS"
    puntaje: float           # -1 (muy negativo) a 1 (muy positivo)
    motor: str
    senales: list[str] = field(default_factory=list)   # qué lo explicó (léxico)


class Analizador(Protocol):
    nombre: str

    def analizar(self, texto: str) -> Sentimiento: ...


# ---------------------------------------------------------------------------
# Léxico propio
# ---------------------------------------------------------------------------

def _plano(texto: str) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return sin_tildes.lower()


# Raíces (sin tildes) → peso. Se buscan como prefijo de palabra: "mancha" cubre manchas, manchadas.
NEGATIVAS = {
    "mancha": 1.0, "rot": 0.8, "descosid": 1.0, "fallad": 1.0, "falla": 0.8, "defectuos": 1.0,
    "corrid": 0.6, "despeg": 1.0, "pixelad": 1.0, "apagad": 0.5, "floj": 0.4, "suelt": 0.3,
    "mal": 0.7, "pesim": 1.5, "horribl": 1.5, "desastr": 1.5, "inaceptabl": 1.5, "verguenz": 1.5,
    "enojad": 1.5, "molest": 1.0, "decepcion": 1.2, "indignad": 1.5, "harto": 1.5, "cansad": 0.8,
    "demor": 0.6, "tarde": 0.4, "atras": 0.6, "esperando": 0.7, "nadie": 0.8, "ignor": 1.0,
    "equivocad": 0.9, "incorrect": 0.8, "error": 0.6, "erron": 0.8, "perdid": 0.8,
    "falt": 0.6, "incomplet": 0.6, "parad": 0.5, "cobraron": 0.6, "problema": 0.6,
}
FRASES_NEGATIVAS = {
    "no llego": 1.0, "no llegaron": 1.0, "todavia no": 0.8, "sigue sin": 1.0, "sigo esperando": 1.0,
    "no responde": 1.0, "no me responden": 1.2, "no sirve": 1.2, "no funciona": 1.0,
    "otra vez": 0.8, "de nuevo": 0.6, "segunda vez": 0.8, "no puedo entregar": 1.0,
    "no las puedo": 0.8, "no los puedo": 0.8, "en vez de": 0.5,
}
POSITIVAS = {
    "gracias": 1.0, "excelente": 1.5, "perfect": 1.2, "genial": 1.2, "buenisim": 1.2, "bien": 0.6,
    "conform": 0.8, "content": 1.0, "rapid": 0.6, "impecabl": 1.2, "como siempre": 0.5,
}
# Lo que atenúa el problema: "nada grave", "un poco".
ATENUANTES = {"nada grave": 0.8, "un poco": 0.3, "chiquit": 0.4, "solo aviso": 0.5, "solamente": 0.3,
              "solo una": 0.3, "una de las": 0.4, "quería avisar": 0.4, "queria avisar": 0.4}
INTENSIFICADORES = ("muy", "re", "super", "totalmente", "realmente", "todas", "todos")
PUENTES = ("esta", "estan", "es", "son", "fue", "fueron", "hay", "salio", "quedo", "quedaron", "me", "nos")
NEGADORES = ("no", "nunca", "ni", "tampoco", "ningun", "ninguna", "ninguno", "sin")


class AnalizadorLexico:
    nombre = "lexico"

    def analizar(self, texto: str) -> Sentimiento:
        plano = _plano(texto or "")
        # Cada cláusula (separada por puntuación) se analiza aparte: la negación no cruza comas.
        clausulas = [re.findall(r"[a-z0-9]+", c) for c in re.split(r"[.,;:!?\n]+", plano)]
        neg = pos = 0.0
        senales: list[str] = []

        for frase, peso in FRASES_NEGATIVAS.items():
            if re.search(rf"\b{frase}\b", plano):
                neg += peso
                senales.append(frase)
        for frase, peso in ATENUANTES.items():
            if _plano(frase) in plano:
                neg -= peso
                senales.append(f"atenúa: {frase}")
        for frase in ("como siempre",):
            if frase in plano:
                pos += POSITIVAS[frase]

        for palabras, i, palabra in ((ps, i, w) for ps in clausulas for i, w in enumerate(ps)):
            previa = palabras[i - 1] if i else ""
            factor = 1.5 if previa in INTENSIFICADORES else 1.0
            # "no bien", "no está bien", "ningún problema": negador inmediato o con un verbo puente.
            negada = previa in NEGADORES or (i > 1 and palabras[i - 2] in NEGADORES and previa in PUENTES)
            for raiz, peso in NEGATIVAS.items():
                if palabra.startswith(raiz) and len(palabra) <= len(raiz) + 5:
                    if negada and raiz in ("mal", "problema"):
                        pos += 0.3            # "no está mal", "ningún problema"
                    else:
                        neg += peso * factor
                        senales.append(palabra)
                    break
            for raiz, peso in POSITIVAS.items():
                if " " in raiz:
                    continue
                if palabra.startswith(raiz) and len(palabra) <= len(raiz) + 4:
                    if negada:
                        neg += peso           # "no está bien"
                        senales.append(f"no {palabra}")
                    else:
                        pos += peso * factor
                        senales.append(f"+{palabra}")
                    break

        # Signos de exclamación repetidos y mayúsculas sostenidas intensifican el enojo.
        if re.search(r"!{2,}", texto or "") and neg > 0:
            neg *= 1.3
            senales.append("!!!")
        if sum(1 for w in re.findall(r"[A-ZÁÉÍÓÚÑ]{4,}", texto or "")) >= 2 and neg > 0:
            neg *= 1.2
            senales.append("MAYÚSCULAS")

        neg = max(neg, 0.0)
        bruto = pos - neg
        puntaje = round(max(-1.0, min(1.0, bruto / 3.0)), 3)
        if puntaje <= -0.2:
            etiqueta = "NEG"
        elif puntaje >= 0.15:
            etiqueta = "POS"
        else:
            etiqueta = "NEU"
        return Sentimiento(etiqueta, puntaje, self.nombre, senales)


# ---------------------------------------------------------------------------
# Transformers (opcional)
# ---------------------------------------------------------------------------

class AnalizadorTransformers:
    nombre = "transformers"

    def __init__(self, modelo: Optional[str] = None, pipeline_factory=None) -> None:
        self.modelo = modelo or settings.sentimiento_modelo
        if pipeline_factory is None:
            from transformers import pipeline as pipeline_factory   # import diferido: es pesado
        self._pipe = pipeline_factory("text-classification", model=self.modelo, top_k=None)

    def analizar(self, texto: str) -> Sentimiento:
        salida = self._pipe((texto or "")[:512])
        if salida and isinstance(salida[0], list):   # algunas versiones anidan una lista más
            salida = salida[0]
        probs = {_normalizar_etiqueta(d["label"]): float(d["score"]) for d in salida}
        etiqueta = max(probs, key=probs.get)
        puntaje = probs.get("POS", 0.0) - probs.get("NEG", 0.0)
        return Sentimiento(etiqueta, round(puntaje, 3), self.nombre,
                           [f"{k}={v:.2f}" for k, v in sorted(probs.items())])


def _normalizar_etiqueta(label: str) -> str:
    l = label.upper()
    if l.startswith("NEG") or l in ("LABEL_0", "1 STAR", "2 STARS"):
        return "NEG"
    if l.startswith("POS") or l in ("LABEL_2", "4 STARS", "5 STARS"):
        return "POS"
    return "NEU"


_analizador: Optional[Analizador] = None


def obtener_analizador() -> Analizador:
    """Según SENTIMIENTO_MOTOR: 'transformers', 'lexico' o 'auto' (transformers si se puede)."""
    global _analizador
    if _analizador is not None:
        return _analizador
    motor = settings.sentimiento_motor.lower()
    if motor in ("auto", "transformers"):
        try:
            _analizador = AnalizadorTransformers()
            logger.info("Sentimiento con transformers (%s)", settings.sentimiento_modelo)
            return _analizador
        except Exception as e:  # noqa: BLE001
            nivel = logging.WARNING if motor == "transformers" else logging.INFO
            logger.log(nivel, "Sentimiento: transformers no disponible (%s); uso el léxico", type(e).__name__)
    _analizador = AnalizadorLexico()
    return _analizador


def reiniciar_analizador() -> None:
    """Para tests o después de cambiar la configuración."""
    global _analizador
    _analizador = None
