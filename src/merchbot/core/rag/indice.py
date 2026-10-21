"""Índice de fragmentos: indexación idempotente y búsqueda.

Búsqueda semántica (embeddings + coseno) cuando hay vectores del modelo
configurado; si no hay API key o la API falla, búsqueda léxica BM25.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from merchbot.config import settings
from merchbot.core.rag.embeddings import Embedder, obtener_embedder
from merchbot.core.rag.fragmentos import fragmentar
from merchbot.core.rag.lexico import BM25, tokenizar
from merchbot.data.database import get_session
from merchbot.data.models import Fragmento

logger = logging.getLogger(__name__)

_SIN_EMBEDDER = object()   # centinela: "resolver el embedder por defecto"


@dataclass
class ResultadoIndexado:
    fuente: str
    fragmentos: int = 0
    nuevos: int = 0
    borrados: int = 0
    embebidos: int = 0
    metodo: str = "lexico"          # "semantico" si todos tienen vector
    error: Optional[str] = None

    def resumen(self) -> str:
        base = (f"Políticas indexadas: {self.fragmentos} fragmentos de {self.fuente} "
                f"({self.nuevos} nuevos, {self.borrados} borrados, {self.embebidos} con embedding nuevo). "
                f"Búsqueda: {'semántica' if self.metodo == 'semantico' else 'léxica (BM25)'}.")
        return base + (f" Aviso: {self.error}" if self.error else "")


@dataclass
class Resultado:
    seccion: str
    texto: str
    score: float
    metodo: str
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"seccion": self.seccion, "texto": self.texto, "score": round(self.score, 3)}


def indexar(path: Optional[Path] = None, embedder=_SIN_EMBEDDER) -> ResultadoIndexado:
    """Sincroniza la tabla `fragmentos` con el documento. Solo embebe lo que cambió."""
    path = Path(path or settings.politicas_path)
    if embedder is _SIN_EMBEDDER:
        embedder = obtener_embedder()
    resultado = ResultadoIndexado(fuente=path.name)
    if not path.exists():
        resultado.error = f"No encontré {path}"
        return resultado

    nuevos_frag = fragmentar(path.read_text(encoding="utf-8"))
    resultado.fragmentos = len(nuevos_frag)
    por_hash = {f.hash: f for f in nuevos_frag}

    with get_session() as session:
        existentes = session.query(Fragmento).filter(Fragmento.fuente == path.name).all()
        hashes_existentes = set()
        for fila in existentes:
            if fila.hash not in por_hash:
                session.delete(fila)
                resultado.borrados += 1
            else:
                hashes_existentes.add(fila.hash)
                fila.orden = por_hash[fila.hash].orden
        for h, f in por_hash.items():
            if h not in hashes_existentes:
                session.add(Fragmento(fuente=path.name, seccion=f.seccion, orden=f.orden,
                                      texto=f.texto, hash=h))
                resultado.nuevos += 1

    if embedder is not None:
        try:
            resultado.embebidos = _embeber_pendientes(path.name, embedder)
        except Exception as e:  # noqa: BLE001 — sin embeddings igual queda la búsqueda léxica
            logger.exception("No pude generar los embeddings")
            resultado.error = f"No pude generar los embeddings ({type(e).__name__}); se usa búsqueda léxica."

    resultado.metodo = "semantico" if _tiene_vectores(path.name, embedder) else "lexico"
    logger.info(resultado.resumen())
    return resultado


def indexar_sin_fallar() -> Optional[ResultadoIndexado]:
    """Para el arranque de la app: si la indexación falla, se loguea y la app sigue."""
    try:
        return indexar()
    except Exception:
        logger.exception("No pude indexar las políticas; las preguntas de procedimientos no tendrán respuesta")
        return None


def _embeber_pendientes(fuente: str, embedder: Embedder) -> int:
    with get_session() as session:
        pendientes = (
            session.query(Fragmento)
            .filter(Fragmento.fuente == fuente)
            .filter((Fragmento.vector.is_(None)) | (Fragmento.modelo != embedder.modelo))
            .order_by(Fragmento.orden)
            .all()
        )
        if not pendientes:
            return 0
        vectores = embedder.documentos([f"{p.seccion}\n{p.texto}" for p in pendientes])
        for fila, v in zip(pendientes, vectores):
            fila.vector = json.dumps(v)
            fila.modelo = embedder.modelo
        return len(pendientes)


def _tiene_vectores(fuente: str, embedder: Optional[Embedder]) -> bool:
    if embedder is None:
        return False
    with get_session() as session:
        q = session.query(Fragmento).filter(Fragmento.fuente == fuente)
        total = q.count()
        con_vector = q.filter(Fragmento.vector.isnot(None), Fragmento.modelo == embedder.modelo).count()
        return total > 0 and total == con_vector


def _cargar(fuente: Optional[str]) -> list[Fragmento]:
    with get_session() as session:
        q = session.query(Fragmento)
        if fuente:
            q = q.filter(Fragmento.fuente == fuente)
        filas = q.order_by(Fragmento.orden).all()
        session.expunge_all()
        return filas


def buscar(
    pregunta: str,
    k: Optional[int] = None,
    embedder=_SIN_EMBEDDER,
    fuente: Optional[str] = None,
    min_score: Optional[float] = None,
) -> list[Resultado]:
    """Los `k` fragmentos más relevantes para la pregunta (puede devolver menos, o ninguno)."""
    k = k or settings.rag_top_k
    pregunta = (pregunta or "").strip()
    if not pregunta:
        return []
    filas = _cargar(fuente or Path(settings.politicas_path).name)
    if not filas:
        return []
    if embedder is _SIN_EMBEDDER:
        embedder = obtener_embedder()

    if embedder is not None and all(f.vector and f.modelo == embedder.modelo for f in filas):
        try:
            return _buscar_semantico(pregunta, filas, embedder, k,
                                     settings.rag_min_score if min_score is None else min_score)
        except Exception:
            logger.exception("Falló la búsqueda semántica; uso la léxica")
    return _buscar_lexico(pregunta, filas, k)


def _buscar_semantico(pregunta, filas, embedder, k, min_score) -> list[Resultado]:
    matriz = np.array([json.loads(f.vector) for f in filas], dtype=np.float32)
    q = np.asarray(embedder.consulta(pregunta), dtype=np.float32)
    similitudes = matriz @ q    # vectores normalizados: producto punto = coseno
    orden = np.argsort(-similitudes)[:k]
    return [
        Resultado(filas[i].seccion, filas[i].texto, float(similitudes[i]), "semantico")
        for i in orden if similitudes[i] >= min_score
    ]


def _buscar_lexico(pregunta, filas, k) -> list[Resultado]:
    if not tokenizar(pregunta):
        return []
    motor = BM25([f"{f.seccion}\n{f.texto}" for f in filas])
    puntajes = motor.puntajes(pregunta)
    orden = sorted(range(len(filas)), key=lambda i: -puntajes[i])[:k]
    mejor = max(puntajes) or 1.0
    # Se descartan los que quedan muy por debajo del mejor (ruido de palabras sueltas).
    return [
        Resultado(filas[i].seccion, filas[i].texto, puntajes[i] / mejor, "lexico")
        for i in orden if puntajes[i] > 0 and puntajes[i] >= 0.35 * mejor
    ]
