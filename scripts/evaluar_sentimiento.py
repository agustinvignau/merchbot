"""Compara motores de sentimiento sobre el set etiquetado de reclamos.

Motores:
- lexico: diccionario propio en español (el que usa MerchBot sin dependencias).
- vader: VADER, el analizador de NLTK (vía `vaderSentiment` o `nltk`). Su léxico es en inglés.
- transformers: pysentimiento/robertuito-sentiment-analysis (requiere `pip install -e ".[nlp]"`).

Métricas: exactitud y F1 macro del sentimiento (NEG/NEU/POS), matriz de confusión, y
exactitud de la prioridad (alta/media/baja) calculada con cada motor.

Uso:
    python scripts/evaluar_sentimiento.py
    python scripts/evaluar_sentimiento.py --salida docs/EVALUACION_SENTIMIENTO.md
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SET = RAIZ / "data" / "evaluacion" / "reclamos_etiquetados.csv"
sys.path.insert(0, str(RAIZ / "src"))

from merchbot.core.prioridad import calcular_prioridad  # noqa: E402
from merchbot.core.sentimiento import (  # noqa: E402
    ETIQUETAS,
    AnalizadorLexico,
    AnalizadorTransformers,
    Sentimiento,
)


class AnalizadorVader:
    """VADER tal cual: umbrales estándar de ±0,05 sobre el puntaje compuesto."""

    nombre = "vader"

    def __init__(self) -> None:
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        except ImportError:
            from nltk.sentiment import SentimentIntensityAnalyzer
        self._sia = SentimentIntensityAnalyzer()

    def analizar(self, texto: str) -> Sentimiento:
        c = self._sia.polarity_scores(texto)["compound"]
        etiqueta = "NEG" if c <= -0.05 else "POS" if c >= 0.05 else "NEU"
        return Sentimiento(etiqueta, c, self.nombre)


def cargar() -> list[dict]:
    with SET.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def f1_macro(reales: list[str], predichas: list[str]) -> float:
    f1s = []
    for etiqueta in ETIQUETAS:
        tp = sum(r == p == etiqueta for r, p in zip(reales, predichas))
        fp = sum(p == etiqueta != r for r, p in zip(reales, predichas))
        fn = sum(r == etiqueta != p for r, p in zip(reales, predichas))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(f1s) / len(f1s)


def evaluar(analizador, filas: list[dict]) -> dict:
    reales, predichas, prio_ok, detalle = [], [], 0, []
    for f in filas:
        s = analizador.analizar(f["texto"])
        p = calcular_prioridad(f["texto"], f["tipo"], s)
        reales.append(f["sentimiento"])
        predichas.append(s.etiqueta)
        prio_ok += p.nivel == f["prioridad"]
        detalle.append((f["texto"], f["sentimiento"], s.etiqueta, f["prioridad"], p.nivel))
    confusion = {r: {p: 0 for p in ETIQUETAS} for r in ETIQUETAS}
    for r, p in zip(reales, predichas):
        confusion[r][p] += 1
    n = len(filas)
    return {
        "exactitud": sum(r == p for r, p in zip(reales, predichas)) / n,
        "f1_macro": f1_macro(reales, predichas),
        "prioridad": prio_ok / n,
        "confusion": confusion,
        "detalle": detalle,
    }


def motores_disponibles() -> list:
    motores = [AnalizadorLexico()]
    try:
        motores.append(AnalizadorVader())
    except ImportError:
        print("VADER no disponible (pip install vaderSentiment): se omite.")
    try:
        motores.append(AnalizadorTransformers())
    except Exception as e:  # noqa: BLE001
        print(f"transformers no disponible ({type(e).__name__}): se omite. "
              'Instalalo con pip install -e ".[nlp]".')
    return motores


def a_markdown(resultados: dict[str, dict], n: int) -> str:
    nombres = {"lexico": "Léxico propio (español)", "vader": "VADER (NLTK, léxico en inglés)",
               "transformers": "RoBERTuito (transformers)"}
    lineas = [
        "# Evaluación del sentimiento de reclamos", "",
        f"Generado con `python scripts/evaluar_sentimiento.py` sobre `data/evaluacion/reclamos_etiquetados.csv` "
        f"({n} reclamos etiquetados a mano con sentimiento y prioridad esperados).", "",
        "| Motor | Exactitud sentimiento | F1 macro | Exactitud prioridad |",
        "|---|---|---|---|",
    ]
    for motor, r in resultados.items():
        lineas.append(f"| {nombres.get(motor, motor)} | {r['exactitud']:.0%} | {r['f1_macro']:.2f} | {r['prioridad']:.0%} |")
    for motor, r in resultados.items():
        lineas += ["", f"## {nombres.get(motor, motor)}", "", "Matriz de confusión (filas: real; columnas: predicho)", "",
                   "| | NEG | NEU | POS |", "|---|---|---|---|"]
        for real in ETIQUETAS:
            c = r["confusion"][real]
            lineas.append(f"| **{real}** | {c['NEG']} | {c['NEU']} | {c['POS']} |")
        errores = [d for d in r["detalle"] if d[1] != d[2] or d[3] != d[4]]
        if errores:
            lineas += ["", "Diferencias con lo esperado:", "", "| Reclamo | Sentimiento (esperado → obtenido) | Prioridad (esperada → obtenida) |", "|---|---|---|"]
            for texto, s_real, s_pred, p_real, p_pred in errores:
                lineas.append(f"| {texto} | {s_real} → {s_pred} | {p_real} → {p_pred} |")
    return "\n".join(lineas) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--salida", help="archivo Markdown donde guardar el reporte")
    args = parser.parse_args(argv)

    filas = cargar()
    resultados = {m.nombre: evaluar(m, filas) for m in motores_disponibles()}
    print()
    for motor, r in resultados.items():
        print(f"{motor:13} exactitud={r['exactitud']:.0%}  F1 macro={r['f1_macro']:.2f}  prioridad={r['prioridad']:.0%}")
    if args.salida:
        Path(args.salida).write_text(a_markdown(resultados, len(filas)), encoding="utf-8")
        print(f"\nReporte: {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
