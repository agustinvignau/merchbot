"""MerchBot: asistente conversacional de stock para empresa de merchandising.

Responsabilidades:
- Mantener una sesión conversacional por usuario (memoria de corto plazo).
- Inyectar el stock actual + pedidos recientes en el prompt de sistema.
- Llamar a Gemini y devolver una respuesta en lenguaje natural.
- Exponer helpers para alertas y resumen ejecutivo (sin pasar por LLM).
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional

from google import genai
from google.genai import types as genai_types
from sqlalchemy import func

from src.config import settings
from src.database import get_session
from src.models import StockItem, Pedido


# ---------------------------------------------------------------------------
# Prompt de sistema (adaptado a merchandising)
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTION_BASE = """Sos un asistente de gestión de stock para una empresa argentina de merchandising sublimado.
La empresa compra productos base (remeras, buzos, gorras, tazas, etc.) y los personaliza con logos de clientes.

Usuarios del bot: el encargado de depósito y el dueño de la empresa.

QUÉ TENÉS QUE PODER HACER:
1. Responder consultas de stock por combinación de atributos:
   - "¿cuántas remeras negras M tengo?" → buscás producto=Remera, color=Negro, talle=M
   - "¿qué tengo en gorras?" → listás todas las variantes de Gorra
2. Listar lo que hay que comprar: productos con stock ≤ 0 (Estado = COMPRAR)
3. Responder consultas sobre pedidos recientes:
   - "¿qué pidió Coca-Cola?" → buscás en los pedidos por cliente
   - "¿cuántas tazas se vendieron?" → sumás cantidades por producto
4. Recomendar alternativas cuando no hay stock exacto:
   - "necesito 200 buzos grises L" → si no llegás, sugerís variantes cercanas (otro color/talle)

