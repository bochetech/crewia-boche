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
from src.conversation_memory import create_user_memory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WELCOME = """
Hola, soy Nia.

Soy la Analista Estratégica de Triaje de Descorcha. Trabajo en dos modos:

*💬 Modo Conversación*
Pregúntame sobre estrategia, procesos o cualquier duda.
Ejemplos: "¿Cómo funciona el triage?", "Ayúdame con esto"

*📊 Modo Triage (análisis formal)*
Cuando quieras que documente y clasifique algo, usa:
• "haz el triage"
• "clasifica esto"
• "documenta esto"

*🎤 Mensajes de voz:*
¡Puedes enviarme notas de voz! Las transcribo automáticamente con Whisper.
📢 *NUEVO:* Si me hablas por voz, te responderé por voz también.
Si me escribes, te responderé por texto.
Perfecto para capturar iniciativas desde reuniones o mientras manejas.

*🧠 Memoria conversacional:*
Recuerdo los últimos 10 mensajes (se limpia cada 10 min)
Cuando haces triage, analizo CON TODO el contexto previo.

*🗂️ Sistema de cajones (memoria semántica):*
Organizo automáticamente las conversaciones en hasta 10 "cajones" temáticos.
Cuando mencionas un tema específico, recupero ese cajón.
Ejemplos:
• "analiza lo de SAP" → busco cajón SAP
• "haz el triage" → tomo cajón más reciente

*Comandos disponibles:*
/help    — Ver ayuda completa
/nueva   — Limpiar contexto
/topics  — Ver cajones activos
/recall  — Buscar por tema
/status  — Estado del inbox
/miid    — Tu chat_id

Conversa conmigo o pídeme que haga un triage.
""".strip()

_HELP = """
*Nia — Analista Estratégica de Triaje*

*Modo Conversación:*
Pregúntame lo que quieras. Mantengo contexto de los últimos 10 mensajes.
• "¿Qué opinas de Shopify?"
• "Ayúdame a decidir si esto es estratégico"
• "Hablemos sobre sistemas de mantenimiento"

*Modo Triage (análisis formal):*
Cuando quieras que documente y clasifique formalmente, usa palabras clave:
• "triage esto"
• "clasifica esto"
• "documenta esto en Confluence"
• "analiza si es estratégico"

📝 *Memoria conversacional:*
• Cuando haces triage, incluyo automáticamente los últimos 10 mensajes
• Así analizo con contexto completo, no solo el último mensaje
• Ejemplo: Conversamos sobre mantenimiento → "hazle triage" → analiza todo
• Después del triage, limpio el contexto para empezar fresco

🗂️ *Sistema de cajones (memoria semántica):*
• Organizo automáticamente las conversaciones en hasta 10 "cajones" temáticos
• Cuando mencionas un tema específico (ej: "analiza lo de SAP"), busco ese cajón
• Si no mencionas tema, tomo el cajón más reciente
• Persiste entre reinicios (ChromaDB local)

*Comandos:*
/nueva  — Limpiar contexto y empezar conversación nueva
/topics — Ver resumen de cajones activos
/recall <tema> — Recuperar conversación sobre un tema
/status — Ver inbox
/miid   — Tu chat_id

*Nota:* El contexto se limpia automáticamente después de 10 minutos de inactividad.
""".strip()


# ---------------------------------------------------------------------------
# Telegram message formatter
# ---------------------------------------------------------------------------

