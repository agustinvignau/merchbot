"""Actualización de la base desde la fuente configurada.

Un solo punto de entrada para el scheduler, el comando /sync de Telegram y la
web: según DATA_SOURCE sincroniza desde Google Sheets o carga la planilla de demo.
"""
from __future__ import annotations

from merchbot.config import settings
from merchbot.data.demo_seed import cargar_datos_demo
from merchbot.data.sheets_sync import SyncResult, sync_from_sheets


def actualizar_datos() -> SyncResult:
    if settings.fuente_de_datos == "demo":
        return cargar_datos_demo()
    return sync_from_sheets()
