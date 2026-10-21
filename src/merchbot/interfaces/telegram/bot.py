"""Bot de Telegram para MerchBot.

Comandos:
    /start    - bienvenida
    /help     - lista de comandos
    /whoami   - muestra tu ID de Telegram (público, sirve para que el dueño te autorice)
    /sync     - fuerza una sincronización con Google Sheets
    /comprar  - lista productos en rojo (stock <= 0)
    /resumen  - resumen ejecutivo
    /clear    - borra el historial de la conversación
    /reclamo  - registra un reclamo (/reclamo llegaron 10 gorras rotas)

Mensajes de texto libre se procesan con ChatService (Gemini + function calling).

SEGURIDAD: por defecto solo responden a usuarios en TELEGRAM_ALLOWED_USER_IDS.
"""
from __future__ import annotations

import asyncio
import functools
import logging
from typing import Awaitable, Callable, Optional

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from merchbot.config import settings
from merchbot.core.chat_service import ChatService, get_chat_service
from merchbot.core.errores import describir_error
from merchbot.data.refresh import actualizar_datos
from merchbot.interfaces.telegram.formatters import (
    format_comprar_message,
    format_resumen_message,
)
from merchbot.security.rate_limiter import RateLimiter


logger = logging.getLogger(__name__)

TELEGRAM_MAX_MSG_LEN = 4000


def _service() -> ChatService:
    """Toda la lógica pasa por ChatService (compartido con la interfaz web)."""
    return get_chat_service()


# Rate limiter compartido para usuarios NO autorizados.
# Configurado con los valores del .env. Se instancia una vez al importar.
unauth_rate_limiter = RateLimiter(
    max_attempts=settings.unauth_max_attempts,
    window_minutes=settings.unauth_window_minutes,
)


# ---------------------------------------------------------------------------
# Autorización
# ---------------------------------------------------------------------------

HandlerFn = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def es_usuario_autorizado(user_id: int) -> bool:
    """True si el user_id puede usar el bot.

    Si la whitelist está vacía -> modo abierto (cualquiera puede usar).
    Útil para desarrollo, NUNCA en producción real.
    """
    allowed = settings.allowed_user_ids_set
    if not allowed:
        return True
    return user_id in allowed