def _format_result(result: object) -> str:  # noqa: ANN001
    """Convert a TriageDecisionOutput into a clean Telegram Markdown message."""
    from src.triage_crew import TriageDecisionOutput  # local import to avoid circularity

    r: TriageDecisionOutput = result  # type: ignore[assignment]
    
    def escape_markdown(text: str) -> str:
        """Escape special Markdown characters for Telegram."""
        if not text:
            return ""
        # Escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text

    lines = [
        f"*Clasificación:* {r.classification}",
        "",
        "*Razonamiento:*",
        escape_markdown(r.reasoning[:300]),
        "",
        f"*De:* {escape_markdown(r.email_summary.sender or '—')}",
        f"*Asunto:* {escape_markdown(r.email_summary.subject or '—')}",
    ]

    if r.email_summary.key_topics:
        topics_str = ', '.join(escape_markdown(t) for t in r.email_summary.key_topics[:5])
        lines.append(f"*Temas:* {topics_str}")

    if r.actions_taken:
        lines += ["", "*Acciones ejecutadas:*"]
        for action in r.actions_taken:
            status_icon = "✓" if action.status == "ok" else "✗"
            tool = escape_markdown(action.tool)
            details = escape_markdown(action.details[:120])
            lines.append(f"  {status_icon} {tool} — {details}")

    if r.pending_approvals:
        lines += ["", "*Pendiente de tu aprobación:*"]
        for item in r.pending_approvals:
            lines.append(f"  • {escape_markdown(item)}")

    if r.discarded and r.discard_reason:
        lines += ["", f"*Motivo de descarte:* {escape_markdown(r.discard_reason)}"]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Audio Transcription (Whisper)
# ---------------------------------------------------------------------------

async def _transcribe_voice_message(file_path: str) -> Optional[str]:
    """Transcribe audio file using Whisper.
    
    Args:
        file_path: Path to audio file (ogg, mp3, wav, etc.)
        
    Returns:
        Transcribed text or None if transcription fails
    """
    try:
        import whisper
        import torch
        import ssl
        import urllib.request
        
        logger.info(f"🎤 Transcribiendo audio: {file_path}")
        
        # WORKAROUND: Deshabilitar verificación SSL para descarga de modelo Whisper
        # (necesario en redes corporativas con proxies/certificados auto-firmados)
        ssl_context = ssl._create_unverified_context()
        original_opener = urllib.request._opener
        urllib.request.install_opener(
            urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_context))
        )
        
        # Cargar modelo Whisper (base es buen balance velocidad/precisión)
        # Opciones: tiny, base, small, medium, large
        # tiny: más rápido, menos preciso
        # base: balance (recomendado para CPU)
        # large: más preciso, requiere GPU
        try:
            model = whisper.load_model("base")
        finally:
            # Restaurar opener original después de descargar modelo
            if original_opener:
                urllib.request.install_opener(original_opener)
        
        # Transcribir con detección automática de idioma
        result = model.transcribe(
            file_path,
            language="es",  # Forzar español (Descorcha es empresa chilena)
            fp16=False,     # Deshabilitar fp16 si no hay GPU
            verbose=False
        )
        
        transcription = result["text"].strip()
        logger.info(f"✅ Transcripción completada: {len(transcription)} chars")
        
        return transcription
        
    except Exception as exc:
        logger.error(f"❌ Error transcribiendo audio: {exc}")
        return None


# ---------------------------------------------------------------------------
# Audio Synthesis (Text-to-Speech)
# ---------------------------------------------------------------------------

async def _synthesize_voice(text: str, lang: str = "es") -> Optional[str]:
    """Convert text to speech using gTTS.
    
    Args:
        text: Text to synthesize
        lang: Language code (default: "es" for Spanish)
        
    Returns:
        Path to generated audio file or None if synthesis fails
    """
    try:
        from gtts import gTTS
        import tempfile
        
        logger.info(f"🔊 Sintetizando voz: {len(text)} chars")
        
        # Crear archivo temporal para el audio
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_audio:
            temp_path = temp_audio.name
        
        # Generar audio con gTTS
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(temp_path)
        
        logger.info(f"✅ Audio generado: {temp_path}")
        return temp_path
        
    except Exception as exc:
        logger.error(f"❌ Error sintetizando voz: {exc}")
        return None


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


