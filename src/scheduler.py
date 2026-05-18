"""Sync automático periódico con Google Sheets.

Usa APScheduler en modo BackgroundScheduler. Cuando inicia el bot:
1. Hace un sync inicial (que también puebla la DB en el primer arranque).
2. Programa un sync recurrente cada SYNC_INTERVAL_MIN minutos.

El sync corre silencioso: no manda mensajes al usuario. Si falla,
solo se loguea. El usuario puede ver el estado con /sync manual.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from src.config import settings
from src.sheets_sync import sync_from_sheets


logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _do_sync() -> None:
    """Job que corre en background. Atrapa cualquier excepción."""
    try:
        result = sync_from_sheets()
        if result.ok:
            logger.info(
                "Sync automático OK | stock=%d (%d nuevos, %d upd) | pedidos=%d",
                result.stock_total, result.stock_insertados,
                result.stock_actualizados, result.pedidos_total,
            )
        else:
            logger.warning("Sync automático falló: %s", result.error)
    except Exception:
        logger.exception("Excepción inesperada en sync automático")


def start_scheduler() -> BackgroundScheduler:
    """Arranca el scheduler. Idempotente — llamarlo dos veces no rompe."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    # Sync inicial síncrono — sin esto el bot arranca con DB vacía.
    logger.info("Sync inicial...")
    _do_sync()

    interval_min = settings.sync_interval_min
    if interval_min <= 0:
        logger.info("SYNC_INTERVAL_MIN=0 → sync automático desactivado, solo /sync manual.")
        _scheduler = BackgroundScheduler()  # vacío, no programa nada
        return _scheduler

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _do_sync,
        trigger="interval",
        minutes=interval_min,
        id="sheets_sync",
        max_instances=1,           # no superponer syncs si uno tarda
        coalesce=True,             # si quedaron varios pendientes, ejecutar uno solo
    )
    _scheduler.start()
    logger.info("Scheduler arrancado: sync cada %d minutos", interval_min)
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
