"""
TelegramChannel — Nia's Telegram adapter.

Migrates and extends src/telegram_bot.py.

New additions vs the original:
  • Delegates intent dispatch to NiaAgent.dispatch()
  • /flujos  — list available flows from flows.yaml
  • /iniciar — dispatch a flow directly by name
  • CallbackQueryHandler for inline email-feedback buttons
  • send() / send_with_buttons() for cross-channel notifications
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, constants
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.nia.channels.base import ChannelAdapter, ChannelConfig
from src.input_sources import ChatMessageInboxTool, EmailInboxTool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class TelegramChannelConfig(ChannelConfig):
    token: str = ""
    mode: str = "conversational"    # "conversational" | "triage_only"
    voice_input: bool = True
    voice_output: bool = True
    notify_chat_id: Optional[int] = None

    @classmethod
    def from_env_and_yaml(cls, yaml_channels: Dict[str, Any]) -> "TelegramChannelConfig":
        tg = yaml_channels.get("telegram", {})
        raw_chat = os.getenv("IMAP_NOTIFY_CHAT_ID", "").strip()
        notify_id = int(raw_chat) if raw_chat.lstrip("-").isdigit() else None
        return cls(
            token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            enabled=tg.get("enabled", True),
            mode=tg.get("mode", "conversational"),
            voice_input=tg.get("voice_input", True),
            voice_output=tg.get("voice_output", True),
            notify_chat_id=notify_id,
        )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WELCOME = """
Hola, soy Nia.

Soy la Analista Estratégica de Triaje de Descorcha. Trabajo en dos modos:

*💬 Modo Conversación*
Pregúntame sobre estrategia, procesos o cualquier duda.

*📊 Modo Triage (análisis formal)*
Cuando quieras que documente y clasifique algo, usa:
• "haz el triage", "clasifica esto", "documenta esto"

*🎤 Mensajes de voz:*
¡Puedes enviarme notas de voz! Las transcribo automáticamente.
Si me hablas por voz, te responderé por voz también.

*Comandos disponibles:*
/flujos  — Ver flujos disponibles
/iniciar — Iniciar un flujo directamente
/nueva   — Limpiar contexto
/topics  — Ver cajones activos
/recall  — Buscar por tema
/status  — Estado del inbox
""".strip()

_HELP = """
*Nia — Analista Estratégica de Triaje*

