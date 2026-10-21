"""Formato de los mensajes de los atajos de Telegram (/comprar, /resumen).

No usan IA: reciben los dicts de `merchbot.core.reports` y devuelven texto.
"""
from __future__ import annotations


def format_comprar_message(productos: list[dict]) -> str:
    """Mensaje legible para el comando /comprar."""
    if not productos:
        return "✅ Stock OK, no hay nada para comprar."
    total_faltante = sum(abs(p["stock_actual"]) for p in productos if p["stock_actual"] < 0)
    lineas = [f"⚠️ {len(productos)} producto(s) por comprar:\n"]
    for p in productos:
        falta = abs(p["stock_actual"]) if p["stock_actual"] < 0 else 0
        sufijo = f" → faltan {falta}" if falta > 0 else ""
        lineas.append(
            f"• {p['descripcion']} ({p['sku']})\n"
            f"   stock actual: {p['stock_actual']}{sufijo}"
        )
    if total_faltante > 0:
        lineas.append(f"\n📦 Total a comprar: {total_faltante} unidades")
    return "\n".join(lineas)


def format_resumen_message(r: dict) -> str:
    """Mensaje legible para el comando /resumen."""
    lineas = [
        "📊 *Resumen ejecutivo*\n",
        f"• Total SKUs en stock: *{r['total_skus']}*",
        f"• SKUs en verde (OK): *{r['skus_ok']}*",
        f"• SKUs en rojo (comprar): *{r['skus_comprar']}*",
        f"• Unidades totales en stock: *{r['unidades_totales']:,}*".replace(",", "."),
        "",
        "📦 *Pedidos*",
        f"• Pedidos cargados: *{r['total_pedidos']}*",
        f"• Unidades vendidas: *{r['unidades_vendidas']:,}*".replace(",", "."),
        f"• Clientes distintos: *{r['clientes_distintos']}*",
    ]
    if r['top_cliente']:
        cliente, cantidad = r['top_cliente']
        lineas.append(
            f"• Top cliente: *{cliente}* "
            f"({cantidad:,} unidades)".replace(",", ".")
        )
    if r['top_producto']:
        producto, cantidad = r['top_producto']
        lineas.append(
            f"• Producto más pedido: *{producto}* "
            f"({cantidad:,} unidades)".replace(",", ".")
        )
    return "\n".join(lineas)