async def _cmd_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show summary of active topic buckets."""
    user_id = str(update.effective_user.id)
    
    try:
        memory = create_user_memory(user_id, max_topics=10)
        topics = memory.get_topics_summary()
        
        if not topics:
            await update.message.reply_text(
                "🗂️ No hay cajones activos aún.\n\n"
                "Conversa conmigo sobre diferentes temas y los organizaré automáticamente.",
                parse_mode=constants.ParseMode.MARKDOWN
            )
            return
        
        lines = ["🗂️ *Cajones activos de memoria:*\n"]
        for i, (topic_label, msg_count) in enumerate(topics, 1):
            lines.append(f"{i}. `{topic_label}` — {msg_count} mensajes")
        
        lines.append(
            "\n💡 Usa `/recall <tema>` para recuperar un cajón específico"
        )
        
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        
    except Exception as exc:
        logger.exception("[TelegramBot] Error en /topics")
        await update.message.reply_text(
            f"Error al obtener cajones: `{exc}`",
            parse_mode=constants.ParseMode.MARKDOWN
        )


async def _cmd_recall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Recall messages about a specific topic."""
    user_id = str(update.effective_user.id)
    
    # Extraer query del comando (ej: "/recall SAP integración")
    text = update.message.text or ""
    parts = text.split(maxsplit=1)
    
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ Uso: `/recall <tema>`\n\n"
            "Ejemplo: `/recall SAP integración`",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return
    
    query = parts[1].strip()
    
    try:
        memory = create_user_memory(user_id, max_topics=10)
        context_text = memory.get_context_for_triage(query=query, max_messages=10)
        
        if not context_text:
            await update.message.reply_text(
                f"🔍 No encontré conversaciones sobre: `{query}`\n\n"
                f"Usa `/topics` para ver los cajones disponibles.",
                parse_mode=constants.ParseMode.MARKDOWN
            )
            return
        
        # Formatear para legibilidad
        response = (
            f"🧠 *Recuerdos sobre: {query}*\n\n"
            f"{context_text}"
        )
        
        # Telegram tiene límite de 4096 chars por mensaje
        if len(response) > 4000:
            response = response[:4000] + "\n\n...(truncado)"
        
        await update.message.reply_text(
            response,
            parse_mode=constants.ParseMode.MARKDOWN
        )
        
    except Exception as exc:
        logger.exception("[TelegramBot] Error en /recall")
        await update.message.reply_text(
            f"Error al buscar: `{exc}`",
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



async def _handle_voice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handler para mensajes de voz: transcribe con Whisper y procesa como texto."""
    user = update.effective_user
    voice = update.message.voice
    
    sender_label = f"@{user.username}" if user.username else f"tg:{user.id}"
    logger.info(f"🎤 [TelegramBot] Mensaje de voz recibido de {sender_label} ({voice.duration}s)")
    
    # Enviar mensaje de procesamiento
    processing_msg = await update.message.reply_text(
        "🎤 Transcribiendo mensaje de voz...",
        parse_mode=constants.ParseMode.MARKDOWN
    )
    
    try:
        import tempfile
        import os
        
        # Descargar archivo de voz
        file = await context.bot.get_file(voice.file_id)
        
        # Crear archivo temporal para el audio
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_audio:
            temp_path = temp_audio.name
            await file.download_to_drive(temp_path)
        
        # Transcribir con Whisper
        transcription = await _transcribe_voice_message(temp_path)
        
        # Limpiar archivo temporal
        os.unlink(temp_path)
        
        if not transcription:
            await processing_msg.edit_text(
                "❌ No pude transcribir el audio. ¿Puedes intentar de nuevo con mejor audio?",
                parse_mode=constants.ParseMode.MARKDOWN
            )
            return
        
        # Actualizar mensaje con transcripción
        await processing_msg.edit_text(
            f"🎤 *Transcripción:*\n\n_{transcription}_\n\n⏳ Procesando...",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        
        logger.info(f"✅ Transcripción: {transcription}")
        
        # Marcar que el input fue de voz para responder con voz
        if "user_data" not in context.user_data:
            context.user_data["user_data"] = {}
        context.user_data["input_was_voice"] = True
        
        # Procesar transcripción directamente (sin modificar update.message inmutable)
        sender_label = f"@{user.username}" if user.username else f"tg:{user.id}"
        await _process_text_message(
            update=update,
            context=context,
            text=transcription,
            sender_label=sender_label,
            processing_msg=processing_msg
        )
        
    except Exception as exc:
        logger.error(f"❌ Error procesando mensaje de voz: {exc}")
        try:
            await processing_msg.edit_text(
                f"❌ Error procesando audio: {str(exc)[:100]}",
                parse_mode=constants.ParseMode.MARKDOWN
            )
        except:
            pass  # Mensaje ya eliminado o no editable


async def _process_text_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    sender_label: str,
    processing_msg = None
) -> None:
    """Process a text message (from typed text or voice transcription).
    
    Args:
        update: Telegram update object
        context: Bot context
        text: Text to process (typed or transcribed)
        sender_label: User identifier for logging
        processing_msg: Optional message to edit/delete after processing
    """
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
        # Eliminar mensaje de procesamiento si existe
        if processing_msg:
            try:
                await processing_msg.delete()
            except:
                pass
        return

    # ── MODO TRIAGE (email o solicitud explícita) ──────────────────────────
    if not processing_msg:
        processing_msg = await update.message.reply_text(
            "_Analizando tu mensaje con contexto completo…_",
            parse_mode=constants.ParseMode.MARKDOWN,
        )

    try:
        user_id = str(update.effective_user.id)
        
        # ── MEMORIA SEMÁNTICA: Detectar tema mencionado ─────────────────────────
        topic_keywords = [
            "sap", "bokun", "bókun", "shopify", "3pl", "carrier", "logística",
            "mantenimiento", "inventario", "costos", "integración", "api",
            "ecommerce", "dtc", "fidelización", "marketplace", "omnicanal"
        ]
        
        detected_topic = None
        text_lower = text.lower()
        
        # Detectar si menciona un tema específico
        for keyword in topic_keywords:
            if keyword in text_lower:
                detected_topic = keyword
                logger.info("[Triage] Tema detectado: %s", detected_topic)
                break
        
        # Recuperar contexto de memoria semántica
        semantic_context = ""
        try:
            memory = create_user_memory(user_id, max_topics=10)
            
            if detected_topic:
                semantic_context = memory.get_context_for_triage(
                    query=detected_topic,
                    max_messages=10
                )
                if semantic_context:
                    logger.info(
                        "[Triage] Recuperado contexto semántico del cajón '%s' (%d chars)",
                        detected_topic,
                        len(semantic_context)
                    )
            else:
                semantic_context = memory.get_context_for_triage(
                    query=None,
                    max_messages=10
                )
                if semantic_context:
                    logger.info(
                        "[Triage] Recuperado contexto del cajón más reciente (%d chars)",
                        len(semantic_context)
                    )
        except Exception as mem_exc:
            logger.warning("[Triage] No se pudo recuperar memoria semántica: %s", mem_exc)
            semantic_context = ""
        
        # Recuperar historial de conversación
        conversation_history = context.user_data.get("conversation_history", [])
        
        # Construir contexto conversacional si hay historial reciente
        short_term_context = ""
        if conversation_history and len(conversation_history) > 0:
            recent_messages = conversation_history[-10:]
            context_lines = []
            for msg in recent_messages:
                role = "Usuario" if msg["role"] == "user" else "Nia"
                content = msg["content"][:300]
                context_lines.append(f"{role}: {content}")
            
            short_term_context = (
                "CONTEXTO CONVERSACIONAL INMEDIATO (últimos 10 mensajes):\n"
                "─────────────────────────────────────────────────────\n"
                + "\n\n".join(context_lines) + "\n"
                "─────────────────────────────────────────────────────\n\n"
            )
            logger.info("[Triage] Incluyendo %d mensajes de contexto conversacional", len(recent_messages))
        
        # Construir bloque de contexto unificado
        context_block = ""
        
        if semantic_context and short_term_context:
            context_block = (
                "MEMORIA SEMÁNTICA (cajón temático relevante):\n"
                "═══════════════════════════════════════════════════════\n"
                f"{semantic_context}\n"
                "═══════════════════════════════════════════════════════\n\n"
                f"{short_term_context}"
            )
        elif semantic_context:
            context_block = (
                "MEMORIA SEMÁNTICA (cajón temático):\n"
                "═══════════════════════════════════════════════════════\n"
                f"{semantic_context}\n"
                "═══════════════════════════════════════════════════════\n\n"
            )
        elif short_term_context:
            context_block = short_term_context
        
        # Format as standard triage input text
        if not is_email_format:
            triage_text = (
                f"De: {sender_label}\n"
                f"Asunto: Análisis de conversación → Triage solicitado\n"
                f"Canal: telegram\n\n"
                f"{context_block}"
                f"SOLICITUD ACTUAL DEL USUARIO:\n{text}"
            )
        else:
            if context_block:
                triage_text = f"{context_block}EMAIL RECIBIDO:\n{text}"
            else:
                triage_text = text

        # Run in thread pool
        crew: TriageCrew = context.bot_data["crew"]
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, crew.kickoff, triage_text)

        reply = _format_result(result)
        
        # ── RESPONDER CON VOZ si el input fue de voz ────────────────────────────
        input_was_voice = context.user_data.get("input_was_voice", False)
        
        if input_was_voice:
            # Para triage con voz, extraer solo el razonamiento para audio
            # (evitar enviar todo el formato Markdown por voz)
            from src.triage_crew import TriageDecisionOutput
            r: TriageDecisionOutput = result
            
            # Construir respuesta hablada más natural
            audio_text = f"He analizado tu mensaje. {r.reasoning[:500]}"
            
            if r.classification == "STRATEGIC":
                audio_text += f" Clasificado como estratégico."
            else:
                audio_text += f" No requiere acción estratégica."
            
            # Enviar transcripción completa por texto primero
            try:
                await processing_msg.edit_text(reply, parse_mode=constants.ParseMode.MARKDOWN)
            except:
                try:
                    await processing_msg.edit_text(reply, parse_mode=None)
                except:
                    pass
            
            # Luego enviar resumen por voz
            await update.message.chat.send_action(action=constants.ChatAction.RECORD_VOICE)
            
            audio_path = await _synthesize_voice(audio_text, lang="es")
            
            if audio_path:
                try:
                    with open(audio_path, "rb") as audio_file:
                        await update.message.reply_voice(voice=audio_file)
                    logger.info("🔊 Resumen del triage enviado como voz")
                except Exception as voice_exc:
                    logger.warning(f"Error enviando voz: {voice_exc}")
                finally:
                    try:
                        os.unlink(audio_path)
                    except:
                        pass
            
            # Limpiar flag de voz
            context.user_data["input_was_voice"] = False
        else:
            # Respuesta normal de texto
            try:
                await processing_msg.edit_text(reply, parse_mode=constants.ParseMode.MARKDOWN)
            except Exception as parse_exc:
                logger.warning(f"Markdown parse error, sending as plain text: {parse_exc}")
                try:
                    await processing_msg.edit_text(reply, parse_mode=None)
                except Exception as plain_exc:
                    logger.error(f"Failed to send even as plain text: {plain_exc}")
                    await processing_msg.edit_text(
                        "✅ Mensaje procesado, pero hubo un error al formatear la respuesta. "
                        "Verifica los logs para más detalles."
                    )
        
        # Limpiar historial conversacional después de triage exitoso
        if "conversation_history" in context.user_data:
            context.user_data["conversation_history"] = []
            logger.info("[Triage] Historial conversacional limpiado post-triage")

    except Exception as exc:
        logger.exception("[TelegramBot] Error processing message")
        
        # Handle quota exceeded error specifically
        error_msg = str(exc)
        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "quota" in error_msg.lower():
            user_friendly_msg = (
                "⚠️ *Límite de API alcanzado*\n\n"
                "El servicio de Gemini AI ha alcanzado su cuota gratuita diaria (20 requests/día).\n\n"
                "📋 *Opciones:*\n"
                "1. Espera ~45 segundos e intenta de nuevo\n"
                "2. Usa el modo conversacional (sin triage)\n"
                "3. Configura un API key con cuota mayor en `.env`"
            )
        else:
            # Generic error message (escape special characters for Markdown)
            error_text = str(exc)[:200].replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace('`', '\\`')
            user_friendly_msg = f"❌ Error procesando el mensaje:\n\n`{error_text}`"
        
        try:
            await processing_msg.edit_text(user_friendly_msg, parse_mode=constants.ParseMode.MARKDOWN)
        except:
            # If even the error message fails, send plain text
            try:
                await processing_msg.edit_text(
                    "❌ Error procesando el mensaje. Revisa los logs del servidor.",
                    parse_mode=None
                )
            except:
                pass  # Give up silently


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

    # Delegar a función de procesamiento común
    await _process_text_message(
        update=update,
        context=context,
        text=text,
        sender_label=sender_label,
        processing_msg=None
    )


async def _handle_conversation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    sender_label: str,
) -> None:
    """Handle conversational messages with context memory and automatic cleanup."""
    import time
    
    user_id = str(update.effective_user.id)
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
    
    # ── AGREGAR A MEMORIA SEMÁNTICA ─────────────────────────────────────────
    # Guardar mensaje del usuario en ChromaDB para clustering automático
    try:
        memory = create_user_memory(user_id, max_topics=10)
        memory.add_message(
            content=text,
            role="user",
            metadata={"sender": sender_label, "timestamp": current_time}
        )
        logger.debug("[Memoria] Mensaje del usuario agregado a cajón semántico")
    except Exception as mem_exc:
        logger.warning("[Memoria] No se pudo agregar mensaje a memoria semántica: %s", mem_exc)
    
    # Agregar mensaje del usuario al historial (corto plazo)
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
        
        # Llamar a kickoff_conversation() con historial Y user_id para memoria episódica
        history = context.user_data.get("conversation_history", [])
        response = await loop.run_in_executor(
            None,
            crew.kickoff_conversation,
            text,
            history,
            user_id  # Pasar user_id para acceder a memoria episódica
        )
        
        # Agregar respuesta de Nia al historial (corto plazo)
        context.user_data["conversation_history"].append({
            "role": "assistant",
            "content": response,
            "timestamp": time.time()
        })
        
        # AGREGAR respuesta de Nia a memoria semántica (largo plazo)
        try:
            memory = create_user_memory(user_id, max_topics=10)
            memory.add_message(
                content=response,
                role="assistant",
                metadata={"timestamp": time.time()}
            )
            logger.debug("[Memoria] Respuesta de Nia agregada a cajón semántico")
        except Exception as mem_exc:
            logger.warning("[Memoria] No se pudo agregar respuesta a memoria semántica: %s", mem_exc)
        
        # ── RESPONDER CON VOZ si el input fue de voz ────────────────────────────
        input_was_voice = context.user_data.get("input_was_voice", False)
        
        if input_was_voice:
            # Enviar como mensaje de voz
            await update.message.chat.send_action(action=constants.ChatAction.RECORD_VOICE)
            
            audio_path = await _synthesize_voice(response, lang="es")
            
            if audio_path:
                try:
                    with open(audio_path, "rb") as audio_file:
                        await update.message.reply_voice(voice=audio_file)
                    logger.info("🔊 Respuesta enviada como voz")
                except Exception as voice_exc:
                    logger.warning(f"Error enviando voz, fallback a texto: {voice_exc}")
                    await update.message.reply_text(response, parse_mode=None)
                finally:
                    # Limpiar archivo temporal
                    try:
                        os.unlink(audio_path)
                    except:
                        pass
            else:
                # Fallback a texto si falla síntesis
                await update.message.reply_text(response, parse_mode=None)
            
            # Limpiar flag de voz
            context.user_data["input_was_voice"] = False
        else:
            # Respuesta normal de texto
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
    app.add_handler(CommandHandler("topics", _cmd_topics))
    app.add_handler(CommandHandler("recall", _cmd_recall))
    
    # Handlers de mensajes (orden importa: voz antes de texto)
    app.add_handler(MessageHandler(filters.VOICE, _handle_voice))
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