def requires_auth(handler: HandlerFn) -> HandlerFn:
    """Decorator que rechaza el mensaje si el user_id no está en la whitelist.

    Aplica rate limiting al rechazo: los primeros N intentos por ventana
    reciben el mensaje educado de "no autorizado"; a partir de ahí, el bot
    silencia las respuestas (sigue logueando como WARNING).

    Esto protege la cuota de envío de Telegram y la CPU del bot contra spam.
    """
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None:
            return  # update raro, ignoramos

        if es_usuario_autorizado(user.id):
            # Si un usuario autorizado tenía rechazos previos, los limpiamos.
            unauth_rate_limiter.reset(user.id)
            await handler(update, context)
            return

        # ----- Usuario NO autorizado -----
        text_sample = (getattr(update.message, "text", "") or "")[:40]

        if unauth_rate_limiter.should_respond(user.id):
            unauth_rate_limiter.register_attempt(user.id)
            logger.warning(
                "ACCESO DENEGADO: user_id=%s username=%s name=%s msg=%r",
                user.id, user.username, user.full_name, text_sample,
            )
            await update.message.reply_text(
                "🔒 No estás autorizado a usar este bot.\n\n"
                "Si necesitás acceso, pasale al administrador tu ID:\n"
                f"`{user.id}`\n\n"
                "El administrador puede agregarlo a la whitelist.",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            # Silenciado: solo loguear, sin consumir cuota de envío.
            unauth_rate_limiter.register_attempt(user.id)
            count = unauth_rate_limiter.current_count(user.id)
            logger.warning(
                "SPAM SILENCIADO: user_id=%s username=%s intentos=%d msg=%r",
                user.id, user.username, count, text_sample,
            )
    return wrapper


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _chunk_message(texto: str, max_len: int = TELEGRAM_MAX_MSG_LEN) -> list[str]:
    """Parte un texto largo en chunks respetando el límite de Telegram."""
    if len(texto) <= max_len:
        return [texto]
    chunks, actual = [], ""
    for linea in texto.split("\n"):
        if len(actual) + len(linea) + 1 > max_len:
            chunks.append(actual)
            actual = linea
        else:
            actual = f"{actual}\n{linea}" if actual else linea
    if actual:
        chunks.append(actual)
    return chunks


async def _reply_largo(update: Update, texto: str,
                       parse_mode: Optional[str] = None) -> None:
    """Responde respetando el límite de longitud de Telegram."""
    for chunk in _chunk_message(texto):
        await update.message.reply_text(chunk, parse_mode=parse_mode)


# ---------------------------------------------------------------------------
# Mensajes estáticos
# ---------------------------------------------------------------------------

WELCOME = """Hola 👋 Soy el bot de stock de la empresa.

Puedo ayudarte con:
• Consultas: *"¿cuántas remeras negras M tengo?"*, *"¿qué pidió Coca-Cola?"*
• /comprar — productos que están en rojo (hay que comprar)
• /resumen — resumen ejecutivo del inventario
• /sync — recargar datos del Google Sheets ahora

Escribime tu consulta o usá /help para ver todos los comandos."""

HELP_TEXT = """Comandos disponibles:

/start    – Mensaje de bienvenida
/help     – Esta ayuda
/whoami   – Tu ID de Telegram (público, sirve para que te autoricen)
/sync     – Forzar sincronización con Google Sheets
/comprar  – Listar productos en rojo (stock <= 0)
/resumen  – Resumen ejecutivo (totales, top cliente, top producto)
/clear    – Borrar el historial de nuestra conversación
/reclamo  – Registrar un reclamo. Ej: /reclamo llegaron 10 gorras rotas
            (también podés contarlo en lenguaje natural)

Además podés escribirme cualquier consulta en lenguaje natural:
• "¿cuántas remeras negras M tengo?"
• "necesito 200 buzos grises L para un cliente"
• "qué pidió Movistar"
• "qué tengo en gorras"
"""


# ---------------------------------------------------------------------------
# Comandos públicos (no requieren auth — sirven para identificarse)
# ---------------------------------------------------------------------------

async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Devuelve el ID del usuario para que pueda pedir acceso."""
    user = update.effective_user
    autorizado = es_usuario_autorizado(user.id)
    estado = "✅ Autorizado" if autorizado else "🔒 NO autorizado"
    msg = (
        f"Tu ID de Telegram: `{user.id}`\n"
        f"Usuario: @{user.username or '—'}\n"
        f"Nombre: {user.full_name}\n"
        f"Estado: {estado}\n"
    )
    if not autorizado:
        msg += (
            "\nPedile al administrador que agregue tu ID a la variable "
            "`TELEGRAM_ALLOWED_USER_IDS` en el .env, separado por comas."
        )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Comandos protegidos (requieren estar en la whitelist)
# ---------------------------------------------------------------------------

@requires_auth
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.MARKDOWN)


@requires_auth
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


@requires_auth
async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    n = _service().clear(update.effective_user.id)
    if n == 0:
        await update.message.reply_text("No había historial para borrar 🤷")
    else:
        await update.message.reply_text(
            f"Listo, borré {n} turno(s). Empezamos de cero."
        )


@requires_auth
async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sincroniza el Sheets con la DB. Bloqueante pero rápido (<5s)."""
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )
    try:
        result = await asyncio.to_thread(actualizar_datos)
        await update.message.reply_text(result.resumen())
    except Exception as e:
        logger.exception("Error en /sync")
        await update.message.reply_text(
            f"❌ Error en /sync: {type(e).__name__}: {e}"
        )