*Comandos:*
/flujos         — Lista los flujos disponibles
/iniciar [texto]— Despacha un flujo con el texto dado
/nueva          — Limpiar contexto
/topics         — Ver cajones activos
/recall <tema>  — Recuperar conversación sobre un tema
/status         — Estado del inbox
/miid           — Tu chat_id
""".strip()


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

async def _transcribe_voice_message(file_path: str) -> Optional[str]:
    try:
        import whisper, torch, ssl, urllib.request  # noqa: F401

        ssl_context = ssl._create_unverified_context()
        original_opener = urllib.request._opener
        urllib.request.install_opener(
            urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_context))
        )
        try:
            model = whisper.load_model("base")
        finally:
            if original_opener:
                urllib.request.install_opener(original_opener)

        result = model.transcribe(file_path, language="es", fp16=False, verbose=False)
        return result["text"].strip()
    except Exception as exc:
        logger.error("❌ Transcription error: %s", exc)
        return None


async def _synthesize_voice(text: str, lang: str = "es") -> Optional[str]:
    try:
        from gtts import gTTS
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            path = tmp.name
        gTTS(text=text, lang=lang, slow=False).save(path)
        return path
    except Exception as exc:
        logger.error("❌ TTS error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Result formatter (unchanged from telegram_bot.py)
# ---------------------------------------------------------------------------

def _format_result(result: object) -> str:
    from src.triage_crew import TriageDecisionOutput

    def esc(text: str) -> str:
        if not text:
            return ""
        for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
            text = text.replace(ch, f'\\{ch}')
        return text

    r: TriageDecisionOutput = result  # type: ignore[assignment]
    lines = [
        f"*Clasificación:* {r.classification}", "",
        "*Razonamiento:*", esc(r.reasoning[:300]), "",
        f"*De:* {esc(r.email_summary.sender or '—')}",
        f"*Asunto:* {esc(r.email_summary.subject or '—')}",
    ]
    if r.email_summary.key_topics:
        lines.append(f"*Temas:* {', '.join(esc(t) for t in r.email_summary.key_topics[:5])}")
    if r.actions_taken:
        lines += ["", "*Acciones ejecutadas:*"]
        for a in r.actions_taken:
            icon = "✓" if a.status == "ok" else "✗"
            lines.append(f"  {icon} {esc(a.tool)} — {esc(a.details[:120])}")
    if r.pending_approvals:
        lines += ["", "*Pendiente de tu aprobación:*"]
        for item in r.pending_approvals:
            lines.append(f"  • {esc(item)}")
    if r.discarded and r.discard_reason:
        lines += ["", f"*Motivo de descarte:* {esc(r.discard_reason)}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TelegramChannel adapter
# ---------------------------------------------------------------------------

class TelegramChannel(ChannelAdapter):
    """Telegram adapter — conversational + triage + inline feedback."""

    def __init__(self, config: TelegramChannelConfig, nia: Any) -> None:
        super().__init__(config, nia)
        self.config: TelegramChannelConfig = config
        self._app: Optional[Application] = None

    # ------------------------------------------------------------------
    # ChannelAdapter lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Build the Application and start polling (blocks until stopped)."""
        app = self._build_application()
        self._app = app
        logger.info("[TelegramChannel] Starting polling…")
        await app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            close_loop=False,
        )

    async def stop(self) -> None:
        if self._app:
            await self._app.stop()
            self._app = None

    # ------------------------------------------------------------------
    # Output API (used by EmailChannel to send notifications)
    # ------------------------------------------------------------------

    async def send(
        self,
        user_id: str,
        message: str,
        parse_mode: Optional[str] = "Markdown",
    ) -> None:
        if self._app is None:
            logger.warning("[TelegramChannel] send() called before start() — skipping")
            return
        await self._app.bot.send_message(
            chat_id=int(user_id),
            text=message,
            parse_mode=parse_mode,
        )

    async def send_with_buttons(
        self,
        user_id: str,
        message: str,
        buttons: List[Tuple[str, str]],
        parse_mode: Optional[str] = "Markdown",
    ) -> None:
        if self._app is None:
            logger.warning("[TelegramChannel] send_with_buttons() called before start()")
            return
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(label, callback_data=data)] for label, data in buttons]
        )
        await self._app.bot.send_message(
            chat_id=int(user_id),
            text=message,
            reply_markup=keyboard,
            parse_mode=parse_mode,
        )

    # ------------------------------------------------------------------
    # Application builder
    # ------------------------------------------------------------------

    def _build_application(self) -> Application:
        """Construct and configure the python-telegram-bot Application."""
        app = Application.builder().token(self.config.token).build()

        # Store references
        app.bot_data["nia"] = self.nia
        app.bot_data["crew"] = self.nia.crew  # backward compat

        # Commands
        app.add_handler(CommandHandler("start",   self._cmd_start))
        app.add_handler(CommandHandler("help",    self._cmd_help))
        app.add_handler(CommandHandler("status",  self._cmd_status))
        app.add_handler(CommandHandler("miid",    self._cmd_miid))
        app.add_handler(CommandHandler("nueva",   self._cmd_nueva))
        app.add_handler(CommandHandler("topics",  self._cmd_topics))
        app.add_handler(CommandHandler("recall",  self._cmd_recall))
        app.add_handler(CommandHandler("flujos",  self._cmd_flujos))
        app.add_handler(CommandHandler("iniciar", self._cmd_iniciar))

        # Inline button callbacks (email feedback)
        app.add_handler(CallbackQueryHandler(self._handle_callback))

        # Message handlers (voice before text)
        if self.config.voice_input:
            app.add_handler(MessageHandler(filters.VOICE, self._handle_voice))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

        return app

    # ------------------------------------------------------------------
    # New commands
    # ------------------------------------------------------------------

    async def _cmd_flujos(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """List available flows from flows.yaml."""
        flows = self.nia.get_flows()
        if not flows:
            await update.message.reply_text(
                "No hay flujos configurados aún. Agrégalos en `config/flows.yaml`.",
                parse_mode=constants.ParseMode.MARKDOWN,
            )
            return

        lines = ["📋 *Flujos disponibles:*\n"]
        for f in flows:
            fid = f.get("id", "?")
            name = f.get("name", fid)
            desc = f.get("description", "")
            lines.append(f"• `{fid}` — *{name}*")
            if desc:
                lines.append(f"  _{desc}_")
        lines.append("\nUsa `/iniciar <texto>` para ejecutar el flujo por defecto.")

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=constants.ParseMode.MARKDOWN,
        )

    async def _cmd_iniciar(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Dispatch the default flow with the provided text."""
        text = update.message.text or ""
        parts = text.split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else ""

        if not payload:
            await update.message.reply_text(
                "Uso: `/iniciar <descripción o texto a analizar>`\n\n"
                "Ejemplo: `/iniciar Propuesta de integración con SAP`",
                parse_mode=constants.ParseMode.MARKDOWN,
            )
            return

        msg = await update.message.reply_text(
            "_⏳ Iniciando flujo…_",
            parse_mode=constants.ParseMode.MARKDOWN,
        )

        user_id = str(update.effective_user.id)
        from src.conversation_memory import create_user_memory
        memory = create_user_memory(user_id, max_topics=self.nia.config.memory_max_topics)
        dispatch = self.nia.dispatch(f"/iniciar {payload}", user_id, memory)

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.nia.run_flow, dispatch.flow_id, dispatch.input_text
            )
            reply = _format_result(result)
            try:
                await msg.edit_text(reply, parse_mode=constants.ParseMode.MARKDOWN)
            except Exception:
                await msg.edit_text(reply, parse_mode=None)
        except Exception as exc:
            logger.exception("[TelegramChannel] /iniciar error")
            await msg.edit_text(f"❌ Error: `{exc}`", parse_mode=constants.ParseMode.MARKDOWN)

    # ------------------------------------------------------------------
    # Existing commands (unchanged logic, now methods of the class)
    # ------------------------------------------------------------------

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(_WELCOME, parse_mode=constants.ParseMode.MARKDOWN)

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(_HELP, parse_mode=constants.ParseMode.MARKDOWN)

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        email_pending = EmailInboxTool.pending_count()
        chat_pending = ChatMessageInboxTool.pending_count()
        imap_user = os.getenv("IMAP_USER", "").strip()
        imap_status = f"`{imap_user}`" if imap_user else "_(no configurado)_"
        await update.message.reply_text(
            f"📊 *Estado del inbox*\n"
            f"  📧 Email: {email_pending} pendiente(s) | cuenta: {imap_status}\n"
            f"  💬 Chat:  {chat_pending} pendiente(s)",
            parse_mode=constants.ParseMode.MARKDOWN,
        )

    async def _cmd_miid(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    async def _cmd_nueva(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        context.user_data["conversation_history"] = []
        context.user_data.pop("last_message_time", None)
        await update.message.reply_text("Listo, contexto limpiado. ¿En qué te puedo ayudar?")

    async def _cmd_topics(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = str(update.effective_user.id)
        try:
            from src.conversation_memory import create_user_memory
            memory = create_user_memory(user_id, max_topics=self.nia.config.memory_max_topics)
            topics = memory.get_topics_summary()
            if not topics:
                await update.message.reply_text(
                    "🗂️ No hay cajones activos aún.",
                    parse_mode=constants.ParseMode.MARKDOWN,
                )
                return
            lines = ["🗂️ *Cajones activos de memoria:*\n"]
            for i, (label, count) in enumerate(topics, 1):
                lines.append(f"{i}. `{label}` — {count} mensajes")
            lines.append("\n💡 Usa `/recall <tema>` para recuperar un cajón específico")
            await update.message.reply_text("\n".join(lines), parse_mode=constants.ParseMode.MARKDOWN)
        except Exception as exc:
            await update.message.reply_text(f"Error: `{exc}`", parse_mode=constants.ParseMode.MARKDOWN)

    async def _cmd_recall(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = str(update.effective_user.id)
        text = update.message.text or ""
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ Uso: `/recall <tema>`", parse_mode=constants.ParseMode.MARKDOWN
            )
            return
        query = parts[1].strip()
        try:
            from src.conversation_memory import create_user_memory
            memory = create_user_memory(user_id, max_topics=self.nia.config.memory_max_topics)
            ctx = memory.get_context_for_triage(query=query, max_messages=10)
            if not ctx:
                await update.message.reply_text(
                    f"🔍 No encontré conversaciones sobre: `{query}`",
                    parse_mode=constants.ParseMode.MARKDOWN,
                )
                return
            response = f"🧠 *Recuerdos sobre: {query}*\n\n{ctx}"
            if len(response) > 4000:
                response = response[:4000] + "\n\n...(truncado)"
            await update.message.reply_text(response, parse_mode=constants.ParseMode.MARKDOWN)
        except Exception as exc:
            await update.message.reply_text(f"Error: `{exc}`", parse_mode=constants.ParseMode.MARKDOWN)

    # ------------------------------------------------------------------
    # Inline callback handler (email feedback buttons)
    # ------------------------------------------------------------------

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline keyboard button presses from email feedback messages."""
        query = update.callback_query
        await query.answer()

        data = query.data or ""
        logger.info("[TelegramChannel] Callback: %s", data)

        # Expected format: "email_action:<action>:<message_id>"
        if not data.startswith("email_action:"):
            return

        parts = data.split(":", 2)
        if len(parts) < 3:
            return

        _, action, message_id = parts

        if action == "discard":
            await query.edit_message_text("🗑️ Email ignorado.")
            return

        if action == "save":
            await query.edit_message_text("🔔 Email guardado en memoria.")
            # TODO: actually save to ChromaDB
            return

        if action.startswith("flow:") or action == "strategy_crew":
            flow_id = action.replace("flow:", "") if action.startswith("flow:") else action
            # Retrieve the pending email payload stored in bot_data
            pending = context.bot_data.get("pending_email_actions", {})
            email_data = pending.get(message_id, {})

            payload = email_data.get("summary", f"Email ID: {message_id}")
            await query.edit_message_text(f"📋 Iniciando flujo `{flow_id}`…")

            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, self.nia.run_flow, flow_id, payload
                )
                reply = _format_result(result)
                await query.edit_message_text(reply, parse_mode=constants.ParseMode.MARKDOWN)
            except Exception as exc:
                logger.exception("[TelegramChannel] Callback flow error")
                await query.edit_message_text(f"❌ Error ejecutando flujo: `{exc}`")

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        text = update.message.text or ""
        if not text.strip():
            await update.message.reply_text("Mensaje vacío.")
            return
        sender_label = f"@{user.username}" if user.username else f"tg:{user.id}"
        await self._process_text(update, context, text, sender_label)

    async def _handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        voice = update.message.voice
        sender_label = f"@{user.username}" if user.username else f"tg:{user.id}"

        msg = await update.message.reply_text("🎤 Transcribiendo…")

        try:
            import tempfile

            file = await context.bot.get_file(voice.file_id)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
                tmp_path = tmp.name
            await file.download_to_drive(tmp_path)

            transcription = await _transcribe_voice_message(tmp_path)
            os.unlink(tmp_path)

            if not transcription:
                await msg.edit_text("❌ No pude transcribir el audio.")
                return

            await msg.edit_text(
                f"🎤 *Transcripción:*\n\n_{transcription}_\n\n⏳ Procesando…",
                parse_mode=constants.ParseMode.MARKDOWN,
            )
            context.user_data["input_was_voice"] = True
            await self._process_text(update, context, transcription, sender_label, processing_msg=msg)
        except Exception as exc:
            logger.error("Voice handler error: %s", exc)
            await msg.edit_text(f"❌ Error procesando audio: `{str(exc)[:100]}`")

    async def _process_text(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        text: str,
        sender_label: str,
        processing_msg=None,
    ) -> None:
        """Central dispatch: decide conversational vs flow via NiaAgent."""
        user_id = str(update.effective_user.id)

        from src.conversation_memory import create_user_memory
        memory = create_user_memory(user_id, max_topics=self.nia.config.memory_max_topics)
        history = context.user_data.get("conversation_history", [])

        dispatch = self.nia.dispatch(text, user_id, memory, history)

        if dispatch.is_conversational:
            await self._reply_conversational(update, context, text, sender_label, memory, processing_msg)
        else:
            await self._reply_flow(update, context, dispatch, processing_msg)

    async def _reply_conversational(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        text: str,
        sender_label: str,
        memory,
        processing_msg=None,
    ) -> None:
        user_id = str(update.effective_user.id)
        current_time = time.time()

        # Auto-cleanup after 10 min inactivity
        if "conversation_history" not in context.user_data:
            context.user_data["conversation_history"] = []
        last_time = context.user_data.get("last_message_time", current_time)
        if current_time - last_time > 600:
            context.user_data["conversation_history"] = []
        context.user_data["last_message_time"] = current_time

        # Store in semantic memory
        try:
            memory.add_message(content=text, role="user", metadata={"sender": sender_label, "ts": current_time})
        except Exception:
            pass

        # Append to short-term history
        context.user_data["conversation_history"].append({"role": "user", "content": text, "timestamp": current_time})
        if len(context.user_data["conversation_history"]) > 10:
            context.user_data["conversation_history"] = context.user_data["conversation_history"][-10:]

        # Show typing
        await update.message.chat.send_action(action=constants.ChatAction.TYPING)

        try:
            crew = self.nia.crew
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, crew.kickoff_conversation, text, context.user_data["conversation_history"], user_id
            )

            context.user_data["conversation_history"].append({"role": "assistant", "content": response, "timestamp": time.time()})
            try:
                memory.add_message(content=response, role="assistant", metadata={"ts": time.time()})
            except Exception:
                pass

            input_was_voice = context.user_data.get("input_was_voice", False)
            if input_was_voice and self.config.voice_output:
                audio_path = await _synthesize_voice(response)
                if audio_path:
                    await update.message.chat.send_action(action=constants.ChatAction.RECORD_VOICE)
                    with open(audio_path, "rb") as af:
                        await update.message.reply_voice(voice=af)
                    os.unlink(audio_path)
                else:
                    await update.message.reply_text(response)
                context.user_data["input_was_voice"] = False
            else:
                if processing_msg:
                    try:
                        await processing_msg.delete()
                    except Exception:
                        pass
                await update.message.reply_text(response)

        except Exception as exc:
            logger.exception("[TelegramChannel] Conversational error")
            await update.message.reply_text(
                "Entiendo. ¿Quieres que proceda con el análisis formal? Responde *'Sí'*.",
                parse_mode=constants.ParseMode.MARKDOWN,
            )

    async def _reply_flow(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        dispatch,
        processing_msg=None,
    ) -> None:
        if not processing_msg:
            processing_msg = await update.message.reply_text(
                "_Analizando con contexto completo…_",
                parse_mode=constants.ParseMode.MARKDOWN,
            )

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.nia.run_flow, dispatch.flow_id, dispatch.input_text
            )
            reply = _format_result(result)

            input_was_voice = context.user_data.get("input_was_voice", False)
            if input_was_voice and self.config.voice_output:
                from src.triage_crew import TriageDecisionOutput
                r: TriageDecisionOutput = result
                audio_text = f"He analizado tu mensaje. {r.reasoning[:500]}"
                try:
                    await processing_msg.edit_text(reply, parse_mode=constants.ParseMode.MARKDOWN)
                except Exception:
                    await processing_msg.edit_text(reply, parse_mode=None)
                audio_path = await _synthesize_voice(audio_text)
                if audio_path:
                    await update.message.chat.send_action(action=constants.ChatAction.RECORD_VOICE)
                    with open(audio_path, "rb") as af:
                        await update.message.reply_voice(voice=af)
                    os.unlink(audio_path)
                context.user_data["input_was_voice"] = False
            else:
                try:
                    await processing_msg.edit_text(reply, parse_mode=constants.ParseMode.MARKDOWN)
                except Exception:
                    await processing_msg.edit_text(reply, parse_mode=None)

            context.user_data["conversation_history"] = []

        except Exception as exc:
            logger.exception("[TelegramChannel] Flow execution error")
            err = str(exc)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                msg = "⚠️ *Límite de API alcanzado.* Espera unos segundos e intenta de nuevo."
            else:
                safe = err[:200].replace('_', '\\_').replace('*', '\\*')
                msg = f"❌ Error: `{safe}`"
            try:
                await processing_msg.edit_text(msg, parse_mode=constants.ParseMode.MARKDOWN)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Convenience runner (backward compat)
