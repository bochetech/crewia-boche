"""
Email Watcher — background polling loop for IMAP inbox.

Runs as an ``asyncio`` task alongside the Telegram bot.  Every
``IMAP_POLL_INTERVAL`` seconds it calls ``EmailInboxTool.fetch_from_imap()``
to pull UNSEEN messages from the configured Gmail / IMAP account.

For each new message it immediately kicks off a triage run in a thread
executor (so the async event loop isn't blocked) and, when enabled, sends
the triage result back to a Telegram chat.

Usage (standalone)
------------------
    from src.email_watcher import start_email_watcher
    asyncio.run(start_email_watcher())          # loops forever

Integration with the Telegram bot (see main.py)
-----------------------------------------------
    asyncio.get_event_loop().create_task(
        start_email_watcher(crew=crew, notify_chat_id=ADMIN_CHAT_ID, bot=bot)
    )
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


async def start_email_watcher(
    crew=None,                         # TriageCrew instance (optional)
    notify_chat_id: Optional[int] = None,  # Telegram chat_id to forward results
    bot=None,                          # telegram.Bot instance
    poll_interval: Optional[int] = None,
) -> None:
    """Async polling loop.  Runs until cancelled.

    Parameters
    ----------
    crew:
        A ``TriageCrew`` instance.  If None the watcher only fetches and
        enqueues messages without running triage — useful for testing.
    notify_chat_id:
        If provided (and ``bot`` is set), each triage result is sent to this
        Telegram chat.  This is usually the admin / owner chat.
    bot:
        A ``telegram.Bot`` instance used to send result notifications.
    poll_interval:
        Seconds between IMAP polls.  Defaults to ``IMAP_POLL_INTERVAL`` env
        var, or 60 seconds.
    """
    # Lazy imports so the module can be imported in test environments where
    # crewai / telegram are absent.
    from src.input_sources import EmailInboxTool, message_to_triage_text  # noqa: PLC0415

    interval = poll_interval or int(os.environ.get("IMAP_POLL_INTERVAL", "60"))
    imap_user = os.environ.get("IMAP_USER", "").strip()

    if not imap_user:
        logger.warning(
            "[EmailWatcher] IMAP_USER is not set — email watcher is disabled. "
            "Configure IMAP credentials in .env to enable it."
        )
        return

    logger.info(
        "[EmailWatcher] Starting. Account: %s | Poll interval: %ds", imap_user, interval
    )

    while True:
        try:
            count = EmailInboxTool.fetch_from_imap()
            if count:
                logger.info("[EmailWatcher] %d new email(s) fetched from IMAP.", count)

                if crew is not None:
                    await _run_triage_for_pending(
                        crew=crew,
                        notify_chat_id=notify_chat_id,
                        bot=bot,
                    )

        except RuntimeError as exc:
            # Missing credentials or connection failure — log and keep retrying
            logger.error("[EmailWatcher] %s", exc)
        except asyncio.CancelledError:
            logger.info("[EmailWatcher] Stopped.")
            return
        except Exception as exc:  # pragma: no cover
            logger.exception("[EmailWatcher] Unexpected error: %s", exc)

        await asyncio.sleep(interval)


async def _run_triage_for_pending(crew, notify_chat_id, bot) -> None:
    """Process all pending EmailInboxTool messages through the triage crew."""
    from src.input_sources import EmailInboxTool, message_to_triage_text  # noqa: PLC0415

    loop = asyncio.get_event_loop()
    pending = [m for m in EmailInboxTool._queue if not m.read]

    for msg in pending:
        triage_text = msg.to_triage_text()
        msg.read = True  # mark before dispatching to avoid double-processing

        logger.info(
            "[EmailWatcher] Triaging email from %s | Subject: %s",
            msg.sender,
            msg.subject,
        )

        try:
            result = await loop.run_in_executor(
                None, crew.kickoff, triage_text
            )
        except Exception as exc:  # pragma: no cover
            logger.error("[EmailWatcher] Triage failed for message %s: %s", msg.message_id, exc)
            result = None

        if result is not None and bot is not None and notify_chat_id is not None:
            await _notify_telegram(bot, notify_chat_id, msg, result)


async def _notify_telegram(bot, chat_id: int, msg, result) -> None:
    """Send a triage result summary to a Telegram chat."""
    try:
        from src.triage_crew import TriageDecisionOutput  # noqa: PLC0415

        header = (
            f"📨 *Correo triado por Nia*\n"
            f"De: `{msg.sender}`\n"
            f"Asunto: _{msg.subject}_\n\n"
        )

        if isinstance(result, TriageDecisionOutput):
            icon = "🟢" if result.classification == "STRATEGIC" else "🔴"
            body = (
                f"{icon} *{result.classification}*\n\n"
                f"_{result.reasoning}_"
            )
        else:
            body = str(result)

        await bot.send_message(
            chat_id=chat_id,
            text=header + body,
            parse_mode="Markdown",
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("[EmailWatcher] Could not send Telegram notification: %s", exc)
