"""Embeddings con Gemini.

Se usan tipos de tarea distintos para documentos y consultas (RETRIEVAL_DOCUMENT
y RETRIEVAL_QUERY), como recomienda la API, y se normalizan los vectores para
que la similitud de coseno sea un producto punto.
"""
from __future__ import annotations

import logging
from typing import Optional, Protocol

import numpy as np

from merchbot.config import settings

logger = logging.getLogger(__name__)

LOTE = 50  # textos por llamada a la API


class Embedder(Protocol):
    modelo: str

    def documentos(self, textos: list[str]) -> list[list[float]]: ...

    def consulta(self, texto: str) -> list[float]: ...


def normalizar(vector) -> list[float]:
    v = np.asarray(vector, dtype=np.float32)
    norma = float(np.linalg.norm(v))
    return (v / norma).tolist() if norma else v.tolist()


class GeminiEmbedder:
    def __init__(self, api_key: Optional[str] = None, modelo: Optional[str] = None,
                 dimensiones: Optional[int] = None) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        self.modelo = modelo or settings.embedding_model
        self.dimensiones = dimensiones or settings.embedding_dimensiones
        self._client = genai.Client(api_key=api_key or settings.gemini_api_key)

    def _embed(self, textos: list[str], tarea: str) -> list[list[float]]:
        vectores: list[list[float]] = []
        for i in range(0, len(textos), LOTE):
            r = self._client.models.embed_content(
                model=self.modelo,
                contents=textos[i:i + LOTE],
                config=self._types.EmbedContentConfig(
                    task_type=tarea, output_dimensionality=self.dimensiones,
                ),
            )
            vectores.extend(normalizar(e.values) for e in r.embeddings)
        return vectores

    def documentos(self, textos: list[str]) -> list[list[float]]:
        return self._embed(textos, "RETRIEVAL_DOCUMENT")

    def consulta(self, texto: str) -> list[float]:
        return self._embed([texto], "RETRIEVAL_QUERY")[0]


def obtener_embedder() -> Optional[Embedder]:
    """Embedder de Gemini si hay API key; si no, None (se usa la búsqueda léxica)."""
    if not settings.gemini_api_key:
        return None
    try:
        return GeminiEmbedder()
    except Exception:
        logger.exception("No pude crear el cliente de embeddings; uso búsqueda léxica")
        return None
