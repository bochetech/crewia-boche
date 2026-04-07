"""
EmailChannel — Nia's email adapter.

Migrates and extends src/email_watcher.py with a 3-step pipeline:
  1. classify  — spam | notification | important | analyzable
  2. summarize — executive summary via NiaAgent
  3. notify + ask feedback via Telegram inline buttons (if analyzable)
  4. execute   — run flow if user confirmed

Configuration via config/nia.yaml → channels.email
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.nia.channels.base import ChannelAdapter, ChannelConfig
from src.nia.agent import EmailClassification

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class EmailPipelineOption:
    label: str
    action: str             # "dispatch_flow" | "save_to_memory" | "discard"
    flow: Optional[str] = None


@dataclass
class EmailPipelineStep:
    step: str               # classify | summarize | notify_telegram | ask_feedback | execute
    discard_if: List[str] = field(default_factory=list)
    if_condition: Optional[str] = None
    format: Optional[str] = None
    options: List[EmailPipelineOption] = field(default_factory=list)


@dataclass
class EmailChannelConfig(ChannelConfig):
    poll_interval_seconds: int = 60
    notify_chat_id: Optional[int] = None    # Telegram chat to forward results
    pipeline: List[EmailPipelineStep] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, yaml_channels: Dict[str, Any]) -> "EmailChannelConfig":
        em = yaml_channels.get("email", {})

        raw_chat = os.getenv("IMAP_NOTIFY_CHAT_ID", "").strip()
        notify_id = int(raw_chat) if raw_chat.lstrip("-").isdigit() else None

        steps: List[EmailPipelineStep] = []
        for raw_step in em.get("pipeline", []):
            options = [
                EmailPipelineOption(
                    label=o.get("label", ""),
                    action=o.get("action", "discard"),
                    flow=o.get("flow"),
                )
                for o in raw_step.get("options", [])
            ]
            steps.append(EmailPipelineStep(
                step=raw_step.get("step", ""),
                discard_if=raw_step.get("discard_if", []),
                if_condition=raw_step.get("if"),
                format=raw_step.get("format"),
                options=options,
            ))

        return cls(
            enabled=em.get("enabled", False),
            poll_interval_seconds=int(em.get("poll_interval_seconds", 60)),
            notify_chat_id=notify_id,
            pipeline=steps,
        )


# ---------------------------------------------------------------------------
# EmailChannel adapter
# ---------------------------------------------------------------------------

class EmailChannel(ChannelAdapter):
    """
    Email channel adapter with classify → summarize → notify → execute pipeline.

    Parameters
    ----------
    config:
        EmailChannelConfig instance.
    nia:
        NiaAgent — used for classify_email() and summarize().
    telegram_channel:
        TelegramChannel — used to send notifications and inline buttons.
        Can be None; notifications are skipped when not available.
    """

    def __init__(
        self,
        config: EmailChannelConfig,
        nia: Any,
        telegram_channel: Optional[Any] = None,
    ) -> None:
        super().__init__(config, nia)
        self.config: EmailChannelConfig = config
        self.telegram_channel = telegram_channel
        self._running = False

    # ------------------------------------------------------------------
    # ChannelAdapter lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        imap_user = os.getenv("IMAP_USER", "").strip()
        if not imap_user:
            logger.warning(
                "[EmailChannel] IMAP_USER not set — email channel disabled. "
                "Configure IMAP credentials in .env to enable it."
            )
            return

        if not self.config.enabled:
            logger.info("[EmailChannel] Disabled via config — skipping.")
            return

        logger.info(
            "[EmailChannel] Starting. Account: %s | Poll: %ds",
            imap_user,
            self.config.poll_interval_seconds,
        )
        self._running = True
        await self._polling_loop()

    async def stop(self) -> None:
        self._running = False

    # Email channel is notification-only (no inbound from us to email users)
    async def send(self, user_id: str, message: str, parse_mode: Optional[str] = None) -> None:
        logger.debug("[EmailChannel] send() not applicable for email — ignoring.")

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    async def _polling_loop(self) -> None:
        from src.input_sources import EmailInboxTool  # lazy import

        while self._running:
            try:
                count = EmailInboxTool.fetch_from_imap()
                if count:
                    logger.info("[EmailChannel] %d new email(s) fetched.", count)
                    await self._process_pending()
            except RuntimeError as exc:
                logger.error("[EmailChannel] IMAP error: %s", exc)
            except asyncio.CancelledError:
                logger.info("[EmailChannel] Polling loop cancelled.")
                return
            except Exception as exc:
                logger.exception("[EmailChannel] Unexpected error: %s", exc)

            await asyncio.sleep(self.config.poll_interval_seconds)

    async def _process_pending(self) -> None:
        from src.input_sources import EmailInboxTool  # lazy import

        pending = [m for m in EmailInboxTool._queue if not m.read]
        for msg in pending:
            msg.read = True
            try:
                await self._run_pipeline(msg)
            except Exception as exc:
                logger.exception("[EmailChannel] Pipeline error for message %s: %s", msg.message_id, exc)

    # ------------------------------------------------------------------
    # 3-step pipeline
    # ------------------------------------------------------------------

    async def _run_pipeline(self, msg) -> None:
        """
        Execute the configured pipeline steps for one email message.

        Steps (from config/nia.yaml):
          classify → summarize → notify_telegram → ask_feedback → execute
        """
        logger.info(
            "[EmailChannel] Processing email from %s | Subject: %s",
            msg.sender,
            msg.subject,
        )

        # ── Step 1: Classify ────────────────────────────────────────────────
        classification = self.nia.classify_email(
            sender=msg.sender or "",
            subject=msg.subject or "",
            body=msg.body or "",
        )
        logger.info("[EmailChannel] Classification: %s", classification)

        # Check discard_if rules from config
        for step_cfg in self.config.pipeline:
            if step_cfg.step == "classify":
                if classification.value in step_cfg.discard_if:
                    logger.info(
                        "[EmailChannel] Discarding email (%s matches discard_if).", classification
                    )
                    return

        # ── Step 2: Summarize ───────────────────────────────────────────────
        summary = self.nia.summarize(
            text=f"Asunto: {msg.subject}\n\nDe: {msg.sender}\n\n{msg.body or ''}",
            max_chars=300,
        )

        # ── Step 3: Notify Telegram ─────────────────────────────────────────
        notify_chat = str(self.config.notify_chat_id) if self.config.notify_chat_id else None

        if notify_chat and self.telegram_channel is not None:
            # Find the notify format from config
            notify_format = "📨 Email de {sender}: {summary}"
            for step_cfg in self.config.pipeline:
                if step_cfg.step == "notify_telegram" and step_cfg.format:
                    notify_format = step_cfg.format
                    break

            notification = notify_format.format(
                sender=msg.sender or "?",
                subject=msg.subject or "(sin asunto)",
                summary=summary,
            )
            await self.telegram_channel.send(
                notify_chat,
                notification,
                parse_mode="Markdown",
            )

            # ── Step 4: Ask feedback if analyzable ──────────────────────────
            if classification == EmailClassification.ANALYZABLE:
                buttons = self._build_feedback_buttons(msg.message_id)
                if buttons and self.telegram_channel is not None:
                    # Store email data so callback can access summary
                    if hasattr(self.telegram_channel, "_app") and self.telegram_channel._app:
                        self.telegram_channel._app.bot_data.setdefault("pending_email_actions", {})[
                            str(msg.message_id)
                        ] = {"summary": summary, "sender": msg.sender, "subject": msg.subject}

                    await self.telegram_channel.send_with_buttons(
                        notify_chat,
                        "¿Qué hago con este email?",
                        buttons,
                        parse_mode="Markdown",
                    )
        else:
            # No Telegram available — run default flow directly
            if classification in (EmailClassification.ANALYZABLE, EmailClassification.IMPORTANT):
                logger.info(
                    "[EmailChannel] No Telegram channel — running default flow for email from %s",
                    msg.sender,
                )
                loop = asyncio.get_event_loop()
                triage_text = msg.to_triage_text() if hasattr(msg, "to_triage_text") else str(msg)
                try:
                    result = await loop.run_in_executor(
                        None, self.nia.run_flow, self.nia.config.default_flow, triage_text
                    )
                    logger.info("[EmailChannel] Flow result: %s", str(result)[:200])
                except Exception as exc:
                    logger.error("[EmailChannel] Flow execution failed: %s", exc)

    def _build_feedback_buttons(self, message_id: Any):
        """Build inline button list from pipeline ask_feedback config."""
        default_buttons = [
            ("📋 Registrar iniciativa", f"email_action:flow:{self.nia.config.default_flow}:{message_id}"),
            ("🔔 Solo guardar", f"email_action:save:{message_id}"),
            ("🗑️ Ignorar", f"email_action:discard:{message_id}"),
        ]

        for step_cfg in self.config.pipeline:
            if step_cfg.step == "ask_feedback" and step_cfg.options:
                configured = []
                for opt in step_cfg.options:
                    if opt.action == "dispatch_flow":
                        flow = opt.flow or self.nia.config.default_flow
                        configured.append(
                            (opt.label, f"email_action:flow:{flow}:{message_id}")
                        )
                    elif opt.action == "save_to_memory":
                        configured.append(
                            (opt.label, f"email_action:save:{message_id}")
                        )
                    elif opt.action == "discard":
                        configured.append(
                            (opt.label, f"email_action:discard:{message_id}")
                        )
                return configured or default_buttons

        return default_buttons


__all__ = ["EmailChannel", "EmailChannelConfig", "EmailPipelineStep", "EmailPipelineOption"]
