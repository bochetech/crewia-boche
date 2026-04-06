"""
Input Source Tools for the Triage Analytical Pipeline.

These tools give the triage agent the ability to *read* pending messages from
two inbound channels:

  - EmailInboxTool      : Reads emails via IMAP (Gmail, Outlook, etc.).
                          Configure IMAP_HOST / IMAP_USER / IMAP_PASSWORD in .env.
                          Falls back to in-memory queue when env vars are absent
                          (used in tests and CLI demo).

  - ChatMessageInboxTool: Simulates a Telegram / Slack message queue.
                          In production the Telegram bot feeds messages directly
                          via ChatMessageInboxTool.enqueue().

Design principles
-----------------
* Both tools follow the same crewai BaseTool pattern as the output tools in
  tools.py (Pydantic instance fields for name/description, args_schema,
  _run(**kwargs)).
* Messages are queued in a ClassVar in-memory store so they work standalone
  in tests and in the CLI demo without any external dependency.
* The public class methods ``EmailInboxTool.enqueue()`` and
  ``ChatMessageInboxTool.enqueue()`` let any code (CLI, tests, webhooks)
  push new messages into the inbox before the agent polls it.
* Each message is marked as ``read=True`` after the agent retrieves it so
  repeated polls don't re-process the same message.
* ``EmailInboxTool.fetch_from_imap()`` connects to a real IMAP server,
  fetches UNSEEN messages, marks them as SEEN and enqueues them.

IMAP setup (Gmail)
------------------
1. Crea o usa una cuenta Gmail dedicada (ej: nia.triage@gmail.com).
2. Activa acceso IMAP: Gmail → Ajustes → Ver todos → Reenvío e IMAP → Habilitar IMAP.
3. Genera una App Password: cuenta.google.com → Seguridad → Contraseñas de aplicación.
4. Agrega al .env:
       IMAP_HOST=imap.gmail.com
       IMAP_PORT=993
       IMAP_USER=nia.triage@gmail.com
       IMAP_PASSWORD=xxxx xxxx xxxx xxxx   # App Password (16 chars)
       IMAP_FOLDER=INBOX
       IMAP_POLL_INTERVAL=60               # segundos entre polls
5. Reenvía cualquier correo a nia.triage@gmail.com → Nia lo procesará.

Usage (standalone, no crewai)
------------------------------
    from src.input_sources import EmailInboxTool, ChatMessageInboxTool

    EmailInboxTool.enqueue(
        sender="vendor@saas.io",
        subject="Propuesta Shopify",
        body="Queremos integrar Shopify con Bókun...",
    )
    tool = EmailInboxTool()
    print(tool.run(max_messages=5))

Usage (inside crewai agent)
-----------------------------
    # The agent calls the tool autonomously when polling for new work.
    # The TriageCrew wires both tools into the agent's tool list.
"""
from __future__ import annotations

import email as _emaillib
import imaplib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from email.header import decode_header as _decode_header
from typing import Any, ClassVar, Dict, List, Optional, Type

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BaseTool resolution (same pattern as tools.py)
# ---------------------------------------------------------------------------
try:
    from crewai.tools import BaseTool as _CrewBaseTool  # type: ignore
    _BASE = _CrewBaseTool
    _CREWAI_AVAILABLE = True
except Exception:
    _CREWAI_AVAILABLE = False

    class _BASE:  # type: ignore
        """Fallback base — used when crewai is not installed."""
        name: str = ""
        description: str = ""
        args_schema: Optional[Any] = None

        def _run(self, **kwargs: Any) -> Any:
            raise NotImplementedError

        def run(self, **kwargs: Any) -> Any:
            if self.args_schema is not None:
                validated = self.args_schema(**kwargs)
                kwargs = validated.model_dump()
            return self._run(**kwargs)


# ===========================================================================
# Internal message dataclass
# ===========================================================================

class _InboxMessage:
    """Lightweight internal message record stored in the ClassVar queue."""

    def __init__(
        self,
        *,
        message_id: str,
        channel: str,
        sender: str,
        subject: str,
        body: str,
        received_at: str,
    ) -> None:
        self.message_id = message_id
        self.channel = channel
        self.sender = sender
        self.subject = subject
        self.body = body
        self.received_at = received_at
        self.read: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "channel": self.channel,
            "sender": self.sender,
            "subject": self.subject,
            "body": self.body,
            "received_at": self.received_at,
        }

    def to_triage_text(self) -> str:
        """Format the message as the raw text the triage agent expects."""
        return (
            f"De: {self.sender}\n"
            f"Asunto: {self.subject}\n"
            f"Canal: {self.channel}\n"
            f"Recibido: {self.received_at}\n\n"
            f"{self.body}"
        )


