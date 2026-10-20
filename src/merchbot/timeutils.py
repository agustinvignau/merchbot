"""Fechas siempre en UTC y con zona horaria (datetime.utcnow() está deprecado)."""
from datetime import datetime, timezone
from typing import Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(valor: Optional[datetime]) -> Optional[str]:
    """ISO 8601 con zona. SQLite devuelve fechas sin zona: se guardaron en UTC."""
    if valor is None:
        return None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.isoformat()