REGLAS ESTRICTAS:
1. Respondés SIEMPRE en español rioplatense, breve y operativo (sin adornos, sin saludos largos).
2. Solo usás información del STOCK ACTUAL y PEDIDOS RECIENTES que te paso abajo. NUNCA inventes SKUs, clientes ni cantidades.
3. Si el producto/variante no existe, decílo claro y sugerí 1-2 alternativas similares (mismo producto, otro color o talle).
4. Cuando muestres varios productos, usá listas con viñetas (•) y formato compacto: "Producto Modelo Color Talle — stock X".
5. Si hay productos en COMPRAR, mencionálos siempre que sean relevantes a la consulta.
6. Si te preguntan por valores monetarios, aclará: "no manejo precios, solo stock".
7. Si la pregunta no tiene que ver con stock o pedidos, redirigí: "Solo puedo ayudarte con consultas de stock o pedidos."
8. Sin emojis innecesarios — máximo 1 por respuesta, y solo si suma información (⚠️ para stock crítico, ✅ para confirmación).
"""


# ---------------------------------------------------------------------------
# Helpers de formato
# ---------------------------------------------------------------------------

def format_stock_for_prompt(items: Iterable[StockItem]) -> str:
    """Formatea el stock como tabla compacta para inyectar en el prompt."""
    lineas = ["SKU | Producto | Modelo | Color | Talle | Stock | Estado"]
    for it in items:
        lineas.append(
            f"{it.sku} | {it.producto} | {it.modelo} | {it.color} | "
            f"{it.talle} | {it.stock_actual} | {it.estado}"
        )
    return "\n".join(lineas)


def format_pedidos_for_prompt(pedidos: Iterable[Pedido]) -> str:
    """Formatea los pedidos recientes como tabla compacta."""
    lineas = ["Fecha | Cliente | SKU | Cantidad"]
    for p in pedidos:
        fecha = p.fecha.isoformat() if p.fecha else "?"
        lineas.append(f"{fecha} | {p.cliente} | {p.sku} | {p.cantidad}")
    return "\n".join(lineas)


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
        f"📦 *Pedidos*",
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


# ---------------------------------------------------------------------------
# Datos de turno
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Turno:
    role: str   # "user" o "model"
    text: str


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class MerchBot:
    """Asistente conversacional de stock para merchandising."""

    HISTORIAL_MAX_TURNOS = 10

    # Cuántos pedidos recientes inyectar en el contexto (para no inflar el prompt)
    PEDIDOS_EN_CONTEXTO = 25

    def __init__(
        self,
        api_key: Optional[str] = None,
        modelo: Optional[str] = None,
    ) -> None:
        self.modelo = modelo or settings.gemini_model
        self.client = genai.Client(api_key=api_key or settings.gemini_api_key)
        self._memoria: dict[int, deque[Turno]] = defaultdict(
            lambda: deque(maxlen=self.HISTORIAL_MAX_TURNOS)
        )

    # ---- DB helpers (no usan Gemini, atajos rápidos) ---------------------

    def _snapshot_stock(self) -> str:
        with get_session() as session:
            items = (
                session.query(StockItem)
                .order_by(StockItem.producto, StockItem.modelo,
                          StockItem.color, StockItem.talle)
                .all()
            )
            return format_stock_for_prompt(items)

    def _snapshot_pedidos_recientes(self) -> str:
        with get_session() as session:
            pedidos = (
                session.query(Pedido)
                .order_by(Pedido.fecha.desc())
                .limit(self.PEDIDOS_EN_CONTEXTO)
                .all()
            )
            return format_pedidos_for_prompt(pedidos)

    def get_productos_a_comprar(self) -> list[dict]:
        """Productos con estado COMPRAR (stock <= 0). Ordenados por urgencia."""
        with get_session() as session:
            items = (
                session.query(StockItem)
                .filter(StockItem.estado == "COMPRAR")
                .order_by(StockItem.stock_actual.asc())
                .all()
            )
            return [it.to_dict() for it in items]

    def get_resumen_ejecutivo(self) -> dict:
        """Métricas agregadas para el dueño / encargado."""
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
                .scalar()
                or 0
            )

            total_pedidos = session.query(Pedido).count()
            unidades_vendidas = (
                session.query(func.sum(Pedido.cantidad)).scalar() or 0
            )
            clientes_distintos = (
                session.query(Pedido.cliente).distinct().count()
            )

            # Top cliente por unidades pedidas
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

            # Producto más pedido (por SKU, mostrando descripción si la encontramos)
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

    # ---- Conversación con Gemini -----------------------------------------

    def _build_contents(self, user_id: int, query: str) -> list[genai_types.Content]:
        contenidos: list[genai_types.Content] = []
        for turno in self._memoria[user_id]:
            contenidos.append(
                genai_types.Content(
                    role=turno.role,
                    parts=[genai_types.Part(text=turno.text)],
                )
            )
        contenidos.append(
            genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=query)],
            )
        )
        return contenidos

    def ask(self, user_id: int, query: str) -> str:
        if not query or not query.strip():
            return ("Decime una consulta. Ej: '¿cuántas remeras negras M tengo?', "
                    "'qué pidió Coca-Cola', 'qué hay que comprar'.")

        system = (
            SYSTEM_INSTRUCTION_BASE
            + "\n\nSTOCK ACTUAL:\n" + self._snapshot_stock()
            + "\n\nPEDIDOS RECIENTES (últimos " + str(self.PEDIDOS_EN_CONTEXTO) + "):\n"
            + self._snapshot_pedidos_recientes()
        )

        response = self.client.models.generate_content(
            model=self.modelo,
            contents=self._build_contents(user_id, query),
            config=genai_types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.3,            # más bajo: respuestas más operativas
                max_output_tokens=2048,
            ),
        )

        respuesta = (response.text or "").strip()

        finish_reason = None
        try:
            finish_reason = response.candidates[0].finish_reason
        except (AttributeError, IndexError):
            pass

        if not respuesta:
            respuesta = "No pude generar respuesta esta vez. Probá reformulando."
        elif finish_reason and str(finish_reason).endswith("MAX_TOKENS"):
            respuesta += "\n\n_(Respuesta cortada — pedí menos productos o más específico.)_"

        self._memoria[user_id].append(Turno(role="user", text=query))
        self._memoria[user_id].append(Turno(role="model", text=respuesta))

        return respuesta

    def clear_memory(self, user_id: int) -> int:
        n = len(self._memoria.get(user_id, []))
        self._memoria.pop(user_id, None)
        return n