# ===========================================================================
# MIME helpers (used by EmailInboxTool.fetch_from_imap)
# ===========================================================================

def _decode_mime_words(raw: str) -> str:
    """Decode RFC-2047 encoded header values (e.g. =?utf-8?b?...?=)."""
    parts = _decode_header(raw)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _extract_body(msg: _emaillib.message.Message) -> str:
    """Extract plain-text body from a parsed email.Message.

    Priority: text/plain → text/html (stripped) → fallback notice.
    Handles multipart/alternative and multipart/mixed recursively.
    """
    plain: Optional[str] = None
    html: Optional[str] = None

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp:
                continue
            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            text = payload.decode(charset, errors="replace")
            if ct == "text/plain" and plain is None:
                plain = text
            elif ct == "text/html" and html is None:
                html = _strip_html(text)
    else:
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload:
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html = _strip_html(text)
            else:
                plain = text

    return (plain or html or "(sin cuerpo)").strip()


def _strip_html(html: str) -> str:
    """Very lightweight HTML → plain text: remove tags, decode entities."""
    import re
    import html as _html_module
    text = re.sub(r"<[^>]+>", " ", html)
    text = _html_module.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ===========================================================================
# 1. EmailInboxTool
# ===========================================================================

class EmailInboxInput(BaseModel):
    """Input schema for EmailInboxTool."""
    max_messages: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of unread messages to retrieve (1–50).",
    )
    mark_as_read: bool = Field(
        default=True,
        description="If true, retrieved messages are marked as read so they won't be returned again.",
    )


