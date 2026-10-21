"""Métricas del panel admin, calculadas sobre `interacciones` y `reclamos`.

Todo sale de consultas a la base: el panel no guarda números propios, así que
lo que muestra siempre coincide con el registro.
"""
from __future__ import annotations

import math
from datetime import timedelta
from typing import Optional

from sqlalchemy import func

from merchbot.data.database import get_session
from merchbot.data.models import ESTADOS_RECLAMO, Interaccion, Reclamo
from merchbot.timeutils import utc_now


def _percentil(valores: list[int], p: float) -> Optional[int]:
    """Percentil por el método del rango más cercano (sin interpolar)."""
    if not valores:
        return None
    ordenados = sorted(valores)
    k = max(0, math.ceil(p / 100 * len(ordenados)) - 1)
    return ordenados[k]


def _filtrar(q, dias: Optional[int], canal: Optional[str]):
    if dias:
        q = q.filter(Interaccion.created_at >= utc_now() - timedelta(days=dias))
    if canal:
        q = q.filter(Interaccion.canal == canal)
    return q


def calcular_metricas(dias: Optional[int] = 7, canal: Optional[str] = None) -> dict:
    """Métricas de los últimos `dias` días (None = todo el historial)."""
    with get_session() as session:
        base = _filtrar(session.query(Interaccion), dias, canal)
        total = base.count()

        def contar_por(columna) -> dict[str, int]:
            filas = (
                _filtrar(session.query(columna, func.count()), dias, canal)
                .group_by(columna).all()
            )
            return {str(k): int(n) for k, n in filas}

        por_tipo = contar_por(Interaccion.tipo)
        por_canal = contar_por(Interaccion.canal)
        por_estado = contar_por(Interaccion.estado)

        filas = base.with_entities(
            Interaccion.hora_simulada, Interaccion.fuera_de_horario,
            Interaccion.duracion_ms, Interaccion.herramientas, Interaccion.user_id,
        ).all()

        reclamos_por_estado = {e: 0 for e in ESTADOS_RECLAMO}
        for estado, n in session.query(Reclamo.estado, func.count()).group_by(Reclamo.estado):
            reclamos_por_estado[estado] = int(n)
        reclamos_por_tipo = {
            t: int(n) for t, n in session.query(Reclamo.tipo, func.count()).group_by(Reclamo.tipo)
        }

    por_hora = [0] * 24
    fuera = 0
    duraciones: list[int] = []
    herramientas: dict[str, int] = {}
    usuarios = set()
    for hora, fuera_de_horario, duracion, tools, user_id in filas:
        por_hora[int(hora[:2])] += 1
        fuera += int(bool(fuera_de_horario))
        duraciones.append(int(duracion or 0))
        usuarios.add(user_id)
        for h in (tools or "").split(","):
            if h:
                herramientas[h] = herramientas.get(h, 0) + 1

    errores = por_estado.get("error", 0)
    return {
        "periodo_dias": dias,
        "canal": canal,
        "totales": {
            "interacciones": total,
            "usuarios": len(usuarios),
            "fuera_de_horario": fuera,
            "porcentaje_fuera_de_horario": round(100 * fuera / total, 1) if total else 0.0,
            "errores": errores,
            "porcentaje_errores": round(100 * errores / total, 1) if total else 0.0,
            "duracion_mediana_ms": _percentil(duraciones, 50),
            "duracion_p95_ms": _percentil(duraciones, 95),
            "reclamos_abiertos": reclamos_por_estado.get("abierto", 0),
        },
        "por_hora": por_hora,
        "por_tipo": dict(sorted(por_tipo.items(), key=lambda kv: -kv[1])),
        "por_canal": dict(sorted(por_canal.items(), key=lambda kv: -kv[1])),
        "herramientas": dict(sorted(herramientas.items(), key=lambda kv: -kv[1])),
        "reclamos": {"por_estado": reclamos_por_estado, "por_tipo": reclamos_por_tipo},
    }


def listar_reclamos(estado: Optional[str] = None, limite: int = 200) -> list[dict]:
    with get_session() as session:
        q = session.query(Reclamo)
        if estado:
            q = q.filter(Reclamo.estado == estado)
        return [r.to_dict() for r in q.order_by(Reclamo.id.desc()).limit(max(1, min(limite, 1000)))]


def cambiar_estado_reclamo(numero: int, estado: str) -> Optional[dict]:
    """Cambia el estado de un reclamo. None si no existe; ValueError si el estado no es válido."""
    if estado not in ESTADOS_RECLAMO:
        raise ValueError(f"Estado inválido: {estado!r}. Usá uno de: {', '.join(ESTADOS_RECLAMO)}.")
    with get_session() as session:
        reclamo = session.get(Reclamo, numero)
        if reclamo is None:
            return None
        reclamo.estado = estado
        session.flush()
        return reclamo.to_dict()
