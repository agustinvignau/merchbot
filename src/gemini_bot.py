"""MerchBot: asistente conversacional de stock, ahora con FUNCTION CALLING.

Cambio mayor respecto a v1:
- Ya NO inyectamos el catálogo completo en el prompt.
- En vez de eso, exponemos funciones (src/tools.py) que Gemini puede llamar.
- Cuando llega una pregunta, Gemini decide qué función(es) llamar, nuestro
  código las ejecuta contra la DB, le devuelve los resultados, y Gemini arma
  la respuesta natural.

Por qué importa:
- Casi cero alucinación en datos: los números vienen de SQL, no de "leer texto".
- Escala a 10.000+ SKUs sin tocar nada (el prompt ya no crece con el catálogo).
- Gemini puede encadenar tools (ej: buscar stock + buscar pedidos del cliente
  en la misma respuesta).
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

from google import genai
from google.genai import types as genai_types
from sqlalchemy import func

from src.config import settings
from src.database import get_session
from src.models import StockItem, Pedido
from src.tools import ejecutar_tool


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt de sistema (mucho más corto que en v1)
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTION = """Sos un asistente de gestión de stock para una empresa argentina de merchandising sublimado.
La empresa compra productos base (remeras, buzos, gorras, tazas, etc.) y los personaliza con logos de clientes.
Usuarios: encargado de depósito y dueño/gerente.

CÓMO TRABAJÁS:
Cuando el usuario te pregunta algo, USÁS LAS HERRAMIENTAS (functions) disponibles para consultar la base de datos.
NO inventes datos: si necesitás información, llamá a la herramienta apropiada.

GUÍA DE QUÉ HERRAMIENTA USAR:
- Consultas tipo "¿cuántas remeras negras M?" → buscar_stock(producto="Remera", color="Negro", talle="M")
- "¿qué hay para comprar?" / "qué falta" / "qué está en rojo" → listar_productos_a_comprar
- "¿qué pidió Coca-Cola?" / "pedidos de X" → obtener_pedidos_de_cliente(nombre_cliente="Coca-Cola")
- "últimos pedidos" / "qué se vendió" → listar_pedidos_recientes
- "dame un resumen" / "cómo estamos" → obtener_resumen_ejecutivo
- "¿qué productos manejás?" / "qué categorías hay" → listar_categorias_disponibles

PODÉS ENCADENAR HERRAMIENTAS si la pregunta lo amerita.
Ej: "necesito 200 buzos grises L para Coca-Cola, ¿alcanzo?" →
    1. buscar_stock(producto="Buzo", color="Gris", talle="L")
    2. (si no alcanza) buscar_stock(producto="Buzo", color="Gris") para sugerir alternativas