class EmailInboxTool(_BASE):
    """Retrieve unread e-mails from the inbox queue.

    The agent calls this tool to fetch pending emails before deciding how to
    process each one.  In production, override ``_fetch_from_server`` with
    real IMAP / Gmail API logic.

    Enqueue messages from outside (CLI, tests, webhooks):
        EmailInboxTool.enqueue(sender="x@y.com", subject="...", body="...")
    """
    name: str = "email_inbox"
    description: str = (
        "Reads unread e-mails from the inbox. Returns a JSON list of messages, "
        "each with sender, subject, body and metadata. Call this before processing "
        "any email triage task to fetch the latest pending messages."
    )
    args_schema: Type[BaseModel] = EmailInboxInput

    # Shared in-memory inbox — populated via enqueue(), cleared in tests
    _queue: ClassVar[List[_InboxMessage]] = []

    # ------------------------------------------------------------------
    # Public API for enqueuing messages (CLI / tests / webhooks)
    # ------------------------------------------------------------------
    @classmethod
    def enqueue(
        cls,
        sender: str,
        subject: str,
        body: str,
        received_at: Optional[str] = None,
    ) -> str:
        """Add an e-mail to the inbox queue. Returns the new message_id."""
        msg = _InboxMessage(
            message_id=str(uuid.uuid4()),
            channel="email",
            sender=sender,
            subject=subject,
            body=body,
            received_at=received_at or datetime.now(timezone.utc).isoformat(),
        )
        cls._queue.append(msg)
        logger.info("[EmailInboxTool] Enqueued email from %s | Subject: %s", sender, subject)
        return msg.message_id

    @classmethod
    def pending_count(cls) -> int:
        """Return the number of unread messages in the queue."""
        return sum(1 for m in cls._queue if not m.read)

    @classmethod
    def clear(cls) -> None:
        """Empty the queue (used in tests)."""
        cls._queue.clear()

    # ------------------------------------------------------------------
    # crewai _run
    # ------------------------------------------------------------------
    def _run(self, **kwargs: Any) -> str:
        try:
            inp = EmailInboxInput(**kwargs)
        except Exception as exc:
            return json.dumps({"status": "error", "message": f"Invalid input: {exc}"})

        try:
            unread = [m for m in self._queue if not m.read]
            batch = unread[: inp.max_messages]

            if inp.mark_as_read:
                for m in batch:
                    m.read = True

            result = {
                "status": "ok",
                "channel": "email",
                "count": len(batch),
                "messages": [m.to_dict() for m in batch],
            }
            logger.info("[EmailInboxTool] Retrieved %d email(s)", len(batch))
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as exc:
            logger.exception("[EmailInboxTool] Unexpected error")
            return json.dumps({"status": "error", "message": str(exc)})

    # ------------------------------------------------------------------
    # Production hook — IMAP real connection
    # ------------------------------------------------------------------
    @classmethod
    def fetch_from_imap(
        cls,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        folder: str = "INBOX",
        max_fetch: int = 20,
    ) -> int:
        """Connect to an IMAP server, fetch UNSEEN messages, enqueue them.

        Reads credentials from env vars when not provided explicitly:
          IMAP_HOST, IMAP_PORT, IMAP_USER, IMAP_PASSWORD, IMAP_FOLDER

        Also reads IMAP_IGNORE_SENDERS (comma-separated list of substrings)
        to skip automated/notification emails, e.g.:
          IMAP_IGNORE_SENDERS=no-reply,noreply,mailer-daemon,accounts.google.com

        Returns the number of new messages enqueued.
        Raises ``RuntimeError`` if credentials are missing.
        """
        _host = host or os.environ.get("IMAP_HOST", "")
        _port = port or int(os.environ.get("IMAP_PORT", "993"))
        _user = user or os.environ.get("IMAP_USER", "")
        _password = password or os.environ.get("IMAP_PASSWORD", "")
        _folder = folder or os.environ.get("IMAP_FOLDER", "INBOX")

        # Senders to silently skip (automated notifications, noreply, etc.)
        _ignore_raw = os.environ.get(
            "IMAP_IGNORE_SENDERS",
            "no-reply,noreply,mailer-daemon,accounts.google.com,notifications@,notify@"
        )
        _ignore = [s.strip().lower() for s in _ignore_raw.split(",") if s.strip()]

        if not _host or not _user or not _password:
            raise RuntimeError(
                "IMAP credentials missing. Set IMAP_HOST, IMAP_USER and "
                "IMAP_PASSWORD in .env (or pass them as arguments)."
            )

        logger.info("[EmailInboxTool] Connecting to IMAP %s:%s as %s", _host, _port, _user)
        try:
            mail = imaplib.IMAP4_SSL(_host, _port)
            mail.login(_user, _password)
            mail.select(_folder)

            # Fetch only UNSEEN messages so we don't reprocess old ones
            status, data = mail.search(None, "UNSEEN")
            if status != "OK" or not data or not data[0]:
                mail.logout()
                logger.info("[EmailInboxTool] No unseen messages found.")
                return 0

            uids = data[0].split()
            uids = uids[:max_fetch]  # safety cap
            count = 0

            for uid in uids:
                try:
                    status, msg_data = mail.fetch(uid, "(RFC822)")
                    if status != "OK" or not msg_data:
                        continue
                    raw = msg_data[0][1]
                    msg = _emaillib.message_from_bytes(raw)

                    sender = _decode_mime_words(msg.get("From", "unknown"))
                    subject = _decode_mime_words(msg.get("Subject", "(sin asunto)"))
                    date_str = msg.get("Date", "")
                    body = _extract_body(msg)

                    # Skip automated/notification senders
                    sender_lower = sender.lower()
                    if any(pattern in sender_lower for pattern in _ignore):
                        logger.info(
                            "[EmailInboxTool] Skipping automated email from %s | Subject: %s",
                            sender, subject,
                        )
                        continue

                    cls.enqueue(
                        sender=sender,
                        subject=subject,
                        body=body,
                        received_at=date_str or datetime.now(timezone.utc).isoformat(),
                    )
                    count += 1
                except Exception as exc:  # pragma: no cover
                    logger.warning("[EmailInboxTool] Could not parse message uid=%s: %s", uid, exc)

            mail.logout()
            logger.info("[EmailInboxTool] Fetched %d new message(s) from IMAP.", count)
            return count

        except imaplib.IMAP4.error as exc:
            logger.error("[EmailInboxTool] IMAP error: %s", exc)
            raise RuntimeError(f"IMAP connection failed: {exc}") from exc

    def _fetch_from_server(self) -> List[Dict[str, Any]]:  # pragma: no cover
        """Legacy stub — kept for backward compatibility.
        Use ``EmailInboxTool.fetch_from_imap()`` directly instead.
        """
        return []


