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
from dataclasses import dataclass
from typing import Callable, Optional

from merchbot.core import reports, tools
from merchbot.core.assistant import MerchBot, UserId
from merchbot.core.horario import resolver_momento
from merchbot.core.memory import SqlConversationStore, Turno
from merchbot.core.registro import clasificar, registrar_interaccion


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


@dataclass
class Atencion:
    """Lo que vuelve a la interfaz después de atender un mensaje."""
    texto: str
    hora: str
    fuera_de_horario: bool
    tipo: str


class ChatService:
    """Orquesta una conversación: valida, ubica la hora, delega, mide y registra."""

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

    def atender(
        self,
        user_id: UserId,
        message: str,
        canal: str = "web",
        hora_simulada: Optional[str] = None,
    ) -> Atencion:
        """Procesa un mensaje en lenguaje natural y registra la interacción.

        `hora_simulada` ("03:20") hace que el asistente responda como si fuera
        esa hora; sin ella se usa la hora real. Lanza ValueError si la hora es inválida.
        """
        momento = resolver_momento(hora_simulada)
        texto = (message or "").strip()
        if not texto:
            return Atencion(MENSAJE_VACIO, momento.hora, momento.fuera_de_horario, "conversacion")
        if len(texto) > MAX_MESSAGE_LEN:
            return Atencion(MENSAJE_DEMASIADO_LARGO, momento.hora, momento.fuera_de_horario, "conversacion")

        inicio = time.perf_counter()
        try:
            respuesta = self.assistant.responder(user_id, texto, momento=momento, canal=canal)
        except Exception:
            registrar_interaccion(
                canal=canal, user_id=str(user_id), momento=momento, consulta=texto,
                respuesta=None, herramientas=[], duracion_ms=_ms_desde(inicio), estado="error",
            )
            raise
        duracion = _ms_desde(inicio)
        tipo = clasificar(respuesta.herramientas)
        registrar_interaccion(
            canal=canal, user_id=str(user_id), momento=momento, consulta=texto,
            respuesta=respuesta.texto, herramientas=respuesta.herramientas,
            duracion_ms=duracion, estado="ok" if respuesta.completa else "error", tipo=tipo,
        )
        logger.info("Consulta %s respondida user=%s en %d ms", tipo, user_id, duracion)
        return Atencion(respuesta.texto, momento.hora, momento.fuera_de_horario, tipo)

    def ask(self, user_id: UserId, message: str, canal: str = "web",
            hora_simulada: Optional[str] = None) -> str:
        """Como `atender`, pero devuelve solo el texto."""
        return self.atender(user_id, message, canal=canal, hora_simulada=hora_simulada).texto

    def history(self, user_id: UserId, limit: int = HISTORIAL_VISIBLE) -> list[Turno]:
        """Conversación guardada del usuario, para mostrarla en pantalla."""
        return self.assistant.memoria.history(user_id, limit=limit)

    def clear(self, user_id: UserId) -> int:
        """Borra el historial del usuario. Devuelve cuántos turnos había."""
        return self.assistant.clear_memory(user_id)

    # ---- Atajos sin IA ---------------------------------------------------

    def productos_a_comprar(self, user_id: Optional[UserId] = None, canal: str = "web",
                            hora_simulada: Optional[str] = None) -> list[dict]:
        inicio = time.perf_counter()
        productos = reports.productos_a_comprar()
        if user_id is not None:
            self._registrar_atajo(user_id, canal, hora_simulada, "Qué hay que comprar",
                                  f"{len(productos)} producto(s) para reponer", "atajo_comprar",
                                  "reposicion", inicio)
        return productos

    def resumen_ejecutivo(self, user_id: Optional[UserId] = None, canal: str = "web",
                          hora_simulada: Optional[str] = None) -> dict:
        inicio = time.perf_counter()
        resumen = reports.resumen_ejecutivo()
        if user_id is not None:
            self._registrar_atajo(user_id, canal, hora_simulada, "Resumen del inventario",
                                  f"{resumen['total_skus']} SKUs, {resumen['skus_comprar']} para comprar",
                                  "atajo_resumen", "resumen", inicio)
        return resumen

    @staticmethod
    def _registrar_atajo(user_id, canal, hora_simulada, consulta, respuesta, herramienta, tipo, inicio) -> None:
        registrar_interaccion(
            canal=canal, user_id=str(user_id), momento=resolver_momento(hora_simulada),
            consulta=consulta, respuesta=respuesta, herramientas=[herramienta],
            duracion_ms=_ms_desde(inicio), tipo=tipo,
        )

    # ---- Reclamos sin IA (formulario) ------------------------------------

    def registrar_reclamo(self, user_id: UserId, descripcion: str, tipo: str = "otro",
                          cliente: Optional[str] = None, canal: str = "web",
                          hora_simulada: Optional[str] = None) -> dict:
        """Registra un reclamo cargado desde un formulario (sin pasar por el modelo)."""
        momento = resolver_momento(hora_simulada)
        inicio = time.perf_counter()
        resultado = tools.registrar_reclamo(
            descripcion, tipo, cliente,
            _contexto={"canal": canal, "user_id": str(user_id), "hora": momento.hora},
        )
        if resultado.get("ok"):
            registrar_interaccion(
                canal=canal, user_id=str(user_id), momento=momento,
                consulta=f"[formulario] {descripcion}", respuesta=f"Reclamo #{resultado['numero']}",
                herramientas=["formulario_reclamo"], duracion_ms=_ms_desde(inicio), tipo="reclamo",
            )
            resultado["fuera_de_horario"] = momento.fuera_de_horario
            self._anotar_en_la_conversacion(user_id, descripcion, resultado, momento.hora)
        return resultado

    def _anotar_en_la_conversacion(self, user_id, descripcion, reclamo, hora) -> None:
        """Deja el reclamo en la memoria: aparece al recargar y el asistente lo conoce."""
        try:
            memoria = self.assistant.memoria
        except Exception:  # sin API key no hay asistente; el reclamo ya quedó guardado
            logger.warning("Reclamo #%s registrado sin anotarlo en la conversación", reclamo["numero"])
            return
        memoria.append(user_id, "user", f"Reclamo: {descripcion}", hora=hora)
        memoria.append(user_id, "model", f"Registré el reclamo #{reclamo['numero']}. "
                       "Lo revisa una persona del equipo.", hora=hora)

    @staticmethod
    def consultar_reclamo(numero: int) -> dict:
        return tools.consultar_estado_reclamo(numero)


def _ms_desde(inicio: float) -> int:
    return int((time.perf_counter() - inicio) * 1000)


_chat_service: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    """Instancia compartida por toda la aplicación."""
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
