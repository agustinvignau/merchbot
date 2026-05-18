"""Sincronización con Google Sheets público (read-only, sin auth).

Estrategia: el Sheets es la fuente de verdad. Cuando alguien edita el Sheets
(carga ingresos, registra pedido), esos cambios se propagan al bot vía sync.

Usamos el endpoint gviz que permite exportar una hoja como CSV usando su nombre
(en vez del GID numérico). No requiere OAuth, basta con que el Sheets esté
compartido "Cualquiera con el enlace - Lector".

URL pattern:
    https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={TAB_NAME}
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import datetime, date
from typing import Iterable, Optional

import requests

from src.config import settings
from src.database import get_session
from src.models import StockItem, Pedido


logger = logging.getLogger(__name__)


SHEETS_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/{sheet_id}"
    "/gviz/tq?tqx=out:csv&sheet={tab}"
)


# ---------------------------------------------------------------------------
# Resultado de un sync (para logging / mensajes al usuario)
# ---------------------------------------------------------------------------

@dataclass
class SyncResult:
    """Resumen de qué pasó en el último sync. Usado para responder /sync."""
    ok: bool
    stock_total: int = 0
    stock_insertados: int = 0
    stock_actualizados: int = 0
    pedidos_total: int = 0
    pedidos_insertados: int = 0
    error: Optional[str] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

    def resumen(self) -> str:
        """Mensaje legible para el bot."""
        if not self.ok:
            return f"❌ Error en sync: {self.error}"
        return (
            f"✅ Sync OK\n"
            f"• Stock: {self.stock_total} productos "
            f"({self.stock_insertados} nuevos, {self.stock_actualizados} actualizados)\n"
            f"• Pedidos: {self.pedidos_total} ({self.pedidos_insertados} nuevos)"
        )


# ---------------------------------------------------------------------------
# Fetch CSV desde Sheets
# ---------------------------------------------------------------------------

def fetch_sheet_as_csv(sheet_id: str, tab: str, timeout: int = 15) -> str:
    """Descarga una hoja del Sheets como CSV string.

    Lanza RuntimeError si:
    - El Sheets no está compartido como público
    - El nombre de la hoja no existe
    - Hay un problema de red
    """
    url = SHEETS_CSV_URL.format(sheet_id=sheet_id, tab=tab)
    logger.info(f"Fetching {url}")
    try:
        r = requests.get(url, timeout=timeout)
    except requests.RequestException as e:
        raise RuntimeError(f"No pude conectar con Google Sheets: {e}") from e

    if r.status_code == 404:
        raise RuntimeError(
            f"La hoja '{tab}' no existe en el Sheets {sheet_id}, "
            "o el Sheets no está compartido como público."
        )
    if r.status_code != 200:
        raise RuntimeError(
            f"Google Sheets respondió {r.status_code}. "
            "Verificá que el Sheets esté compartido como 'Cualquiera con el enlace - Lector'."
        )

    return r.text


# ---------------------------------------------------------------------------
# Parseo de CSV
# ---------------------------------------------------------------------------

def _safe_int(val: str, default: int = 0) -> int:
    """Convierte 'val' a int, devuelve default si está vacío o no es número."""
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return default


def _parse_fecha(val: str) -> Optional[date]:
    """Acepta varios formatos típicos de Sheets."""
    if not val:
        return None
    val = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    logger.warning(f"Fecha no reconocida: {val!r}")
    return None


def parse_stock_csv(csv_text: str) -> list[dict]:
    """Parsea el CSV de la hoja Stock a lista de dicts listos para upsert."""
    reader = csv.DictReader(io.StringIO(csv_text))
    items = []
    for row in reader:
        sku = (row.get("SKU") or "").strip()
        if not sku:
            continue  # ignorar filas vacías
        items.append({
            "sku": sku,
            "producto": (row.get("Producto") or "").strip(),
            "modelo": (row.get("Modelo") or "").strip(),
            "color": (row.get("Color") or "").strip(),
            "talle": (row.get("Talle") or "").strip(),
            "stock_inicial": _safe_int(row.get("Stock Inicial", 0)),
            "ingresos": _safe_int(row.get("Ingresos", 0)),
            "pedidos": _safe_int(row.get("Pedidos", 0)),
            "stock_actual": _safe_int(row.get("Stock Actual", 0)),
            "estado": (row.get("Estado") or "").strip().upper() or "OK",
        })
    return items


def parse_pedidos_csv(csv_text: str) -> list[dict]:
    """Parsea el CSV de la hoja Pedidos a lista de dicts."""
    reader = csv.DictReader(io.StringIO(csv_text))
    items = []
    for row in reader:
        sku = (row.get("SKU") or "").strip()
        cantidad = _safe_int(row.get("Cantidad", 0))
        if not sku or cantidad == 0:
            continue
        items.append({
            "fecha": _parse_fecha(row.get("Fecha")),
            "cliente": (row.get("Cliente") or "").strip(),
            "sku": sku,
            "producto": (row.get("Producto") or "").strip(),
            "cantidad": cantidad,
        })
    return items


# ---------------------------------------------------------------------------
# Upsert en DB
# ---------------------------------------------------------------------------

def _upsert_stock(items: Iterable[dict], now: datetime) -> tuple[int, int]:
    """Upsert por SKU. Devuelve (insertados, actualizados)."""
    insertados, actualizados = 0, 0
    with get_session() as session:
        for it in items:
            existing = session.query(StockItem).filter_by(sku=it["sku"]).first()
            if existing:
                for k, v in it.items():
                    setattr(existing, k, v)
                existing.last_synced_at = now
                actualizados += 1
            else:
                session.add(StockItem(**it, last_synced_at=now))
                insertados += 1
    return insertados, actualizados


def _replace_pedidos(items: list[dict], now: datetime) -> int:
    """Estrategia simple: borrar todos los pedidos y reinsertar.

    Por qué: los pedidos del Sheets no tienen un ID único, son apend-only.
    Si alguien borra/edita una fila en el Sheets, hacer upsert es complejo.
    Borrar + reinsertar es idempotente.
    """
    with get_session() as session:
        session.query(Pedido).delete()
        for it in items:
            if it["fecha"] is None:
                continue  # ignorar pedidos sin fecha válida
            session.add(Pedido(**it, last_synced_at=now))
    return len(items)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def sync_from_sheets(
    sheet_id: Optional[str] = None,
    stock_tab: Optional[str] = None,
    pedidos_tab: Optional[str] = None,
) -> SyncResult:
    """Sincroniza Stock y Pedidos desde el Google Sheets configurado.

    Devuelve un SyncResult con métricas. No lanza excepciones — las captura
    y las pone en SyncResult.error para que el bot pueda mostrarlas al usuario.
    """
    sheet_id = sheet_id or settings.sheets_id
    stock_tab = stock_tab or settings.sheets_stock_tab
    pedidos_tab = pedidos_tab or settings.sheets_pedidos_tab

    if not sheet_id:
        return SyncResult(ok=False, error="SHEETS_ID no configurado en .env")

    now = datetime.utcnow()
    try:
        # Stock
        stock_csv = fetch_sheet_as_csv(sheet_id, stock_tab)
        stock_items = parse_stock_csv(stock_csv)
        ins_s, upd_s = _upsert_stock(stock_items, now)

        # Pedidos
        pedidos_csv = fetch_sheet_as_csv(sheet_id, pedidos_tab)
        pedido_items = parse_pedidos_csv(pedidos_csv)
        ins_p = _replace_pedidos(pedido_items, now)

        return SyncResult(
            ok=True,
            stock_total=len(stock_items),
            stock_insertados=ins_s,
            stock_actualizados=upd_s,
            pedidos_total=len(pedido_items),
            pedidos_insertados=ins_p,
            timestamp=now,
        )
    except RuntimeError as e:
        logger.error(f"Sync falló: {e}")
        return SyncResult(ok=False, error=str(e), timestamp=now)
    except Exception as e:
        logger.exception("Sync falló con excepción inesperada")
        return SyncResult(ok=False, error=f"{type(e).__name__}: {e}", timestamp=now)
