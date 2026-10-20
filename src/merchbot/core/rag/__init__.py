"""RAG de políticas: el asistente responde preguntas de procedimientos con
fragmentos recuperados de `data/politicas.md`.

- `fragmentos.py`: divide el documento en secciones.
- `embeddings.py`: vectores con Gemini (o ninguno, si no hay API key).
- `lexico.py`: búsqueda BM25 de respaldo, sin dependencias externas.
- `indice.py`: guarda los fragmentos en la base, indexa y busca.
"""
from merchbot.core.rag.indice import Resultado, buscar, indexar, indexar_sin_fallar

__all__ = ["Resultado", "buscar", "indexar", "indexar_sin_fallar"]
