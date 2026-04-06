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

Conversa conmigo o envíame un email para analizar.
""".strip()

_HELP = """
*Nia — Analista Estratégica de Triaje*

Envíame cualquier mensaje de texto y lo clasificaré como:
• *STRATEGIC* — Relevante para la estrategia Descorcha. Lo documento en Confluence, redacto un borrador de seguimiento y notifico al líder.
• *JUNK* — Spam o sin alineación estratégica. Lo descarto y notifico al líder.

*Formato sugerido para emails:*
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
    # Si el mensaje tiene estructura de email (De:, Asunto:, etc.) → TRIAGE
    # Si es una pregunta/conversación directa → CONVERSACIÓN
    is_email_format = any(
        line.strip().lower().startswith(prefix)
        for line in text.split("\n")[:5]
        for prefix in ("de:", "from:", "asunto:", "subject:")
    )
    
    # Patrones conversacionales (preguntas directas, saludos)
    conversational_patterns = [
        "hola", "cómo estás", "como estas", "qué tal", "que tal",
        "ayuda", "ayúdame", "ayudame", "explica", "cuéntame", "cuentame",
        "nia", "necesito", "puedes", "podrías", "podrias",
    ]
    is_conversational = (
        not is_email_format
        and len(text.split()) < 50  # Menos de 50 palabras probablemente es conversación
        and any(pattern in text.lower() for pattern in conversational_patterns)
    )

    # ── MODO CONVERSACIONAL ─────────────────────────────────────────────────
    if is_conversational:
        await _handle_conversation(update, context, text, sender_label)
        return

    # ── MODO TRIAGE (email o mensaje largo estructurado) ───────────────────
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
    """Handle conversational messages (not triage requests)."""
    # Respuestas conversacionales simples basadas en el contexto de Nia
    text_lower = text.lower()
    
    if any(word in text_lower for word in ["hola", "holi", "buenas", "saludos"]):
        response = (
            "Hola! Soy Nia, tu Analista Estratégica de Triaje.\n\n"
            "Puedo ayudarte de dos formas:\n"
            "• *Conversación*: pregúntame sobre estrategia, procesos o cómo funciono\n"
            "• *Triage*: envíame un email completo (con De: y Asunto:) para clasificarlo\n\n"
            "¿En qué te puedo ayudar?"
        )
    elif any(word in text_lower for word in ["cómo estás", "como estas", "qué tal", "que tal"]):
        response = (
            "Funcionando perfectamente, gracias por preguntar.\n\n"
            "Estoy monitoreando `niaboche@gmail.com` cada 60 segundos y lista para "
            "clasificar cualquier mensaje que me envíes.\n\n"
            "¿Tienes algún email que quieras que analice?"
        )
    elif "ayuda" in text_lower or "ayúdame" in text_lower or "ayudame" in text_lower:
        response = (
            "Claro, te ayudo.\n\n"
            "*Para triage de emails:*\n"
            "Envíame el texto completo del email con este formato:\n"
            "```\nDe: remitente@ejemplo.com\nAsunto: Título del email\n\n"
            "Cuerpo del mensaje...\n```\n\n"
            "*Para conversación:*\n"
            "Simplemente pregúntame lo que necesites saber sobre estrategia, "
            "procesos de Descorcha o mi funcionamiento."
        )
    elif "nia" in text_lower and "?" in text:
        response = (
            "Soy Nia, Analista Estratégica de Triaje para Descorcha.\n\n"
            "Mi trabajo es:\n"
            "• Clasificar emails/mensajes como STRATEGIC o JUNK\n"
            "• Documentar información relevante en Confluence\n"
            "• Redactar borradores de respuesta cuando se necesita colaboración\n"
            "• Notificar al líder técnico de decisiones importantes\n\n"
            "Trabajo con una cascada de modelos:\n"
            "1. LM Studio local (tu máquina)\n"
            "2. Gemini (si local falla)\n"
            "3. Clasificador determinístico (último recurso)"
        )
    else:
        # Respuesta genérica para otras conversaciones
        response = (
            "Entiendo que quieres conversar, pero no estoy segura de cómo responder a eso específicamente.\n\n"
            "Puedo ayudarte mejor si:\n"
            "• Me envías un email completo para clasificar (De: / Asunto: / Cuerpo)\n"
            "• Me preguntas sobre estrategia de Descorcha\n"
            "• Me pides ayuda sobre cómo usar el sistema de triage\n\n"
            "¿Qué prefieres?"
        )
    
    await update.message.reply_text(response, parse_mode=constants.ParseMode.MARKDOWN)


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