@requires_auth
async def cmd_comprar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Atajo directo a DB (sin Gemini): productos en rojo."""
    try:
        productos = await asyncio.to_thread(
            _service().productos_a_comprar, update.effective_user.id, "telegram"
        )
        await _reply_largo(update, format_comprar_message(productos))
    except Exception as e:
        logger.exception("Error en /comprar")
        await update.message.reply_text(
            f"Ups, no pude leer los productos a comprar. ({type(e).__name__})"
        )


@requires_auth
async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Atajo directo a DB (sin Gemini): resumen ejecutivo."""
    try:
        resumen = await asyncio.to_thread(
            _service().resumen_ejecutivo, update.effective_user.id, "telegram"
        )
        await _reply_largo(
            update,
            format_resumen_message(resumen),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.exception("Error en /resumen")
        await update.message.reply_text(
            f"Ups, no pude generar el resumen. ({type(e).__name__})"
        )


@requires_auth
async def cmd_reclamo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registra un reclamo sin pasar por el modelo: /reclamo <descripción>."""
    descripcion = " ".join(context.args or []).strip()
    if len(descripcion) < 5:
        await update.message.reply_text(
            "Contame qué pasó después del comando. Ej:\n/reclamo llegaron 10 gorras rojas descosidas"
        )
        return
    resultado = await asyncio.to_thread(
        _service().registrar_reclamo, update.effective_user.id, descripcion, "otro", None, "telegram"
    )
    if not resultado.get("ok"):
        await update.message.reply_text(resultado.get("error", "No pude registrar el reclamo."))
        return
    cuando = (
        "Lo revisa una persona el próximo día hábil."
        if resultado.get("fuera_de_horario")
        else "Lo revisa una persona del equipo."
    )
    if resultado.get("requiere_humano"):
        cuando += " Quedó marcado como prioritario."
    await update.message.reply_text(f"✅ Reclamo #{resultado['numero']} registrado. {cuando}")


# ---------------------------------------------------------------------------
# Handler de mensajes de texto libre (también protegido)
# ---------------------------------------------------------------------------

@requires_auth
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto = (update.message.text or "").strip()
    if not texto:
        return

    user_id = update.effective_user.id

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )

    try:
        respuesta = await asyncio.to_thread(
            _service().ask, user_id, texto, "telegram"
        )
        await _reply_largo(update, respuesta)
    except Exception as e:
        logger.exception("Error procesando mensaje de user_id=%s", user_id)
        await update.message.reply_text(describir_error(e).mensaje)


# ---------------------------------------------------------------------------
# Manejador global de errores
# ---------------------------------------------------------------------------

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception(
        "Excepción no manejada en update=%s", update, exc_info=context.error
    )


# ---------------------------------------------------------------------------
# Setup del Application
# ---------------------------------------------------------------------------

def build_application() -> Application:
    if not settings.telegram_bot_token or settings.telegram_bot_token == "tu_token_de_telegram":
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN no configurado. "
            "Conseguilo con @BotFather y ponelo en .env"
        )

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    # /whoami va SIN auth: un nuevo usuario lo necesita para obtener su ID
    # y pedir que lo agreguen a la whitelist.
    app.add_handler(CommandHandler("whoami", cmd_whoami))

    # El resto requiere autorización (ver decorator @requires_auth)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("comprar", cmd_comprar))
    app.add_handler(CommandHandler("resumen", cmd_resumen))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("reclamo", cmd_reclamo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(on_error)

    return app


def run() -> None:
    """Arranca el bot con long-polling."""
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    # WARNING importante si está en modo abierto
    allowed = settings.allowed_user_ids_set
    if not allowed:
        logger.warning(
            "⚠️  TELEGRAM_ALLOWED_USER_IDS está VACIO. "
            "El bot funciona en MODO ABIERTO: cualquiera con el username puede usarlo. "
            "NO uses esto en producción — configurá la whitelist en .env."
        )
    else:
        logger.info("Whitelist activa: %d usuarios autorizados", len(allowed))

    logger.info("Inicializando MerchBot...")
    _ = _service().assistant  # warm-up: falla rápido si falta la API key

    logger.info("Arrancando bot de Telegram (long-polling)...")
    app = build_application()
    app.run_polling(allowed_updates=Update.ALL_TYPES)