# ===========================================================================
# 2. ChatMessageInboxTool
# ===========================================================================

class ChatInboxInput(BaseModel):
    """Input schema for ChatMessageInboxTool."""
    max_messages: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of unread chat messages to retrieve (1–50).",
    )
    mark_as_read: bool = Field(
        default=True,
        description="If true, retrieved messages are marked as read.",
    )
    channel_filter: Optional[str] = Field(
        default=None,
        description="Filter by channel name, e.g. 'telegram' or 'slack'. None = all channels.",
    )


class ChatMessageInboxTool(_BASE):
    """Retrieve unread chat messages from Telegram / Slack / Teams.

    The agent calls this tool to fetch pending chat messages.
    In production, override ``_fetch_from_server`` with real bot API calls.

    Enqueue messages from outside (CLI, tests, webhooks):
        ChatMessageInboxTool.enqueue(sender="@jefe", subject="...", body="...")
    """
    name: str = "chat_inbox"
    description: str = (
        "Reads unread chat messages from Telegram, Slack or Teams. Returns a JSON "
        "list of messages with sender, subject/topic, body and metadata. Call this "
        "to fetch pending chat messages before executing any triage task."
    )
    args_schema: Type[BaseModel] = ChatInboxInput

    # Shared in-memory inbox
    _queue: ClassVar[List[_InboxMessage]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @classmethod
    def enqueue(
        cls,
        sender: str,
        body: str,
        subject: str = "(chat message)",
        channel: str = "telegram",
        received_at: Optional[str] = None,
    ) -> str:
        """Add a chat message to the inbox queue. Returns the new message_id."""
        msg = _InboxMessage(
            message_id=str(uuid.uuid4()),
            channel=channel,
            sender=sender,
            subject=subject,
            body=body,
            received_at=received_at or datetime.now(timezone.utc).isoformat(),
        )
        cls._queue.append(msg)
        logger.info(
            "[ChatMessageInboxTool] Enqueued %s message from %s", channel, sender
        )
        return msg.message_id

    @classmethod
    def pending_count(cls) -> int:
        return sum(1 for m in cls._queue if not m.read)

    @classmethod
    def clear(cls) -> None:
        cls._queue.clear()

    # ------------------------------------------------------------------
    # crewai _run
    # ------------------------------------------------------------------
    def _run(self, **kwargs: Any) -> str:
        try:
            inp = ChatInboxInput(**kwargs)
        except Exception as exc:
            return json.dumps({"status": "error", "message": f"Invalid input: {exc}"})

        try:
            unread = [m for m in self._queue if not m.read]
            if inp.channel_filter:
                unread = [m for m in unread if m.channel == inp.channel_filter]
            batch = unread[: inp.max_messages]

            if inp.mark_as_read:
                for m in batch:
                    m.read = True

            result = {
                "status": "ok",
                "channel": inp.channel_filter or "all",
                "count": len(batch),
                "messages": [m.to_dict() for m in batch],
            }
            logger.info("[ChatMessageInboxTool] Retrieved %d chat message(s)", len(batch))
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as exc:
            logger.exception("[ChatMessageInboxTool] Unexpected error")
            return json.dumps({"status": "error", "message": str(exc)})

    # ------------------------------------------------------------------
    # Production hook
    # ------------------------------------------------------------------
    def _fetch_from_server(self) -> List[Dict[str, Any]]:  # pragma: no cover
        """
        Override with real bot logic, e.g.:

            from telegram import Bot
            bot = Bot(token=TELEGRAM_TOKEN)
            updates = bot.get_updates(offset=self._last_update_id)
            ...
        """
        return []


# ===========================================================================
# Convenience helper — format a single inbox message as triage input text
# ===========================================================================

def message_to_triage_text(msg_dict: Dict[str, Any]) -> str:
    """Convert a message dict (from tool output) into the triage text format."""
    return (
        f"De: {msg_dict.get('sender', 'unknown')}\n"
        f"Asunto: {msg_dict.get('subject', '(sin asunto)')}\n"
        f"Canal: {msg_dict.get('channel', 'unknown')}\n"
        f"Recibido: {msg_dict.get('received_at', '')}\n\n"
        f"{msg_dict.get('body', '')}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
__all__ = [
    "EmailInboxTool",
    "EmailInboxInput",
    "ChatMessageInboxTool",
    "ChatInboxInput",
    "message_to_triage_text",
]
