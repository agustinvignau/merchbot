"""Rate limiter sencillo en memoria con sliding window.

Pensado para frenar el spam de usuarios NO autorizados al bot:
- Los primeros `max_attempts` intentos en una ventana de `window_minutes`
  reciben respuesta normal (mensaje educado de "no estás autorizado").
- A partir del intento `max_attempts + 1` dentro de la misma ventana,
  el bot deja de responder (silencioso) — ahorra cuota de envío y
  no da feedback al posible atacante.
- Si pasan `window_minutes` sin actividad, el contador se resetea.

NO se usa para usuarios autorizados.

Limitación conocida: el estado vive en RAM. Si el bot se reinicia, se pierde.
Para deploy con múltiples workers, migrar a Redis.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Callable

from merchbot.timeutils import utc_now


class RateLimiter:
    """Sliding window rate limiter por clave (user_id).

    Estrategia: por cada user_id mantenemos un deque con los timestamps de
    los últimos intentos. Al consultar, primero limpiamos los expirados
    (fuera de la ventana) y después contamos los que quedan.
    """

    def __init__(
        self,
        max_attempts: int,
        window_minutes: int,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """
        Args:
            max_attempts: cuántos intentos permitimos en la ventana
            window_minutes: tamaño de la ventana deslizante
            clock: función que devuelve "ahora" — inyectable para tests
        """
        if max_attempts < 1:
            raise ValueError("max_attempts debe ser >= 1")
        if window_minutes < 1:
            raise ValueError("window_minutes debe ser >= 1")
        self.max_attempts = max_attempts
        self.window = timedelta(minutes=window_minutes)
        self._clock = clock
        # Cap el tamaño del deque para no crecer indefinidamente si alguien
        # spamea miles de mensajes seguidos: solo necesitamos los últimos N
        # para tomar decisión (con margen).
        self._attempts: dict[object, deque[datetime]] = defaultdict(
            lambda: deque(maxlen=max_attempts * 10)
        )

    def _cleanup_expired(self, key: object) -> None:
        """Elimina los timestamps fuera de la ventana actual."""
        now = self._clock()
        cutoff = now - self.window
        attempts = self._attempts[key]
        while attempts and attempts[0] < cutoff:
            attempts.popleft()

    def should_respond(self, key: object) -> bool:
        """True si todavía podemos responderle a este usuario en esta ventana.

        Llamar ANTES de register_attempt — si esta función devuelve False,
        el caller debería ignorar el mensaje sin responder.
        """
        self._cleanup_expired(key)
        return len(self._attempts[key]) < self.max_attempts

    def register_attempt(self, key: object) -> None:
        """Registra un intento del usuario (timestamp = ahora)."""
        self._attempts[key].append(self._clock())

    def reset(self, key: object) -> None:
        """Resetea el contador de un usuario específico (útil cuando se autoriza)."""
        self._attempts.pop(key, None)

    def reset_all(self) -> None:
        """Resetea todo el estado (útil para tests)."""
        self._attempts.clear()

    def current_count(self, key: object) -> int:
        """Cuántos intentos válidos tiene actualmente este usuario (para debug/logs)."""
        self._cleanup_expired(key)
        return len(self._attempts[key])
