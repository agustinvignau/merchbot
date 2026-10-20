"""Registro de interacciones: cada consulta atendida queda guardada.

Cubre el requisito del TP ("registro de interacciones") y alimenta el panel de
métricas de la Fase 3.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from merchbot.core.horario import Momento
from merchbot.core.tools import TIPO_POR_TOOL
from merchbot.data.database import get_session
from merchbot.data.models import Interaccion


logger = logging.getLogger(__name__)

# Prioridad cuando el modelo usó varias funciones: el tipo más "fuerte" gana.
_PRIORIDAD_TIPO = ("reclamo", "reposicion", "pedidos", "stock", "resumen")


def clasificar(herramientas: Iterable[str]) -> str:
    """Tipo de consulta según las funciones usadas ("conversacion" si ninguna)."""
    tipos = {TIPO_POR_TOOL.get(h) for h in herramientas} - {None}
    for tipo in _PRIORIDAD_TIPO:
        if tipo in tipos:
            return tipo
    return "conversacion"


def registrar_interaccion(
    *,
    canal: str,
    user_id: str,
    momento: Momento,
    consulta: str,
    respuesta: Optional[str],
    herramientas: list[str],
    duracion_ms: int,
    estado: str = "ok",
    tipo: Optional[str] = None,
) -> Optional[int]:
    """Guarda la interacción. Si falla, lo loguea y sigue: el registro nunca corta una respuesta."""
    try:
        with get_session() as session:
            fila = Interaccion(
                canal=canal,
                user_id=str(user_id),
                hora_simulada=momento.hora,
                hora_es_simulada=int(momento.simulada),
                fuera_de_horario=int(momento.fuera_de_horario),
                tipo=tipo or clasificar(herramientas),
                consulta=consulta[:4000],
                respuesta=(respuesta or "")[:8000] or None,
                herramientas=",".join(herramientas),
                duracion_ms=duracion_ms,
                estado=estado,
            )
            session.add(fila)
            session.flush()
            return fila.id
    except Exception:
        logger.exception("No pude registrar la interacción")
        return None


def listar_interacciones(
    limite: int = 100,
    canal: Optional[str] = None,
    tipo: Optional[str] = None,
    solo_fuera_de_horario: bool = False,
    solo_errores: bool = False,
) -> list[dict]:
    """Últimas interacciones, de la más nueva a la más vieja."""
    limite = max(1, min(limite, 1000))
    with get_session() as session:
        q = session.query(Interaccion)
        if canal:
            q = q.filter(Interaccion.canal == canal)
        if tipo:
            q = q.filter(Interaccion.tipo == tipo)
        if solo_fuera_de_horario:
            q = q.filter(Interaccion.fuera_de_horario == 1)
        if solo_errores:
            q = q.filter(Interaccion.estado == "error")
        return [i.to_dict() for i in q.order_by(Interaccion.id.desc()).limit(limite).all()]