# ---------------------------------------------------------------------------

def run_bot(token: Optional[str] = None, nia=None) -> None:
    """Start the Telegram bot.  Blocks until Ctrl+C."""
    load_dotenv()
    from pathlib import Path
    import yaml as _yaml

    bot_token = token or os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise EnvironmentError("TELEGRAM_BOT_TOKEN not set in .env")

    # Load nia config if not provided
    if nia is None:
        from src.nia.agent import NiaAgent, NiaConfig
        from src.triage_crew import TriageCrew
        nia_cfg = NiaConfig.from_yaml()
        nia = NiaAgent(config=nia_cfg, crew=TriageCrew())

    # Load channel config from nia.yaml
    nia_yaml = Path(__file__).parent.parent.parent.parent / "config" / "nia.yaml"
    channels_raw: Dict[str, Any] = {}
    if nia_yaml.exists():
        with open(nia_yaml) as fh:
            channels_raw = (_yaml.safe_load(fh) or {}).get("channels", {})

    cfg = TelegramChannelConfig.from_env_and_yaml(channels_raw)
    cfg.token = bot_token

    channel = TelegramChannel(config=cfg, nia=nia)
    asyncio.run(channel.start())


__all__ = ["TelegramChannel", "TelegramChannelConfig", "run_bot"]
