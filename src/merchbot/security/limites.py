"""Límites de uso de la web, compartidos por toda la app.

- Chat: N consultas por minuto por sesión (protege la cuota de Gemini y evita abuso).
- Ingreso: N intentos por IP en una ventana (chat y panel), contra adivinar claves.
"""
from __future__ import annotations

from typing import Optional

from merchbot.config import settings
from merchbot.security.rate_limiter import RateLimiter

_chat: Optional[RateLimiter] = None
_login: Optional[RateLimiter] = None


def limite_chat() -> RateLimiter:
    global _chat
    if _chat is None:
        _chat = RateLimiter(max_attempts=settings.limite_chat_por_minuto, window_minutes=1)
    return _chat


def limite_login() -> RateLimiter:
    global _login
    if _login is None:
        _login = RateLimiter(max_attempts=settings.limite_login_intentos,
                             window_minutes=settings.limite_login_minutos)
    return _login


def permitir(limitador: RateLimiter, clave: object) -> bool:
    """Registra el intento y dice si todavía está dentro del límite."""
    if not limitador.should_respond(clave):
        return False
    limitador.register_attempt(clave)
    return True


def reiniciar() -> None:
    """Para tests o al cambiar la configuración."""
    global _chat, _login
    _chat = _login = None
