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
from dataclasses import dataclass, field
from typing import Optional

from google import genai
from google.genai import types as genai_types

from merchbot.config import settings
from merchbot.core.horario import Momento, resolver_momento
from merchbot.core.memory import (
    ConversationStore,
    InMemoryConversationStore,
    Turno,
    UserId,
)
from merchbot.core.tools import ejecutar_tool

__all__ = ["MerchBot", "Respuesta", "Turno", "UserId", "SYSTEM_INSTRUCTION"]


logger = logging.getLogger(__name__)


@dataclass
class Respuesta:
    """Resultado de una consulta al asistente."""
    texto: str
    herramientas: list[str] = field(default_factory=list)  # funciones que llamó el modelo
    completa: bool = True   # False si se cayó a un mensaje de respaldo
    fuentes: list[str] = field(default_factory=list)   # secciones de políticas consultadas (RAG)


# ---------------------------------------------------------------------------
# Prompt de sistema (mucho más corto que en v1)
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTION = """Sos un asistente de gestión de stock para una empresa argentina de merchandising sublimado.
La empresa compra productos base (remeras, buzos, gorras, tazas, etc.) y los personaliza con logos de clientes.
Usuarios: encargado de depósito, dueño/gerente y vendedores. Atendés las 24 horas.

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
- El usuario cuenta un problema (prenda fallada, pedido demorado o equivocado, faltante) → registrar_reclamo.
  Si falta información clave (qué pasó), preguntala antes de registrar. Confirmá con el número de reclamo.
- "¿cómo va mi reclamo 12?" → consultar_estado_reclamo(numero=12)
- Preguntas de procedimientos y condiciones (plazos de entrega, pedido mínimo, cómo hacer un pedido,
  cambios y devoluciones, guía de talles y medidas, envíos, formatos del logo, cuidado de prendas,
  muestras, horarios) → consultar_politicas(pregunta="...").
  Respondé SOLO con lo que dicen los fragmentos devueltos y nombrá la sección ("según Plazos de entrega...").
  Si no devuelve fragmentos, decí que no tenés esa información y que lo puede consultar con el equipo.
  Nunca inventes plazos, mínimos ni condiciones.

PODÉS ENCADENAR HERRAMIENTAS si la pregunta lo amerita.
Ej: "necesito 200 buzos grises L para Coca-Cola, ¿alcanzo?" →
    1. buscar_stock(producto="Buzo", color="Gris", talle="L")
    2. (si no alcanza) buscar_stock(producto="Buzo", color="Gris") para sugerir alternativas
Ej: "¿cuánto tardan 150 remeras blancas M?" → buscar_stock(...) y consultar_politicas(pregunta="plazo de producción 150 unidades")

REGLAS DE RESPUESTA:
1. Respondés en español rioplatense, breve y operativo (sin saludos largos).
2. Formato compacto para listas: "• Producto Modelo Color Talle — stock X" (un ítem por línea).
3. Si una herramienta devolvió 0 resultados, decílo claro y sugerí alternativas si tiene sentido.
4. Si una herramienta devolvió un error, avisá al usuario sin inventar datos.
5. No hablés de las herramientas en tu respuesta — el usuario no las ve, le hablás como un asistente humano.
6. Máximo 1 emoji por respuesta (⚠️ para stock crítico, ✅ para confirmación, sino ninguno).
7. No manejás precios — si te preguntan, decí "no manejo precios, solo stock".
8. Si la pregunta no es de stock, pedidos o reclamos, redirigí: "Solo puedo ayudarte con stock, pedidos y reclamos."
9. Al registrar un reclamo, decí el número y qué pasa después (lo revisa una persona; si es fuera de horario, el próximo día hábil).
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
        genai_types.FunctionDeclaration(
            name="registrar_reclamo",
            description=(
                "Registra un reclamo del usuario y devuelve el número asignado. Usala "
                "cuando el usuario informa un problema con un producto o un pedido."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "descripcion": {
                        "type": "string",
                        "description": "Qué pasó, en palabras claras y completas (ej. 'Llegaron 20 remeras blancas M con manchas de tinta').",
                    },
                    "tipo": {
                        "type": "string",
                        "enum": ["producto_defectuoso", "demora", "error_en_pedido", "faltante", "otro"],
                        "description": "Categoría del reclamo.",
                    },
                    "cliente": {
                        "type": "string",
                        "description": "Cliente o pedido involucrado, si se mencionó.",
                    },
                },
                "required": ["descripcion", "tipo"],
            },
        ),
        genai_types.FunctionDeclaration(
            name="consultar_estado_reclamo",
            description="Devuelve el estado de un reclamo a partir de su número.",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "numero": {"type": "integer", "description": "Número de reclamo."},
                },
                "required": ["numero"],
            },
        ),
        genai_types.FunctionDeclaration(
            name="consultar_politicas",
            description=(
                "Busca en el documento de políticas de la empresa (plazos, pedido mínimo, cómo pedir, "
                "cambios y devoluciones, talles, envíos, archivos de diseño, cuidado, muestras, horarios) "
                "y devuelve los fragmentos más relevantes. Usala para cualquier pregunta de procedimientos."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "pregunta": {
                        "type": "string",
                        "description": "La pregunta del usuario, reformulada en forma completa si hace falta.",
                    },
                },
                "required": ["pregunta"],
            },
        ),
    ]


# Instancia única de las tools para Gemini.
_TOOLS = [genai_types.Tool(function_declarations=_build_function_declarations())]


# ---------------------------------------------------------------------------
# Datos de turno (memoria conversacional)
# ---------------------------------------------------------------------------

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
        store: Optional[ConversationStore] = None,
    ) -> None:
        self.modelo = modelo or settings.gemini_model
        self.client = genai.Client(api_key=api_key or settings.gemini_api_key)
        self.memoria: ConversationStore = store or InMemoryConversationStore(
            max_turnos=self.HISTORIAL_MAX_TURNOS
        )

    # ---- Conversación con Gemini + function calling ----------------------

    def _build_initial_contents(
        self, user_id: UserId, query: str
    ) -> list[genai_types.Content]:
        """Arma el historial conversacional + nueva pregunta."""
        contenidos: list[genai_types.Content] = []
        for turno in self.memoria.history(user_id):
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

    def ask(self, user_id: UserId, query: str) -> str:
        """Atajo que devuelve solo el texto de la respuesta."""
        return self.responder(user_id, query).texto

    def responder(
        self,
        user_id: UserId,
        query: str,
        momento: Optional[Momento] = None,
        canal: str = "desconocido",
    ) -> Respuesta:
        """Pregunta principal con loop de function calling.

        `momento` es la hora (real o simulada) de la consulta: se le informa al
        modelo para que sepa si es fuera de horario. `canal` y la hora se pasan
        como contexto a las funciones que lo necesitan (registrar_reclamo).

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
            return Respuesta("Decime una consulta. Ej: '¿cuántas remeras negras M tengo?', "
                             "'qué pidió Coca-Cola', 'qué hay que comprar'.")

        momento = momento or resolver_momento()
        instrucciones = f"{SYSTEM_INSTRUCTION}\n{momento.contexto_para_el_modelo()}"
        contexto_tools = {"canal": canal, "user_id": str(user_id), "hora": momento.hora}
        herramientas: list[str] = []
        fuentes: list[str] = []

        contents = self._build_initial_contents(user_id, query)
        had_tool_calls = False       # algún turno previo pidió tools
        nudge_intentado = False      # ya le dimos el "articulá la respuesta"

        for iteration in range(self.MAX_FUNCTION_CALL_ITERATIONS):
            response = self.client.models.generate_content(
                model=self.modelo,
                contents=contents,
                config=genai_types.GenerateContentConfig(
                    system_instruction=instrucciones,
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
                    herramientas.append(fc.name)
                    result = ejecutar_tool(fc.name, args, contexto_tools)
                    if fc.name == "consultar_politicas" and isinstance(result, dict):
                        for frag in result.get("fragmentos", []):
                            if frag.get("seccion") and frag["seccion"] not in fuentes:
                                fuentes.append(frag["seccion"])
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
                self.memoria.append(user_id, "user", query, hora=momento.hora)
                self.memoria.append(user_id, "model", respuesta, hora=momento.hora)
                return Respuesta(respuesta, herramientas, fuentes=fuentes)

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
            return Respuesta(
                "No pude armar una respuesta esta vez. Probá reformulando "
                "(por ejemplo, sin signos de puntuación pegados a la consulta, "
                "o agregando más contexto).",
                herramientas,
                completa=False,
            )

        # Excedimos el máximo de iteraciones.
        logger.warning(
            "Excedido MAX_FUNCTION_CALL_ITERATIONS (%d) para user %s, query=%r",
            self.MAX_FUNCTION_CALL_ITERATIONS, user_id, query,
        )
        return Respuesta(
            "Tu consulta requirió más pasos de los esperados. "
            "Probá dividirla en preguntas más simples.",
            herramientas,
            completa=False,
        )

    def clear_memory(self, user_id: UserId) -> int:
        return self.memoria.clear(user_id)