REGLAS DE RESPUESTA:
1. Respondés en español rioplatense, breve y operativo (sin saludos largos).
2. Formato compacto para listas: "• Producto Modelo Color Talle — stock X" (un ítem por línea).
3. Si una herramienta devolvió 0 resultados, decílo claro y sugerí alternativas si tiene sentido.
4. Si una herramienta devolvió un error, avisá al usuario sin inventar datos.
5. No hablés de las herramientas en tu respuesta — el usuario no las ve, le hablás como un asistente humano.
6. Máximo 1 emoji por respuesta (⚠️ para stock crítico, ✅ para confirmación, sino ninguno).
7. No manejás precios — si te preguntan, decí "no manejo precios, solo stock".
8. Si la pregunta no es de stock o pedidos, redirigí: "Solo puedo ayudarte con consultas de stock o pedidos."
"""


# ---------------------------------------------------------------------------
# Function declarations: lo que Gemini sabe que puede llamar
# ---------------------------------------------------------------------------

def _build_function_declarations() -> list[genai_types.FunctionDeclaration]:
    """Construye las declarations a partir de las tools.

    Cada declaration: nombre + descripción + JSON schema de parámetros.
    Gemini lee esto y decide cuál llamar y con qué args.
    """
    return [
        genai_types.FunctionDeclaration(
            name="buscar_stock",
            description=(
                "Busca productos en stock filtrando por atributos. Todos los filtros "
                "son opcionales y se combinan con AND. Devuelve los SKUs que matchean "
                "con su stock actual y estado."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "producto": {
                        "type": "string",
                        "description": "Categoría base. Ej: 'Remera', 'Buzo', 'Gorra', 'Taza', 'Chomba', 'Campera', 'Llavero'.",
                    },
                    "modelo": {
                        "type": "string",
                        "description": "Tipo dentro de la categoría. Ej: 'Cuello Redondo', 'Dry-Fit', 'Canguro', 'Con Cierre', 'Piqué', 'Con Respiración'.",
                    },
                    "color": {
                        "type": "string",
                        "description": "Color del producto. Ej: 'Negro', 'Blanco', 'Gris', 'Rojo', 'Azul'.",
                    },
                    "talle": {
                        "type": "string",
                        "description": "Talle. Para indumentaria: 'S', 'M', 'L', 'XL'. Para productos sin talle: 'Único'.",
                    },
                },
            },
        ),
        genai_types.FunctionDeclaration(
            name="listar_productos_a_comprar",
            description=(
                "Lista todos los productos con estado COMPRAR (stock <= 0, es decir "
                "los que están en rojo en el sistema). Ordenados por urgencia (los "
                "más negativos primero)."
            ),
            parameters_json_schema={"type": "object", "properties": {}},
        ),
        genai_types.FunctionDeclaration(
            name="obtener_pedidos_de_cliente",
            description=(
                "Busca todos los pedidos de un cliente (búsqueda parcial por nombre). "
                "Ej: 'Coca' encuentra 'Coca-Cola - Evento Verano'."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "nombre_cliente": {
                        "type": "string",
                        "description": "Texto a buscar dentro del nombre del cliente (case-insensitive, parcial).",
                    },
                },
                "required": ["nombre_cliente"],
            },
        ),
        genai_types.FunctionDeclaration(
            name="listar_pedidos_recientes",
            description=(
                "Lista los últimos N pedidos ordenados por fecha descendente. "
                "Útil para 'qué se vendió últimamente', 'últimos pedidos'."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "cantidad": {
                        "type": "integer",
                        "description": "Cuántos pedidos devolver. Default 10, máximo 50.",
                    },
                },
            },
        ),
        genai_types.FunctionDeclaration(
            name="obtener_resumen_ejecutivo",
            description=(
                "Devuelve métricas agregadas de stock y pedidos: total SKUs, cuántos "
                "OK, cuántos a comprar, unidades en stock, total pedidos, top cliente, "
                "top producto, clientes distintos."
            ),
            parameters_json_schema={"type": "object", "properties": {}},
        ),
        genai_types.FunctionDeclaration(
            name="listar_categorias_disponibles",
            description=(
                "Lista todas las categorías de productos y modelos disponibles en el "
                "stock. Útil cuando el usuario pregunta '¿qué productos manejás?'."
            ),
            parameters_json_schema={"type": "object", "properties": {}},
        ),
    ]


# Instancia única de las tools para Gemini.
_TOOLS = [genai_types.Tool(function_declarations=_build_function_declarations())]


# ---------------------------------------------------------------------------
# Datos de turno (memoria conversacional)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Turno:
    role: str   # "user" o "model"
    text: str


# ---------------------------------------------------------------------------
# Formateadores para los comandos atajo del bot Telegram
# (estos NO usan IA, leen directo de la DB)
# ---------------------------------------------------------------------------

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
# MerchBot
# ---------------------------------------------------------------------------

class MerchBot:
    """Asistente conversacional con function calling.

    Flujo de ask():
    1. Mandamos a Gemini: historial conversacional + nueva pregunta + tools disponibles.
    2. Gemini puede:
       a. Devolver texto (respuesta final, terminamos).
       b. Pedir llamar a una o más tools.
    3. Si pidió tools: las ejecutamos, agregamos los resultados al historial, y volvemos al paso 1.
    4. Hay un límite de iteraciones para evitar loops infinitos.
    """

    HISTORIAL_MAX_TURNOS = 10
    MAX_FUNCTION_CALL_ITERATIONS = 5

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

    # ---- Comandos atajo del bot Telegram (no usan IA) --------------------

    def get_productos_a_comprar(self) -> list[dict]:
        """Productos con estado COMPRAR. Ordenados por urgencia."""
        with get_session() as session:
            items = (
                session.query(StockItem)
                .filter(StockItem.estado == "COMPRAR")
                .order_by(StockItem.stock_actual.asc())
                .all()
            )
            return [it.to_dict() for it in items]

    def get_resumen_ejecutivo(self) -> dict:
        """Métricas agregadas para el comando /resumen."""
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

    # ---- Conversación con Gemini + function calling ----------------------

    def _build_initial_contents(
        self, user_id: int, query: str
    ) -> list[genai_types.Content]:
        """Arma el historial conversacional + nueva pregunta."""
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

    @staticmethod
    def _finish_reason_str(response) -> str:
        """Extrae el finish_reason de un response de forma segura para logging."""
        try:
            return str(response.candidates[0].finish_reason)
        except (AttributeError, IndexError):
            return "?"

    def ask(self, user_id: int, query: str) -> str:
        """Pregunta principal con loop de function calling.

        Flujo:
        - Iteramos mandando contents + tools a Gemini.
        - Si Gemini pide function calls: las ejecutamos, agregamos resultados, loopeamos.
        - Si Gemini devuelve texto: lo guardamos en memoria y lo retornamos.
        - Si Gemini devuelve texto VACÍO post-tool-calls: le damos UNA iteración extra
          con un nudge ("articulá la respuesta") antes de caer al fallback. Esto
          atrapa casos donde el modelo se "queda mudo" tras una tool que no devolvió
          resultados (típico con queries ambiguas, ej. "talle m?" en vez de "talle M").
        """
        if not query or not query.strip():
            return ("Decime una consulta. Ej: '¿cuántas remeras negras M tengo?', "
                    "'qué pidió Coca-Cola', 'qué hay que comprar'.")

        contents = self._build_initial_contents(user_id, query)
        had_tool_calls = False       # algún turno previo pidió tools
        nudge_intentado = False      # ya le dimos el "articulá la respuesta"

        for iteration in range(self.MAX_FUNCTION_CALL_ITERATIONS):
            response = self.client.models.generate_content(
                model=self.modelo,
                contents=contents,
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    tools=_TOOLS,
                    temperature=0.3,
                    max_output_tokens=2048,
                ),
            )

            function_calls = response.function_calls or []

            if function_calls:
                had_tool_calls = True
                logger.info(
                    "Iter %d: Gemini pidió %d function call(s): %s",
                    iteration + 1, len(function_calls),
                    [fc.name for fc in function_calls],
                )

                contents.append(response.candidates[0].content)
                tool_response_parts = []
                for fc in function_calls:
                    args = dict(fc.args) if fc.args else {}
                    result = ejecutar_tool(fc.name, args)
                    # Loguear args + resumen del resultado para diagnóstico
                    resumen_result = (
                        f"keys={list(result.keys())[:4]}"
                        if isinstance(result, dict) else type(result).__name__
                    )
                    logger.info(
                        "  -> %s(%r) → %s", fc.name, args, resumen_result,
                    )
                    tool_response_parts.append(
                        genai_types.Part.from_function_response(
                            name=fc.name,
                            response=result,
                        )
                    )
                contents.append(genai_types.Content(
                    role="user",
                    parts=tool_response_parts,
                ))
                continue

            # Sin function calls: Gemini debería estar devolviendo texto final.
            respuesta = (response.text or "").strip()

            if respuesta:
                self._memoria[user_id].append(Turno(role="user", text=query))
                self._memoria[user_id].append(Turno(role="model", text=respuesta))
                return respuesta

            # ★ Texto VACÍO sin function calls.
            # Loguear con detalle para entender qué pasó (mejora B).
            logger.warning(
                "Iter %d: respuesta vacía. finish_reason=%s had_tool_calls=%s "
                "nudge_intentado=%s query=%r",
                iteration + 1, self._finish_reason_str(response),
                had_tool_calls, nudge_intentado, query,
            )

            # Si hubo tool calls antes pero el modelo se "quedó mudo", darle
            # UNA chance más con un nudge (mejora A). Si ya lo intentamos o
            # nunca hubo tools, cortamos al fallback.
            if had_tool_calls and not nudge_intentado:
                nudge_intentado = True
                contents.append(genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text=(
                        "Por favor articulá la respuesta para el usuario usando los "
                        "datos que ya consultaste. Si las herramientas no devolvieron "
                        "resultados, decílo claramente y sugerí alternativas."
                    ))],
                ))
                continue

            # Fallback honesto. NO se guarda en memoria (distorsionaría el contexto).
            return ("No pude armar una respuesta esta vez. Probá reformulando "
                    "(por ejemplo, sin signos de puntuación pegados a la consulta, "
                    "o agregando más contexto).")

        # Excedimos el máximo de iteraciones.
        logger.warning(
            "Excedido MAX_FUNCTION_CALL_ITERATIONS (%d) para user %s, query=%r",
            self.MAX_FUNCTION_CALL_ITERATIONS, user_id, query,
        )
        return ("Tu consulta requirió más pasos de los esperados. "
                "Probá dividirla en preguntas más simples.")

    def clear_memory(self, user_id: int) -> int:
        n = len(self._memoria.get(user_id, []))
        self._memoria.pop(user_id, None)
        return n
