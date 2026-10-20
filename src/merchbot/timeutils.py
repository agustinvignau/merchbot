"""Fechas siempre en UTC y con zona horaria (datetime.utcnow() está deprecado)."""
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
