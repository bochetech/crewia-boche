"""
Telegram Bot — Triage Analytical Pipeline gateway.

Connects a Telegram chat directly to the TriageCrew agent.  Any message
you send to the bot is triaged by the Gemini-powered agent, and the
structured result is sent back to your chat.

Setup
-----
1. Talk to @BotFather on Telegram → /newbot → copy the token.
2. Add to your .env::

       TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRstUVwXyz

3. Start the bot::

       .venv313/bin/python3 main.py --mode telegram

4. Open your bot in Telegram and send any message.

Supported commands
------------------
/start   — Welcome message with usage instructions.
/help    — Show available commands.
/status  — Show how many messages are pending in the inbox queue.
Any other text — Treated as an incoming message to triage.

Architecture
------------
User sends text  →  Telegram servers  →  Bot (polling)
    → enqueued in ChatMessageInboxTool._queue
    → TriageCrew.kickoff(message_text)
    → result formatted and sent back to same chat
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from dotenv import load_dotenv
from telegram import Update, constants
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.triage_crew import TriageCrew
from src.input_sources import ChatMessageInboxTool, EmailInboxTool, message_to_triage_text
from src.email_watcher import start_email_watcher

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WELCOME = """
Hola, soy Nia.

Soy la Analista Estratégica de Triaje de Descorcha. Trabajo en dos modos:

*Modo Conversación*
Pregúntame sobre estrategia, procesos o cualquier duda que tengas.
Ejemplos: "¿Cómo funciona el triage?", "Ayúdame con esto"

*Modo Triage*
Envíame emails completos para clasificarlos como STRATEGIC o JUNK.
Formato:
```
De: remitente@empresa.com
Asunto: Propuesta integración

Cuerpo del email...
```

*Comandos disponibles:*
/start — Este mensaje
/help  — Ayuda
/status — Estado del inbox
/miid — Tu chat_id
/nueva — Limpiar contexto y empezar conversación nueva

Conversa conmigo o envíame un email para analizar.
Recuerdo el contexto durante 10 minutos.
""".strip()

_HELP = """
*Nia — Analista Estratégica de Triaje*

*Modo Conversación:*
Pregúntame lo que quieras. Mantengo contexto de los últimos 10 mensajes.
• "¿Qué opinas de Shopify?"
• "Ayúdame a decidir si esto es estratégico"
Cuando quieras que formalice algo, responde: *'Sí'* o *'Hazlo'*

*Modo Triage (emails):*
Envíame el email completo y lo clasifico como STRATEGIC o JUNK.
```
De: proveedor@empresa.com
Asunto: Propuesta integración Shopify

Cuerpo del mensaje...
```

*Comandos:*
/start  — Bienvenida
/help   — Esta ayuda
/status — Mensajes pendientes en el inbox
/miid   — Obtener tu chat_id
/nueva  — Limpiar contexto de conversación

*Nota:* El contexto se limpia automáticamente después de 10 minutos de inactividad.
""".strip()


# ---------------------------------------------------------------------------
# Telegram message formatter
# ---------------------------------------------------------------------------

def _format_result(result: object) -> str:  # noqa: ANN001
    """Convert a TriageDecisionOutput into a clean Telegram Markdown message."""
    from src.triage_crew import TriageDecisionOutput  # local import to avoid circularity

    r: TriageDecisionOutput = result  # type: ignore[assignment]

    lines = [
        f"*Clasificación: {r.classification}*",
        "",
        f"*Razonamiento:*",
        f"_{r.reasoning[:400]}_",
        "",
        f"*De:* {r.email_summary.sender or '—'}",
        f"*Asunto:* {r.email_summary.subject or '—'}",
    ]

    if r.email_summary.key_topics:
        lines.append(f"*Temas:* {', '.join(r.email_summary.key_topics[:5])}")

    if r.actions_taken:
        lines += ["", "*Acciones ejecutadas:*"]
        for action in r.actions_taken:
            status_icon = "✓" if action.status == "ok" else "✗"
            lines.append(f"  {status_icon} `{action.tool}` — {action.details[:120]}")

    if r.pending_approvals:
        lines += ["", "*Pendiente de tu aprobación:*"]
        for item in r.pending_approvals:
            lines.append(f"  • {item}")

    if r.discarded and r.discard_reason:
        lines += ["", f"*Motivo de descarte:* {r.discard_reason}"]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def _cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_WELCOME, parse_mode=constants.ParseMode.MARKDOWN)


async def _cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_HELP, parse_mode=constants.ParseMode.MARKDOWN)


async def _cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    email_pending = EmailInboxTool.pending_count()
    chat_pending  = ChatMessageInboxTool.pending_count()
    imap_user = os.getenv("IMAP_USER", "").strip()
    imap_status = f"`{imap_user}`" if imap_user else "_(no configurado)_"
    await update.message.reply_text(
        f"📊 *Estado del inbox*\n"
        f"  📧 Email: {email_pending} pendiente(s) | cuenta: {imap_status}\n"
        f"  💬 Chat:  {chat_pending} pendiente(s)",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def _cmd_nueva(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear conversation context and start fresh."""
    context.user_data["conversation_history"] = []
    context.user_data.pop("last_message_time", None)
    await update.message.reply_text(
        "Listo, contexto limpiado. Empezamos de cero.\n\n¿En qué te puedo ayudar?",
        parse_mode=constants.ParseMode.MARKDOWN
    )


