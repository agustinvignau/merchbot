"""Mide qué tan bien el RAG encuentra la sección correcta de las políticas.

Compara la búsqueda léxica (BM25) con la semántica (embeddings de Gemini) sobre
un set de preguntas escritas como las haría un usuario, sin copiar las palabras
del documento. Métricas:

- acierto@1: la sección correcta salió primera.
- acierto@3: la sección correcta está entre las 3 primeras.
- MRR: promedio de 1/posición de la sección correcta (0 si no aparece).
- rechazo: en preguntas fuera de tema, que no devuelva nada (evita inventar).

Uso:
    python scripts/evaluar_rag.py                 # léxica; y semántica si hay GEMINI_API_KEY
    python scripts/evaluar_rag.py --salida docs/EVALUACION_RAG.md
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# (pregunta, sección esperada). None = fuera de tema: lo correcto es no devolver nada.
PREGUNTAS: list[tuple[str, str | None]] = [
    ("¿Cuántos días tarda un pedido de 80 remeras?", "Plazos de producción y entrega"),
    ("Si encargo 600 buzos, ¿para cuándo los tengo?", "Plazos de producción y entrega"),
    ("¿Hacen trabajos urgentes para pasado mañana?", "Plazos de producción y entrega"),
    ("¿Puedo pedir solo 5 remeras con mi logo?", "Pedido mínimo"),
    ("¿Cuál es la cantidad mínima de tazas?", "Pedido mínimo"),
    ("¿Puedo mezclar talles en un mismo pedido?", "Pedido mínimo"),
    ("Me llegaron prendas con la impresión corrida, ¿me las cambian?", "Cambios y devoluciones"),
    ("¿Cuántos días tengo para avisar de una falla?", "Cambios y devoluciones"),
    ("Una remera lisa me quedó chica, ¿la puedo cambiar?", "Cambios y devoluciones"),
    ("¿Qué ancho de pecho tiene una remera L?", "Guía de talles"),
    ("Las dry-fit, ¿vienen chicas?", "Guía de talles"),
    ("¿Sirve si les mando el logo en JPG que bajé de Instagram?", "Archivos de diseño"),
    ("¿Respetan los colores Pantone?", "Archivos de diseño"),
    ("¿Me lo pueden mandar a Córdoba?", "Envíos y retiro"),
    ("¿Puedo pasar a buscar el pedido por el depósito?", "Envíos y retiro"),
    ("¿Se puede meter en el secarropas una remera sublimada?", "Cuidado de las prendas sublimadas"),
    ("¿El estampado se despega con los lavados?", "Cuidado de las prendas sublimadas"),
    ("¿Atienden los sábados?", "Horarios de atención"),
    ("¿Qué pasos tengo que seguir para encargar remeras con mi marca?", "Cómo hacer un pedido"),
    ("¿Cuándo queda confirmado mi pedido?", "Cómo hacer un pedido"),
    ("¿En cuánto tiempo me responden un reclamo?", "Reclamos"),
    ("¿Puedo ver cómo queda una prenda antes de encargar 300?", "Muestras"),
    ("¿Quién ganó el último mundial?", None),
    ("Pasame una receta de empanadas", None),
    ("¿Cuál es la capital de Francia?", None),
]


def evaluar(buscar_fn) -> dict:
    filas, a1, a3, rr, rechazos_ok, n_pos, n_neg = [], 0, 0, 0.0, 0, 0, 0
    for pregunta, esperada in PREGUNTAS:
        secciones = [r.seccion for r in buscar_fn(pregunta)]
        if esperada is None:
            n_neg += 1
            ok = not secciones
            rechazos_ok += ok
            filas.append((pregunta, "(ninguna)", secciones[:1], "✅" if ok else "❌"))
            continue
        n_pos += 1
        pos = secciones.index(esperada) + 1 if esperada in secciones else 0
        a1 += pos == 1
        a3 += 1 <= pos <= 3
        rr += 1 / pos if pos else 0
        filas.append((pregunta, esperada, secciones[:1], "✅" if pos == 1 else ("🟡" if pos else "❌")))
    return {
        "acierto@1": a1 / n_pos, "acierto@3": a3 / n_pos, "mrr": rr / n_pos,
        "rechazo": rechazos_ok / n_neg if n_neg else 1.0, "filas": filas,
    }


def a_markdown(resultados: dict[str, dict], modelo: str | None) -> str:
    lineas = [
        "# Evaluación del RAG de políticas", "",
        "Generado con `python scripts/evaluar_rag.py`. Preguntas escritas como las haría un usuario, "
        f"sin copiar las palabras del documento ({sum(1 for _, e in PREGUNTAS if e)} con respuesta en las políticas "
        f"y {sum(1 for _, e in PREGUNTAS if e is None)} fuera de tema).", "",
        "| Método | Acierto@1 | Acierto@3 | MRR | Rechaza lo fuera de tema |",
        "|---|---|---|---|---|",
    ]
    nombres = {"lexico": "Léxica (BM25 + sinónimos)", "semantico": f"Semántica ({modelo})"}
    for metodo, r in resultados.items():
        lineas.append(f"| {nombres[metodo]} | {r['acierto@1']:.0%} | {r['acierto@3']:.0%} | "
                      f"{r['mrr']:.2f} | {r['rechazo']:.0%} |")
    for metodo, r in resultados.items():
        lineas += ["", f"## {nombres[metodo]}", "", "| Pregunta | Esperada | Primera devuelta | |", "|---|---|---|---|"]
        for pregunta, esperada, primera, marca in r["filas"]:
            lineas.append(f"| {pregunta} | {esperada} | {primera[0] if primera else '(ninguna)'} | {marca} |")
    lineas += ["", "✅ primera posición · 🟡 entre las 3 primeras · ❌ no aparece o respondió algo fuera de tema."]
    return "\n".join(lineas) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--salida", help="archivo Markdown donde guardar el reporte")
    args = parser.parse_args(argv)

    tmp = tempfile.mkdtemp(prefix="merchbot-rag-")
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp) / 'rag.db'}"
    sys.path.insert(0, str(RAIZ / "src"))

    from merchbot.config import settings
    from merchbot.core.rag import buscar, indexar
    from merchbot.core.rag.embeddings import obtener_embedder
    from merchbot.data.database import init_db

    init_db()
    resultados: dict[str, dict] = {}

    indexar(embedder=None)
    resultados["lexico"] = evaluar(lambda q: buscar(q, embedder=None))

    embedder = obtener_embedder()
    if embedder is None:
        print("Sin GEMINI_API_KEY: solo se evalúa la búsqueda léxica.\n")
    else:
        r = indexar(embedder=embedder)
        if r.metodo == "semantico":
            resultados["semantico"] = evaluar(lambda q: buscar(q, embedder=embedder))
        else:
            print(f"No pude generar embeddings: {r.error}\n")

    for metodo, r in resultados.items():
        print(f"{metodo:10} acierto@1={r['acierto@1']:.0%}  acierto@3={r['acierto@3']:.0%}  "
              f"MRR={r['mrr']:.2f}  rechazo={r['rechazo']:.0%}")
    if args.salida:
        Path(args.salida).write_text(a_markdown(resultados, settings.embedding_model), encoding="utf-8")
        print(f"\nReporte: {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
