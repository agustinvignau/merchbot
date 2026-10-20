"""Puerta de entrada única a la lógica del bot.

Todas las interfaces (Telegram hoy, web en la Fase 1) hablan con `ChatService`
y nunca directamente con `MerchBot` ni con la base. Así:

- la validación de mensajes vive en un solo lugar;
- el registro de interacciones (Fase 2) se agrega acá una sola vez;
- cambiar el modelo o el proveedor de LLM no toca las interfaces.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from merchbot.core import reports
from merchbot.core.assistant import MerchBot, UserId
from merchbot.core.memory import SqlConversationStore, Turno


logger = logging.getLogger(__name__)

MAX_MESSAGE_LEN = 2000
HISTORIAL_VISIBLE = 50


def crear_asistente_persistente() -> MerchBot:
    """Asistente con memoria guardada en la base (sobrevive a reinicios)."""
    return MerchBot(store=SqlConversationStore(max_turnos=MerchBot.HISTORIAL_MAX_TURNOS))


MENSAJE_VACIO = (
    "Decime una consulta. Ej: '¿cuántas remeras negras M tengo?', "
    "'qué pidió Coca-Cola', 'qué hay que comprar'."
)
MENSAJE_DEMASIADO_LARGO = (
    f"El mensaje es muy largo (máximo {MAX_MESSAGE_LEN} caracteres). "
    "Probá dividirlo en consultas más cortas."
)


class ChatService:
    """Orquesta una conversación: valida, delega en el asistente y mide."""

    def __init__(
        self,
        assistant: Optional[MerchBot] = None,
        assistant_factory: Callable[[], MerchBot] = crear_asistente_persistente,
    ) -> None:
        self._assistant = assistant
        self._assistant_factory = assistant_factory

    @property
    def assistant(self) -> MerchBot:
        """El asistente se crea recién cuando hace falta (evita pedir la API key al importar)."""
        if self._assistant is None:
            self._assistant = self._assistant_factory()
        return self._assistant

    # ---- Conversación ----------------------------------------------------

    def ask(self, user_id: UserId, message: str) -> str:
        """Procesa un mensaje en lenguaje natural y devuelve la respuesta."""
        texto = (message or "").strip()
        if not texto:
            return MENSAJE_VACIO
        if len(texto) > MAX_MESSAGE_LEN:
            return MENSAJE_DEMASIADO_LARGO

        inicio = time.perf_counter()
        respuesta = self.assistant.ask(user_id, texto)
        duracion_ms = int((time.perf_counter() - inicio) * 1000)
        logger.info("Consulta respondida user=%s en %d ms", user_id, duracion_ms)
        return respuesta

    def history(self, user_id: UserId, limit: int = HISTORIAL_VISIBLE) -> list[Turno]:
        """Conversación guardada del usuario, para mostrarla en pantalla."""
        return self.assistant.memoria.history(user_id, limit=limit)

    def clear(self, user_id: UserId) -> int:
        """Borra el historial del usuario. Devuelve cuántos turnos había."""
        return self.assistant.clear_memory(user_id)

    # ---- Atajos sin IA ---------------------------------------------------

    @staticmethod
    def productos_a_comprar() -> list[dict]:
        return reports.productos_a_comprar()

    @staticmethod
    def resumen_ejecutivo() -> dict:
        return reports.resumen_ejecutivo()


_chat_service: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    """Instancia compartida por toda la aplicación."""
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