async def _cmd_miid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with the user's own Telegram chat_id."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"🪪 *Tu identificación de Telegram*\n\n"
        f"  Chat ID: `{chat_id}`\n"
        f"  User ID: `{user_id}`\n\n"
        f"Copia el *Chat ID* y pégalo en `.env` como:\n"
        f"`IMAP_NOTIFY_CHAT_ID={chat_id}`",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def _handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Main handler: conversational AI or triage depending on message structure."""
    user = update.effective_user
    text = update.message.text or ""

    if not text.strip():
        await update.message.reply_text("Mensaje vacío. Envíame texto para analizarlo.")
        return

    sender_label = f"@{user.username}" if user.username else f"tg:{user.id}"
    logger.info("[TelegramBot] Received message from %s: %s…", sender_label, text[:80])

    # ── Detección de modo: CONVERSACIÓN vs TRIAGE ───────────────────────────
    # LÓGICA: TODO es CONVERSACIÓN por defecto, excepto si es claramente un EMAIL
    
    # Detectar formato de email (headers explícitos)
    is_email_format = any(
        line.strip().lower().startswith(prefix)
        for line in text.split("\n")[:5]
        for prefix in ("de:", "from:", "asunto:", "subject:", "fecha:", "date:")
    )
    
    # Palabras clave que indican intención de TRIAGE explícito
    triage_keywords = [
        "clasifica esto", "clasifica el siguiente", "analiza este email",
        "triaje", "triage", "documenta esto", "es strategic", "es junk"
    ]
    is_explicit_triage = any(keyword in text.lower() for keyword in triage_keywords)
    
    # Mensajes muy largos (>100 palabras) probablemente son emails sin headers
    is_very_long = len(text.split()) > 100
    
    # DECISIÓN: Solo hacer TRIAGE si es email o solicitud explícita
    should_triage = is_email_format or is_explicit_triage or is_very_long
    
    # ── MODO CONVERSACIONAL (por defecto) ──────────────────────────────────
    if not should_triage:
        await _handle_conversation(update, context, text, sender_label)
        return

    # ── MODO TRIAGE (email o solicitud explícita) ──────────────────────────
    ack = await update.message.reply_text(
        "_Analizando tu mensaje…_",
        parse_mode=constants.ParseMode.MARKDOWN,
    )

    try:
        # Format as standard triage input text (solo si no tiene headers ya)
        if not is_email_format:
            triage_text = (
                f"De: {sender_label}\n"
                f"Asunto: (mensaje de Telegram)\n"
                f"Canal: telegram\n\n"
                f"{text}"
            )
        else:
            triage_text = text  # Ya tiene formato de email

        # Run in thread pool so the async event loop is not blocked
        crew: TriageCrew = context.bot_data["crew"]
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, crew.kickoff, triage_text)

        reply = _format_result(result)

        # Edit the "processing…" message with the actual result
        await ack.edit_text(reply, parse_mode=constants.ParseMode.MARKDOWN)

    except Exception as exc:
        logger.exception("[TelegramBot] Error processing message")
        await ack.edit_text(
            f"Error procesando el mensaje:\n`{exc}`",
            parse_mode=constants.ParseMode.MARKDOWN,
        )


async def _handle_conversation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    sender_label: str,
) -> None:
    """Handle conversational messages with context memory and automatic cleanup."""
    import time
    
    text_lower = text.lower()
    
    # Inicializar historial de conversación si no existe
    if "conversation_history" not in context.user_data:
        context.user_data["conversation_history"] = []
        context.user_data["last_message_time"] = time.time()
    
    # ── Auto-limpieza: timeout de 10 minutos ────────────────────────────────
    current_time = time.time()
    last_message_time = context.user_data.get("last_message_time", current_time)
    time_since_last = current_time - last_message_time
    
    # Si pasaron más de 10 minutos, limpiar contexto
    if time_since_last > 600:  # 600 segundos = 10 minutos
        context.user_data["conversation_history"] = []
        logger.info("[Conversación] Historial limpiado por timeout (%.1f min)", time_since_last / 60)
    
    context.user_data["last_message_time"] = current_time
    
    # ── Comando explícito de limpieza ───────────────────────────────────────
    if text_lower in ["nueva conversación", "nueva", "limpiar", "reset", "reiniciar"]:
        context.user_data["conversation_history"] = []
        await update.message.reply_text(
            "Listo, contexto limpiado. Empezamos de cero.\n\n¿En qué te puedo ayudar?",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return
    
    # Agregar mensaje del usuario al historial
    context.user_data["conversation_history"].append({
        "role": "user",
        "content": text,
        "timestamp": current_time
    })
    
    # Limitar historial a últimos 10 mensajes (5 intercambios)
    if len(context.user_data["conversation_history"]) > 10:
        context.user_data["conversation_history"] = context.user_data["conversation_history"][-10:]
    
    # ── Comandos de control de conversación ─────────────────────────────────
    if text_lower in ["listo", "ok", "dale", "hazlo", "sí", "si", "procede", "adelante"]:
        # El usuario confirma una acción que Nia sugirió
        history = context.user_data["conversation_history"]
        if len(history) >= 2:
            # Reconstruir contexto completo para triage
            full_context = "\n\n".join([
                f"{'Usuario' if msg['role'] == 'user' else 'Nia'}: {msg['content']}"
                for msg in history[-6:]  # Últimos 3 intercambios
            ])
            
            await update.message.reply_text("_Procesando con contexto completo…_", parse_mode=constants.ParseMode.MARKDOWN)
            
            # Ejecutar triage con contexto
            triage_text = (
                f"De: {sender_label}\n"
                f"Asunto: Conversación → Solicitud de triage\n"
                f"Canal: telegram\n\n"
                f"CONTEXTO DE LA CONVERSACIÓN:\n{full_context}\n\n"
                f"ACCIÓN: Usuario confirma proceder con el triage/documentación."
            )
            
            try:
                crew: TriageCrew = context.bot_data["crew"]
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, crew.kickoff, triage_text)
                reply = _format_result(result)
                await update.message.reply_text(reply, parse_mode=constants.ParseMode.MARKDOWN)
                
                # Limpiar historial después de ejecutar acción
                context.user_data["conversation_history"] = []
            except Exception as exc:
                logger.exception("[TelegramBot] Error en triage con contexto")
                await update.message.reply_text(
                    f"Error procesando: `{exc}`",
                    parse_mode=constants.ParseMode.MARKDOWN,
                )
            return
    
    # ── Respuestas conversacionales con LLM (SIN reasoning) ────────────────
    # En lugar de respuestas enlatadas, usar kickoff_conversation() para 
    # respuestas dinámicas y contextuales
    
    try:
        crew: TriageCrew = context.bot_data["crew"]
        loop = asyncio.get_event_loop()
        
        # Mostrar indicador de escritura
        await update.message.chat.send_action(action=constants.ChatAction.TYPING)
        
        # Llamar a kickoff_conversation() con historial
        history = context.user_data.get("conversation_history", [])
        response = await loop.run_in_executor(
            None,
            crew.kickoff_conversation,
            text,
            history
        )
        
        # Agregar respuesta de Nia al historial
        context.user_data["conversation_history"].append({
            "role": "assistant",
            "content": response,
            "timestamp": time.time()
        })
        
        await update.message.reply_text(response, parse_mode=None)
        
    except Exception as exc:
        logger.exception("[TelegramBot] Error en conversación")
        
        # Fallback a respuesta genérica si el LLM falla
        response = (
            "Entiendo. ¿Quieres que analice esto formalmente y ejecute acciones "
            "(documentar, notificar, etc.)?\n\n"
            "Si quieres que proceda con el triage completo, responde: *'Sí'* o *'Hazlo'*"
        )
        await update.message.reply_text(response, parse_mode=constants.ParseMode.MARKDOWN)


def _generate_strategic_opinion(text: str, history: list) -> str:
    """Generate a strategic opinion and offer to formalize it."""
    text_lower = text.lower()
    
    # Detectar temas estratégicos clave
    if any(word in text_lower for word in ["shopify", "ecommerce", "e-commerce", "tienda"]):
        return (
            "Shopify está totalmente alineado con nuestra estrategia de eCommerce DTC. "
            "Es una plataforma confiable, escalable y con integraciones nativas que pueden "
            "acelerar el lanzamiento del canal digital.\n\n"
            "¿Quieres que documente esta propuesta formalmente en Confluence y "
            "notifique al líder técnico? Responde *'Sí'* y lo proceso completo."
        )
    elif any(word in text_lower for word in ["integración", "integracion", "api", "sap", "bokun", "bókun"]):
        return (
            "Las integraciones son un foco estratégico crítico. SAP y Bókun son sistemas "
            "core que requieren BFFs y adaptadores robustos para garantizar confiabilidad operativa.\n\n"
            "Si esto viene de un proveedor o propuesta externa, puedo documentarlo y "
            "redactar un borrador de validación técnica. ¿Procedo?"
        )
    elif any(word in text_lower for word in ["automatización", "automatizacion", "digitalización", "digitalizacion"]):
        return (
            "La automatización y digitalización de procesos está en nuestros focos estratégicos, "
            "especialmente para operaciones de campo y gestión interna.\n\n"
            "¿Hay un proyecto específico que quieras que documente o escale? "
            "Responde *'Sí'* y lo formalizo."
        )
    else:
        return (
            "Déjame pensar... Basándome en la estrategia de Descorcha, esto podría ser relevante "
            "si toca áreas como DTC, fidelización, carriers, o eficiencia operativa.\n\n"
            "¿Quieres que lo analice formalmente y determine si requiere documentación o escalamiento? "
            "Responde *'Sí'* para proceder con el triage completo."
        )


# ---------------------------------------------------------------------------
# Bot builder + runner
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Bot builder + runner
# ---------------------------------------------------------------------------

def build_application(token: str) -> Application:
    """Build and configure the Telegram Application."""
    crew = TriageCrew()  # Built once, shared across all messages

    app = Application.builder().token(token).build()
    app.bot_data["crew"] = crew

    app.add_handler(CommandHandler("start",  _cmd_start))
    app.add_handler(CommandHandler("help",   _cmd_help))
    app.add_handler(CommandHandler("status", _cmd_status))
    app.add_handler(CommandHandler("miid",   _cmd_miid))
    app.add_handler(CommandHandler("nueva",  _cmd_nueva))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))

    # ── Email watcher (background task) ────────────────────────────────────
    # post_init runs inside the same event loop as run_polling, so we can
    # schedule a coroutine as a proper asyncio task that lives alongside the bot.
    async def _start_watcher(application: Application) -> None:
        imap_user = os.getenv("IMAP_USER", "").strip()
        if imap_user:
            # Get the admin chat_id if set in env (optional — to forward results)
            raw_chat_id = os.getenv("IMAP_NOTIFY_CHAT_ID", "").strip()
            notify_chat_id = int(raw_chat_id) if raw_chat_id.lstrip("-").isdigit() else None

            asyncio.create_task(
                start_email_watcher(
                    crew=application.bot_data["crew"],
                    notify_chat_id=notify_chat_id,
                    bot=application.bot,
                ),
                name="email_watcher",
            )
            logger.info(
                "[TelegramBot] Email watcher scheduled for %s (notify_chat_id=%s)",
                imap_user, notify_chat_id,
            )
        else:
            logger.info(
                "[TelegramBot] Email watcher disabled — set IMAP_USER in .env to enable."
            )

    app.post_init = _start_watcher  # type: ignore[assignment]

    return app


def run_bot(token: Optional[str] = None) -> None:
    """Start the bot in polling mode.  Blocks until Ctrl+C."""
    load_dotenv()
    bot_token = token or os.getenv("TELEGRAM_BOT_TOKEN")

    if not bot_token:
        raise EnvironmentError(
            "TELEGRAM_BOT_TOKEN no encontrado.\n"
            "Pasos:\n"
            "  1. Habla con @BotFather en Telegram → /newbot\n"
            "  2. Copia el token y agrégalo a .env:\n"
            "       TELEGRAM_BOT_TOKEN=123456789:ABCdef...\n"
            "  3. Vuelve a ejecutar: .venv313/bin/python3 main.py --mode telegram"
        )

    print("\n🤖  Bot de Triage Analítico — Descorcha")
    print("    Iniciando conexión con Telegram…\n")

    app = build_application(bot_token)

    print("✅  Bot activo. Escríbele en Telegram.")
    print("    Presiona Ctrl+C para detener.\n")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,   # Ignore messages sent while the bot was offline
    )


__all__ = ["run_bot", "build_application"]
