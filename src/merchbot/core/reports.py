"""Reportes directos sobre la base, sin IA.

Los usan los atajos de las interfaces (/comprar, /resumen en Telegram; el panel
web más adelante). Devuelven dicts planos, nunca objetos ORM, para poder usarse
fuera de la sesión de base de datos.
"""
from __future__ import annotations

from sqlalchemy import func

from merchbot.data.database import get_session
from merchbot.data.models import Pedido, StockItem


def productos_a_comprar() -> list[dict]:
    """Productos con estado COMPRAR. Ordenados por urgencia."""
    with get_session() as session:
        items = (
            session.query(StockItem)
            .filter(StockItem.estado == "COMPRAR")
            .order_by(StockItem.stock_actual.asc())
            .all()
        )
        return [it.to_dict() for it in items]


def resumen_ejecutivo() -> dict:
    """Métricas agregadas de stock y pedidos para el resumen ejecutivo."""
    with get_session() as session:
        total_skus = session.query(StockItem).count()
        skus_comprar = (
            session.query(StockItem)
            .filter(StockItem.estado == "COMPRAR")
            .count()
        )
        skus_ok = total_skus - skus_comprar
        unidades_totales = (
            session.query(func.sum(StockItem.stock_actual))
            .filter(StockItem.stock_actual > 0)
            .scalar() or 0
        )
        total_pedidos = session.query(Pedido).count()
        unidades_vendidas = session.query(func.sum(Pedido.cantidad)).scalar() or 0
        clientes_distintos = session.query(Pedido.cliente).distinct().count()

        top_cliente_row = (
            session.query(Pedido.cliente, func.sum(Pedido.cantidad).label("total"))
            .group_by(Pedido.cliente)
            .order_by(func.sum(Pedido.cantidad).desc())
            .first()
        )
        top_cliente = (
            (top_cliente_row.cliente, top_cliente_row.total)
            if top_cliente_row else None
        )

        top_sku_row = (
            session.query(Pedido.sku, Pedido.producto,
                          func.sum(Pedido.cantidad).label("total"))
            .group_by(Pedido.sku, Pedido.producto)
            .order_by(func.sum(Pedido.cantidad).desc())
            .first()
        )
        top_producto = (
            (top_sku_row.producto or top_sku_row.sku, top_sku_row.total)
            if top_sku_row else None
        )

    return {
        "total_skus": total_skus,
        "skus_ok": skus_ok,
        "skus_comprar": skus_comprar,
        "unidades_totales": int(unidades_totales),
        "total_pedidos": total_pedidos,
        "unidades_vendidas": int(unidades_vendidas),
        "clientes_distintos": clientes_distintos,
        "top_cliente": top_cliente,
        "top_producto": top_producto,
    }
