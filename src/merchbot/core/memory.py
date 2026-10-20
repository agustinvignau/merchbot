"""Memoria conversacional: los últimos turnos de cada usuario.

Dos implementaciones con la misma interfaz:

- `InMemoryConversationStore`: rápida, se pierde al reiniciar. Útil en tests.
  Guarda solo los últimos `max_turnos`, así que `limit` no puede superar ese tope.
- `SqlConversationStore`: guarda cada mensaje en la tabla `mensajes`, así la
  conversación sobrevive a reinicios y la web puede mostrar el historial.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional, Protocol, Union

from merchbot.data.database import get_session
from merchbot.data.models import Mensaje


# Identificador de usuario: int en Telegram, str (id de sesión) en la web.
UserId = Union[int, str]

ROLES_VALIDOS = ("user", "model")


@dataclass(slots=True)
class Turno:
    role: str   # "user" o "model"
    text: str


class ConversationStore(Protocol):
    def history(self, user_id: UserId, limit: Optional[int] = None) -> list[Turno]:
        """Últimos turnos del usuario, del más viejo al más nuevo.

        Sin `limit` devuelve la ventana que ve el modelo (`max_turnos`).
        """

    def append(self, user_id: UserId, role: str, text: str) -> None:
        """Agrega un turno al final."""

    def clear(self, user_id: UserId) -> int:
        """Borra el historial. Devuelve cuántos turnos había."""


class InMemoryConversationStore:
    def __init__(self, max_turnos: int = 10) -> None:
        self.max_turnos = max_turnos
        self._data: dict[str, deque[Turno]] = defaultdict(
            lambda: deque(maxlen=self.max_turnos)
        )

    def history(self, user_id: UserId, limit: Optional[int] = None) -> list[Turno]:
        turnos = list(self._data.get(str(user_id), ()))
        return turnos[-limit:] if limit else turnos

    def append(self, user_id: UserId, role: str, text: str) -> None:
        _validar_rol(role)
        self._data[str(user_id)].append(Turno(role=role, text=text))

    def clear(self, user_id: UserId) -> int:
        return len(self._data.pop(str(user_id), ()))


class SqlConversationStore:
    def __init__(self, max_turnos: int = 10) -> None:
        self.max_turnos = max_turnos

    def history(self, user_id: UserId, limit: Optional[int] = None) -> list[Turno]:
        with get_session() as session:
            filas = (
                session.query(Mensaje)
                .filter(Mensaje.user_id == str(user_id))
                .order_by(Mensaje.id.desc())
                .limit(limit or self.max_turnos)
                .all()
            )
            return [Turno(role=f.role, text=f.text) for f in reversed(filas)]

    def append(self, user_id: UserId, role: str, text: str) -> None:
        _validar_rol(role)
        with get_session() as session:
            session.add(Mensaje(user_id=str(user_id), role=role, text=text))

    def clear(self, user_id: UserId) -> int:
        with get_session() as session:
            return (
                session.query(Mensaje)
                .filter(Mensaje.user_id == str(user_id))
                .delete()
            )


def _validar_rol(role: str) -> None:
    if role not in ROLES_VALIDOS:
        raise ValueError(f"Rol inválido: {role!r}. Usá 'user' o 'model'.")
