"""Funciones que el LLM puede llamar para consultar la base de datos.

Estas son funciones PURAS de consulta a la DB — no saben nada de Gemini.
Las exponemos al LLM como "tools" (function calling): el modelo decide cuál
llamar según la pregunta del usuario, ejecutamos la función, le devolvemos
el resultado, y el modelo arma la respuesta natural.

Ventaja clave vs inyectar el catálogo en el prompt:
- El modelo recibe SOLO datos relevantes a la query (no todo el inventario).
- Los datos vienen de SQL, no de "interpretar texto" — casi cero alucinación.
- Escala a 10.000+ SKUs sin cambiar el prompt.

Cada función devuelve un dict serializable a JSON (Gemini lo recibe así).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func

from merchbot.data.database import get_session
from merchbot.data.models import StockItem, Pedido


# ---------------------------------------------------------------------------
# Tools: cada una es una función que Gemini puede llamar
# ---------------------------------------------------------------------------

def buscar_stock(
    producto: Optional[str] = None,
    modelo: Optional[str] = None,
    color: Optional[str] = None,
    talle: Optional[str] = None,
) -> dict:
    """Busca productos en el stock filtrando por uno o más atributos.

    Todos los filtros son opcionales y se aplican con AND. Las búsquedas
    son case-insensitive y por coincidencia parcial (ej. 'gris' encuentra
    'Gris' y 'Gris Oscuro').

    Args:
        producto: Categoría base (ej. "Remera", "Buzo", "Gorra", "Taza").
        modelo: Tipo dentro de la categoría (ej. "Cuello Redondo", "Dry-Fit", "Canguro").
        color: Color del producto (ej. "Negro", "Blanco", "Gris").
        talle: Talle (ej. "S", "M", "L", "XL", "Único").

    Returns:
        dict con:
          - "encontrados": int (cantidad de SKUs que matchearon)
          - "items": lista de productos con SKU, descripción, stock_actual, estado
          - "stock_total": suma del stock de todos los matches (puede ser negativo)
    """
    with get_session() as session:
        q = session.query(StockItem)
        if producto:
            q = q.filter(StockItem.producto.ilike(f"%{producto}%"))
        if modelo:
            q = q.filter(StockItem.modelo.ilike(f"%{modelo}%"))
        if color:
            q = q.filter(StockItem.color.ilike(f"%{color}%"))
        if talle:
            q = q.filter(StockItem.talle.ilike(f"%{talle}%"))

        items = q.order_by(StockItem.stock_actual.desc()).all()
        items_data = [
            {
                "sku": it.sku,
                "descripcion": it.descripcion_completa,
                "stock_actual": it.stock_actual,
                "estado": it.estado,
            }
            for it in items
        ]
        stock_total = sum(i["stock_actual"] for i in items_data)

    return {
        "encontrados": len(items_data),
        "items": items_data,
        "stock_total": stock_total,
    }


def listar_productos_a_comprar() -> dict:
    """Lista los productos con estado COMPRAR (stock <= 0).

    Útil cuando el usuario pregunta "qué hay que comprar", "qué falta",
    "qué está en rojo", "qué tengo en negativo".

    Returns:
        dict con:
          - "cantidad": int (cuántos SKUs hay que comprar)
          - "items": lista ordenada por urgencia (los más negativos primero)
          - "total_unidades_faltantes": int (suma de cuánto falta de cada uno)
    """
    with get_session() as session:
        items = (
            session.query(StockItem)
            .filter(StockItem.estado == "COMPRAR")
            .order_by(StockItem.stock_actual.asc())
            .all()
        )
        items_data = [
            {
                "sku": it.sku,
                "descripcion": it.descripcion_completa,
                "stock_actual": it.stock_actual,
                "faltantes": abs(it.stock_actual) if it.stock_actual < 0 else 0,
            }
            for it in items
        ]
        total_faltantes = sum(i["faltantes"] for i in items_data)

    return {
        "cantidad": len(items_data),
        "items": items_data,
        "total_unidades_faltantes": total_faltantes,
    }


def obtener_pedidos_de_cliente(nombre_cliente: str) -> dict:
    """Busca pedidos por nombre de cliente (búsqueda parcial, case-insensitive).

    Ej: "coca-cola" encuentra "Coca-Cola - Evento Verano".
    Ej: "globant" encuentra "Globant - Welcome Kit".

    Args:
        nombre_cliente: Texto a buscar dentro del nombre del cliente.

    Returns:
        dict con:
          - "encontrados": int (cuántos pedidos del cliente)
          - "pedidos": lista de pedidos ordenados por fecha descendente
          - "total_unidades": int (suma de cantidades pedidas)
          - "clientes_distintos": lista de nombres únicos que matchearon
    """
    with get_session() as session:
        pedidos = (
            session.query(Pedido)
            .filter(Pedido.cliente.ilike(f"%{nombre_cliente}%"))
            .order_by(Pedido.fecha.desc())
            .all()
        )
        pedidos_data = [
            {
                "fecha": p.fecha.isoformat() if p.fecha else None,
                "cliente": p.cliente,
                "sku": p.sku,
                "producto": p.producto,
                "cantidad": p.cantidad,
            }
            for p in pedidos
        ]
        total = sum(p["cantidad"] for p in pedidos_data)
        clientes = sorted({p["cliente"] for p in pedidos_data})

    return {
        "encontrados": len(pedidos_data),
        "pedidos": pedidos_data,
        "total_unidades": total,
        "clientes_distintos": clientes,
    }


def listar_pedidos_recientes(cantidad: int = 10) -> dict:
    """Lista los últimos N pedidos por fecha.

    Útil cuando preguntan "qué pedidos hubo últimamente", "qué se vendió",
    "últimos pedidos".

    Args:
        cantidad: Cuántos pedidos devolver (default 10, máximo 50).

    Returns:
        dict con la lista de pedidos ordenados por fecha descendente.
    """
    cantidad = max(1, min(cantidad, 50))  # clamp 1..50
    with get_session() as session:
        pedidos = (
            session.query(Pedido)
            .order_by(Pedido.fecha.desc())
            .limit(cantidad)
            .all()
        )
        pedidos_data = [
            {
                "fecha": p.fecha.isoformat() if p.fecha else None,
                "cliente": p.cliente,
                "sku": p.sku,
                "producto": p.producto,
                "cantidad": p.cantidad,
            }
            for p in pedidos
        ]

    return {
        "cantidad": len(pedidos_data),
        "pedidos": pedidos_data,
    }


def obtener_resumen_ejecutivo() -> dict:
    """Devuelve métricas agregadas de stock y pedidos.

    Útil cuando preguntan "dame un resumen", "cómo estamos", "qué tal el stock",
    "cuántos pedidos hubo en total".

    Returns:
        dict con totales, conteos, top cliente y top producto.
    """
    with get_session() as session:
        total_skus = session.query(StockItem).count()
        skus_comprar = (
            session.query(StockItem)
            .filter(StockItem.estado == "COMPRAR")
            .count()
        )
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
            {"nombre": top_cliente_row.cliente, "unidades": top_cliente_row.total}
            if top_cliente_row else None
        )

        top_sku_row = (
            session.query(Pedido.producto, func.sum(Pedido.cantidad).label("total"))
            .group_by(Pedido.producto)
            .order_by(func.sum(Pedido.cantidad).desc())
            .first()
        )
        top_producto = (
            {"descripcion": top_sku_row.producto, "unidades": top_sku_row.total}
            if top_sku_row else None
        )

    return {
        "total_skus": total_skus,
        "skus_ok": total_skus - skus_comprar,
        "skus_a_comprar": skus_comprar,
        "unidades_totales_en_stock": int(unidades_totales),
        "total_pedidos": total_pedidos,
        "unidades_vendidas": int(unidades_vendidas),
        "clientes_distintos": clientes_distintos,
        "top_cliente": top_cliente,
        "top_producto": top_producto,
    }


def listar_categorias_disponibles() -> dict:
    """Lista todas las categorías de productos y modelos que existen en el stock.

    Útil cuando el usuario pregunta "qué productos tenés", "qué hay disponible",
    "qué categorías manejás". El LLM puede usar esto para sugerirle al usuario
    qué tipos de cosas puede consultar.

    Returns:
        dict con la lista de productos distintos y modelos asociados.
    """
    with get_session() as session:
        # Productos distintos con cantidad de variantes
        rows = (
            session.query(
                StockItem.producto,
                StockItem.modelo,
                func.count(StockItem.id).label("variantes"),
            )
            .group_by(StockItem.producto, StockItem.modelo)
            .order_by(StockItem.producto, StockItem.modelo)
            .all()
        )
        agrupado: dict[str, list[dict]] = {}
        for r in rows:
            agrupado.setdefault(r.producto, []).append({
                "modelo": r.modelo,
                "variantes": r.variantes,
            })

    return {
        "productos": [
            {"producto": prod, "modelos": modelos}
            for prod, modelos in agrupado.items()
        ]
    }


# ---------------------------------------------------------------------------
# Mapeo nombre -> función (para que el bot pueda ejecutar dinámicamente)
# ---------------------------------------------------------------------------

TOOLS_MAP = {
    "buscar_stock": buscar_stock,
    "listar_productos_a_comprar": listar_productos_a_comprar,
    "obtener_pedidos_de_cliente": obtener_pedidos_de_cliente,
    "listar_pedidos_recientes": listar_pedidos_recientes,
    "obtener_resumen_ejecutivo": obtener_resumen_ejecutivo,
    "listar_categorias_disponibles": listar_categorias_disponibles,
}


def ejecutar_tool(nombre: str, args: dict) -> dict:
    """Ejecuta una tool por nombre con los args que mandó Gemini.

    Si el nombre no existe o falla la ejecución, devuelve un dict con error
    en vez de lanzar excepción — así Gemini puede leer el error y decidir
    qué hacer (ej. avisar al usuario).
    """
    fn = TOOLS_MAP.get(nombre)
    if fn is None:
        return {"error": f"Tool '{nombre}' no existe."}
    try:
        return fn(**(args or {}))
    except TypeError as e:
        # Args inválidos (ej. parámetro de más, o tipo incorrecto)
        return {"error": f"Args inválidos para '{nombre}': {e}"}
    except Exception as e:
        return {"error": f"Error ejecutando '{nombre}': {type(e).__name__}: {e}"}
