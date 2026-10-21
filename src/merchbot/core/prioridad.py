"""Prioridad de un reclamo: un puntaje de 0 a 100 explicable.

Combina señales simples, cada una con su motivo, para que quien atienda sepa
por qué un reclamo quedó arriba:

- el tipo de reclamo (una falla de producción pesa más que una consulta),
- el sentimiento (enojo explícito),
- la urgencia ("hoy", "mañana", "evento", "urgente"),
- el volumen afectado (cuántas unidades menciona),
- la reincidencia ("otra vez", "segunda vez").

Alta ≥ 60, media ≥ 35, baja por debajo. Los reclamos de prioridad alta o con
enojo fuerte se marcan para atención humana.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from merchbot.core.sentimiento import Sentimiento

PESO_TIPO = {
    "producto_defectuoso": 25,
    "error_en_pedido": 25,
    "faltante": 20,
    "demora": 15,
    "otro": 5,
}
URGENCIA = ("urgente", "urgencia", "hoy", "manana", "evento", "cuanto antes", "ya mismo",
            "inmediato", "lo antes posible", "esta semana")
REINCIDENCIA = ("otra vez", "de nuevo", "segunda vez", "tercera vez", "siempre lo mismo", "sigo esperando",
                "sigue sin")
UMBRAL_ALTA = 60
UMBRAL_MEDIA = 35


@dataclass
class Prioridad:
    nivel: str                 # "alta" | "media" | "baja"
    puntaje: int               # 0 a 100
    requiere_humano: bool
    motivos: list[str] = field(default_factory=list)


def _plano(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def calcular_prioridad(texto: str, tipo: str, sentimiento: Sentimiento) -> Prioridad:
    plano = _plano(texto or "")
    puntaje = 0.0
    motivos: list[str] = []

    base = PESO_TIPO.get(tipo, PESO_TIPO["otro"])
    puntaje += base
    motivos.append(f"tipo {tipo.replace('_', ' ')} (+{base})")

    if sentimiento.etiqueta == "NEG":
        aporte = round(15 + 25 * min(1.0, abs(sentimiento.puntaje)))
        puntaje += aporte
        motivos.append(f"tono negativo (+{aporte})")
    elif sentimiento.etiqueta == "POS":
        puntaje -= 10
        motivos.append("tono positivo (−10)")

    urgencias = [u for u in URGENCIA if re.search(rf"\b{u}\b", plano)]
    if urgencias:
        puntaje += 20
        motivos.append(f"urgencia: {', '.join(urgencias)} (+20)")

    cantidades = [int(n) for n in re.findall(r"\b\d{1,6}\b", plano)]
    mayor = max(cantidades, default=0)
    if mayor >= 100:
        puntaje += 15
        motivos.append(f"{mayor} unidades (+15)")
    elif mayor >= 20:
        puntaje += 8
        motivos.append(f"{mayor} unidades (+8)")

    reincide = [r for r in REINCIDENCIA if r in plano]
    if reincide:
        puntaje += 10
        motivos.append(f"reincidencia: {reincide[0]} (+10)")

    puntaje_final = int(max(0, min(100, round(puntaje))))
    if puntaje_final >= UMBRAL_ALTA:
        nivel = "alta"
    elif puntaje_final >= UMBRAL_MEDIA:
        nivel = "media"
    else:
        nivel = "baja"
    enojo_fuerte = sentimiento.etiqueta == "NEG" and sentimiento.puntaje <= -0.6
    return Prioridad(nivel, puntaje_final, nivel == "alta" or enojo_fuerte, motivos)
