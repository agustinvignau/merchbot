"""Cadena de modelos de Gemini: si uno se queda sin cuota, se pasa al siguiente.

GEMINI_MODEL es el principal y GEMINI_MODELOS_RESPALDO una lista separada por
comas. Cuando un modelo devuelve 429 (cuota) o 404 (modelo dado de baja), queda
"en pausa" un rato y la consulta sigue con el próximo de la lista:

- cuota por minuto: la pausa es lo que sugiere la API en `retryDelay`;
- cuota diaria: una hora (se vuelve a probar, por si ya se renovó);
- modelo saturado (503, "high demand"): 30 segundos;
- modelo inexistente: hasta reiniciar (24 h).

Si todos están en pausa se prueba igual el que se libera antes. Si fallan todos,
sube el error más "pasajero" (saturación o cuota por minuto antes que cuota
diaria), así quien llama sabe que vale la pena esperar y reintentar.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Callable, Optional, TypeVar

from merchbot.config import settings

logger = logging.getLogger(__name__)
T = TypeVar("T")

PAUSA_POR_DEFECTO = 60.0
PAUSA_DIARIA = 3600.0
PAUSA_SATURADO = 30.0
PAUSA_MODELO_INEXISTENTE = 24 * 3600.0
# Del más pasajero al más duradero: si fallan todos, sube el primero de esta lista.
PRIORIDAD_ERROR = ("sobrecargado", "cuota_minuto", "cuota_diaria", "modelo_no_disponible")


def modelos_configurados(principal: Optional[str] = None) -> list[str]:
    """Principal + respaldos, sin repetidos y en orden."""
    lista = [principal or settings.gemini_model, *settings.gemini_modelos_respaldo.split(",")]
    vistos: list[str] = []
    for m in (x.strip() for x in lista):
        if m and m not in vistos:
            vistos.append(m)
    return vistos


def motivo_para_cambiar(exc: BaseException) -> Optional[str]:
    """'cuota_minuto', 'cuota_diaria', 'sobrecargado', 'modelo_no_disponible' o None si es otro error."""
    texto = f"{exc} {getattr(exc, 'status', '')}"
    codigo = getattr(exc, "code", None)
    if codigo == 429 or "RESOURCE_EXHAUSTED" in texto or " 429 " in f" {texto} ":
        return "cuota_diaria" if "PerDay" in texto else "cuota_minuto"
    if codigo == 503 or "UNAVAILABLE" in texto or "high demand" in texto:
        return "sobrecargado"
    if codigo == 404 or "NOT_FOUND" in texto or "no longer available" in texto:
        return "modelo_no_disponible"
    return None


def segundos_de_pausa(exc: BaseException, motivo: str) -> float:
    if motivo == "modelo_no_disponible":
        return PAUSA_MODELO_INEXISTENTE
    if motivo == "cuota_diaria":
        return PAUSA_DIARIA
    if motivo == "sobrecargado":
        return PAUSA_SATURADO
    m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s", str(exc))
    return float(m.group(1)) + 1 if m else PAUSA_POR_DEFECTO


class SelectorDeModelos:
    def __init__(self, modelos: list[str], reloj: Callable[[], float] = time.monotonic) -> None:
        if not modelos:
            raise ValueError("Hace falta al menos un modelo.")
        self.modelos = modelos
        self._reloj = reloj
        self._pausado_hasta: dict[str, float] = {}
        self._lock = threading.Lock()

    def orden(self) -> list[str]:
        """Disponibles primero (en el orden configurado); después los pausados, el que se libera antes primero."""
        ahora = self._reloj()
        with self._lock:
            libres = [m for m in self.modelos if self._pausado_hasta.get(m, 0) <= ahora]
            pausados = sorted((m for m in self.modelos if m not in libres), key=lambda m: self._pausado_hasta[m])
        return libres + pausados

    def pausar(self, modelo: str, segundos: float) -> None:
        with self._lock:
            self._pausado_hasta[modelo] = self._reloj() + segundos

    def ejecutar(self, llamada: Callable[[str], T]) -> tuple[T, str]:
        """Corre `llamada(modelo)` con el primero que funcione. Devuelve (resultado, modelo usado)."""
        errores: dict[str, BaseException] = {}
        for modelo in self.orden():
            try:
                return llamada(modelo), modelo
            except Exception as e:  # noqa: BLE001
                motivo = motivo_para_cambiar(e)
                if motivo is None:
                    raise
                pausa = segundos_de_pausa(e, motivo)
                self.pausar(modelo, pausa)
                logger.warning("Modelo %s: %s (pausa %.0f s). Pruebo el siguiente.", modelo, motivo, pausa)
                errores.setdefault(motivo, e)
        raise next(errores[m] for m in PRIORIDAD_ERROR if m in errores)
