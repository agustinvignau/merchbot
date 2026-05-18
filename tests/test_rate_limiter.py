"""Tests del RateLimiter.

Usamos un clock inyectable (FakeClock) para simular el paso del tiempo
sin necesidad de time.sleep() — los tests corren instantáneos.
"""
from datetime import datetime, timedelta

import pytest

from src.rate_limiter import RateLimiter


class FakeClock:
    """Reloj manipulable para tests."""

    def __init__(self, start: datetime = datetime(2026, 1, 1, 0, 0, 0)):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        """Avanza el tiempo. Pasale minutes=, seconds=, etc."""
        self.now += timedelta(**kwargs)


# ---------------------------------------------------------------------------
# Validación de inputs
# ---------------------------------------------------------------------------

class TestInitValidation:
    def test_max_attempts_cero_falla(self):
        with pytest.raises(ValueError):
            RateLimiter(max_attempts=0, window_minutes=10)

    def test_window_cero_falla(self):
        with pytest.raises(ValueError):
            RateLimiter(max_attempts=3, window_minutes=0)


# ---------------------------------------------------------------------------
# Comportamiento básico
# ---------------------------------------------------------------------------

class TestSlidingWindow:
    def test_primeros_n_intentos_pasan(self):
        clock = FakeClock()
        rl = RateLimiter(max_attempts=3, window_minutes=10, clock=clock)

        for i in range(3):
            assert rl.should_respond(user_id := 1) is True
            rl.register_attempt(user_id)

    def test_intento_n_mas_uno_es_silenciado(self):
        clock = FakeClock()
        rl = RateLimiter(max_attempts=3, window_minutes=10, clock=clock)

        for _ in range(3):
            rl.register_attempt(1)
        assert rl.should_respond(1) is False

    def test_pasa_la_ventana_se_resetea(self):
        clock = FakeClock()
        rl = RateLimiter(max_attempts=3, window_minutes=10, clock=clock)

        for _ in range(3):
            rl.register_attempt(1)
        assert rl.should_respond(1) is False

        # Avanzar más allá de la ventana
        clock.advance(minutes=11)
        assert rl.should_respond(1) is True

    def test_ventana_es_deslizante_no_fija(self):
        """Si los intentos están espaciados, el contador no se acumula."""
        clock = FakeClock()
        rl = RateLimiter(max_attempts=3, window_minutes=10, clock=clock)

        # Intento 1 en t=0
        rl.register_attempt(1)
        # Intento 2 en t=5min
        clock.advance(minutes=5)
        rl.register_attempt(1)
        # Intento 3 en t=11min — el primero (t=0) ya salió de la ventana
        clock.advance(minutes=6)
        # Ahora solo hay 1 intento válido en la ventana (el de t=5min)
        assert rl.current_count(1) == 1
        assert rl.should_respond(1) is True

    def test_usuarios_aislados(self):
        clock = FakeClock()
        rl = RateLimiter(max_attempts=3, window_minutes=10, clock=clock)

        # User 1 se gasta todos sus intentos
        for _ in range(3):
            rl.register_attempt(1)
        assert rl.should_respond(1) is False

        # User 2 todavía tiene chances
        assert rl.should_respond(2) is True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_reset_de_usuario_individual(self):
        clock = FakeClock()
        rl = RateLimiter(max_attempts=3, window_minutes=10, clock=clock)

        for _ in range(3):
            rl.register_attempt(1)
        assert rl.should_respond(1) is False

        rl.reset(1)
        assert rl.should_respond(1) is True
        assert rl.current_count(1) == 0

    def test_reset_all(self):
        clock = FakeClock()
        rl = RateLimiter(max_attempts=3, window_minutes=10, clock=clock)

        for u in (1, 2, 3):
            for _ in range(3):
                rl.register_attempt(u)
            assert rl.should_respond(u) is False

        rl.reset_all()
        for u in (1, 2, 3):
            assert rl.should_respond(u) is True

    def test_current_count_refleja_intentos_validos(self):
        clock = FakeClock()
        rl = RateLimiter(max_attempts=10, window_minutes=10, clock=clock)

        assert rl.current_count(1) == 0
        rl.register_attempt(1)
        assert rl.current_count(1) == 1
        rl.register_attempt(1)
        assert rl.current_count(1) == 2

        # Avanzar fuera de la ventana
        clock.advance(minutes=11)
        assert rl.current_count(1) == 0


# ---------------------------------------------------------------------------
# Caso realista: ráfaga de 100 intentos
# ---------------------------------------------------------------------------

class TestSpamScenario:
    def test_rafaga_de_100_intentos_responde_solo_a_los_primeros(self):
        """Simula a un atacante mandando 100 mensajes seguidos.
        El bot debería responder solo los primeros 3 y silenciar el resto."""
        clock = FakeClock()
        rl = RateLimiter(max_attempts=3, window_minutes=10, clock=clock)

        respondidos = 0
        silenciados = 0
        for _ in range(100):
            if rl.should_respond(user_id := 999):
                respondidos += 1
            else:
                silenciados += 1
            rl.register_attempt(user_id)
            # Cada mensaje a 0.1s del anterior, no avanzamos mucho el reloj
            clock.advance(seconds=0)

        assert respondidos == 3
        assert silenciados == 97
