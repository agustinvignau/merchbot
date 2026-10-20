"""Hora de la conversación: real o simulada.

El TP pide mostrar atención "a cualquier hora". En la demo el usuario elige
una hora simulada (por ejemplo 03:20) y el asistente responde como si fuera
ese momento: sabe si el depósito está abierto y lo aclara. Si no se elige
ninguna, se usa la hora real en la zona horaria configurada.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

from merchbot.config import settings


DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_FORMATO_HORA = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def validar_hora(valor: Optional[str]) -> Optional[str]:
    """Devuelve la hora normalizada "HH:MM", None si viene vacía, o lanza ValueError."""
    if valor is None or not str(valor).strip():
        return None
    valor = str(valor).strip()
    if len(valor) == 4 and valor[1] == ":":  # "3:20" → "03:20"
        valor = "0" + valor
    if not _FORMATO_HORA.match(valor):
        raise ValueError(f"Hora inválida: {valor!r}. Usá el formato HH:MM, por ejemplo 03:20.")
    return valor


def _a_time(valor: str) -> time:
    h, m = valor.split(":")
    return time(int(h), int(m))


@dataclass(frozen=True)
class Momento:
    hora: str               # "HH:MM"
    dia_semana: int         # 0 = lunes
    simulada: bool
    fuera_de_horario: bool

    @property
    def dia(self) -> str:
        return DIAS[self.dia_semana]

    @property
    def franja(self) -> str:
        h = int(self.hora[:2])
        if 6 <= h < 12:
            return "mañana"
        if 12 <= h < 19:
            return "tarde"
        if 19 <= h < 24:
            return "noche"
        return "madrugada"

    def contexto_para_el_modelo(self) -> str:
        """Texto que se agrega a las instrucciones del modelo en cada consulta."""
        horario = f"{settings.atencion_desde} a {settings.atencion_hasta}, {_dias_de_atencion()}"
        estado = (
            "FUERA del horario de atención humana: el depósito está cerrado."
            if self.fuera_de_horario
            else "dentro del horario de atención humana."
        )
        return (
            f"MOMENTO DE LA CONSULTA: {self.dia} {self.hora} hs ({self.franja}). "
            f"Es {estado} Horario de atención humana: {horario}.\n"
            "Si es fuera de horario y la consulta lo amerita, aclaralo en una frase corta: "
            "vos respondés igual las 24 horas, y lo que necesite a una persona (por ejemplo un "
            "reclamo) queda registrado para el próximo día hábil. Si es dentro del horario, no lo menciones."
        )


def _dias_de_atencion() -> str:
    dias = sorted(dias_habiles())
    if dias == [0, 1, 2, 3, 4]:
        return "de lunes a viernes"
    return ", ".join(DIAS[d] for d in dias)


def dias_habiles() -> set[int]:
    return {int(d) for d in settings.atencion_dias.split(",") if d.strip().isdigit()}


def esta_fuera_de_horario(hora: str, dia_semana: int) -> bool:
    if dia_semana not in dias_habiles():
        return True
    t = _a_time(hora)
    return not (_a_time(settings.atencion_desde) <= t < _a_time(settings.atencion_hasta))


def ahora_local() -> datetime:
    return datetime.now(ZoneInfo(settings.timezone))


def resolver_momento(hora_simulada: Optional[str] = None, ahora: Optional[datetime] = None) -> Momento:
    """Arma el Momento de una consulta: la hora simulada si hay, si no la real.

    El día de la semana siempre es el real (la demo simula la hora, no la fecha).
    """
    ahora = ahora or ahora_local()
    hora = validar_hora(hora_simulada)
    simulada = hora is not None
    if not simulada:
        hora = ahora.strftime("%H:%M")
    dia = ahora.weekday()
    return Momento(
        hora=hora,
        dia_semana=dia,
        simulada=simulada,
        fuera_de_horario=esta_fuera_de_horario(hora, dia),
    )
