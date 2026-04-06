"""
Custom Tools for the Triage Analytical Pipeline.

Each tool follows the BaseTool pattern from crewai (with a Pydantic v2 input
schema).  When crewai is not installed the module provides a lightweight
stand-alone fallback so the tools remain independently usable and testable.

Tools:
- ConfluenceUpsertTool   : Upsert knowledge into Confluence (search → update or create).
- EmailDraftingTool      : Draft a collaboration e-mail to an organogram member.
- LeaderNotificationTool : Send a structured chat summary to the tech lead (Telegram/Slack sim).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, List, Optional, Type

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thin BaseTool shim — replaced by the real crewai.tools.BaseTool when present
# ---------------------------------------------------------------------------
try:
    from crewai.tools import BaseTool as _CrewBaseTool  # type: ignore

    _BASE = _CrewBaseTool
    _CREWAI_AVAILABLE = True
except Exception:
    _CREWAI_AVAILABLE = False

    class _BASE:  # type: ignore
        """Fallback base so tools work without crewai installed."""
        name: str = ""
        description: str = ""
        args_schema: Optional[Any] = None

        def _run(self, **kwargs: Any) -> Any:  # noqa: D401
            raise NotImplementedError

        def run(self, **kwargs: Any) -> Any:
            if self.args_schema is not None:
                validated = self.args_schema(**kwargs)
                kwargs = validated.model_dump()
            return self._run(**kwargs)


# ===========================================================================
# 1. ConfluenceUpsertTool
# ===========================================================================

class ConfluenceUpsertInput(BaseModel):
    """Input schema for ConfluenceUpsertTool."""
    space_key: str = Field(..., description="Confluence space key, e.g. 'TECH'")
    title: str = Field(..., description="Page title / topic to search for or create")
    content: str = Field(..., description="Structured Markdown/HTML content to upsert")
    labels: Optional[List[str]] = Field(default_factory=list, description="Labels to tag the page")
    parent_page_id: Optional[str] = Field(None, description="Parent page ID (optional)")


class ConfluenceUpsertTool(_BASE):
    """Search Confluence for a topic; update if found, create if not.

    In production, replace the ``_simulate_*`` methods with real Confluence
    REST API calls using the ``atlassian-python-api`` library or ``requests``.
    """
    # crewai 1.x: BaseTool is a Pydantic model — name/description must be
    # instance fields, NOT ClassVar. args_schema wires input validation.
    name: str = "confluence_upsert"
    description: str = (
        "Upserts a Confluence page: searches for an existing page by title in the "
        "given space; if found merges the new content into it (Update); if not found "
        "creates a new structured page (Insert).  Returns a JSON with the action taken "
        "and the (simulated) page URL."
    )
    args_schema: Type[BaseModel] = ConfluenceUpsertInput

    # Simulated in-memory store so the tool is self-contained in tests
    _store: ClassVar[Dict[str, Dict[str, Any]]] = {}

    def _run(self, **kwargs: Any) -> str:  # noqa: D401
        try:
            inp = ConfluenceUpsertInput(**kwargs)
        except Exception as exc:
            return json.dumps({"status": "error", "message": f"Invalid input: {exc}"})

        try:
            key = f"{inp.space_key}::{inp.title.lower()}"
            now = datetime.now(timezone.utc).isoformat()

            if key in self._store:
                # UPDATE: merge content
                existing = self._store[key]
                existing["content"] = self._merge_content(existing["content"], inp.content)
                existing["updated_at"] = now
                existing["labels"] = list(set(existing.get("labels", []) + (inp.labels or [])))
                action = "updated"
                page_id = existing["page_id"]
            else:
                # INSERT: create new page
                page_id = f"page_{abs(hash(key)) % 100_000:05d}"
                self._store[key] = {
                    "page_id": page_id,
                    "space_key": inp.space_key,
                    "title": inp.title,
                    "content": inp.content,
                    "labels": inp.labels or [],
                    "parent_page_id": inp.parent_page_id,
                    "created_at": now,
                    "updated_at": now,
                }
                action = "created"

            result = {
                "status": "ok",
                "action": action,
                "page_id": page_id,
                "title": inp.title,
                "space_key": inp.space_key,
                "url": f"https://confluence.example.com/display/{inp.space_key}/{page_id}",
                "timestamp": now,
            }
            logger.info("[ConfluenceUpsertTool] %s page '%s' (%s)", action, inp.title, page_id)
            return json.dumps(result, ensure_ascii=False)

        except Exception as exc:
            logger.exception("[ConfluenceUpsertTool] Unexpected error")
            return json.dumps({"status": "error", "message": str(exc)})

    @staticmethod
    def _merge_content(existing: str, new: str) -> str:
        """Append new content under a timestamped section header."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return f"{existing}\n\n---\n### Update — {ts}\n{new}"


# ===========================================================================
# 2. EmailDraftingTool
# ===========================================================================

class EmailDraftingInput(BaseModel):
    """Input schema for EmailDraftingTool."""
    recipient_name: str = Field(..., description="Full name of the recipient")
    recipient_role: str = Field(..., description="Role/title in the organogram")
    recipient_email: str = Field(..., description="Recipient e-mail address")
    subject: str = Field(..., description="E-mail subject line")
    context: str = Field(..., description="Key context / information to include in the draft")
    action_requested: str = Field(..., description="Specific action or answer being requested")
    urgency: str = Field(default="normal", description="Urgency level: low | normal | high | critical")
    sender_name: str = Field(
        default="Nia — Analista Estratégica de Triaje",
        description="Sender display name",
    )


class EmailDraftingTool(_BASE):
    """Compose a structured collaboration e-mail draft to an organogram member.

    Returns the draft as a JSON object with subject, body, and metadata.
    The draft is NOT sent — it should be reviewed and approved by the tech lead
    before dispatch.
    """
    name: str = "email_drafting"
    description: str = (
        "Composes a professional collaboration e-mail draft addressed to a specific "
        "organogram member.  The draft includes subject, body, urgency tag and metadata. "
        "Returns JSON.  The e-mail is NOT sent automatically — it requires leader approval."
    )
    args_schema: Type[BaseModel] = EmailDraftingInput

    def _run(self, **kwargs: Any) -> str:  # noqa: D401
        try:
            inp = EmailDraftingInput(**kwargs)
        except Exception as exc:
            return json.dumps({"status": "error", "message": f"Invalid input: {exc}"})

        try:
            urgency_tag = {
                "low": "",
                "normal": "",
                "high": "[ALTA PRIORIDAD] ",
                "critical": "[URGENTE] ",
            }.get(inp.urgency.lower(), "")

            subject_full = f"{urgency_tag}{inp.subject}"

            body = (
                f"Hola {inp.recipient_name},\n\n"
                f"Me pongo en contacto contigo en mi rol de Analista Estratégica de Triaje "
                f"para solicitarte tu colaboración en el siguiente asunto:\n\n"
                f"**Contexto:**\n{inp.context}\n\n"
                f"**Acción requerida:**\n{inp.action_requested}\n\n"
                f"Quedo a tu disposición para cualquier aclaración. "
                f"Agradezco tu respuesta a la brevedad posible.\n\n"
                f"Saludos,\n{inp.sender_name}"
            )

            draft = {
                "status": "ok",
                "draft": {
                    "to": inp.recipient_email,
                    "recipient_name": inp.recipient_name,
                    "recipient_role": inp.recipient_role,
                    "subject": subject_full,
                    "body": body,
                    "urgency": inp.urgency,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "requires_approval": True,
                },
            }
            logger.info(
                "[EmailDraftingTool] Draft created for %s <%s> | Subject: %s",
                inp.recipient_name, inp.recipient_email, subject_full,
            )
            return json.dumps(draft, ensure_ascii=False, indent=2)

        except Exception as exc:
            logger.exception("[EmailDraftingTool] Unexpected error")
            return json.dumps({"status": "error", "message": str(exc)})


# ===========================================================================
# 3. LeaderNotificationTool
# ===========================================================================

class LeaderNotificationInput(BaseModel):
    """Input schema for LeaderNotificationTool."""
    channel: str = Field(default="telegram", description="Channel to use: telegram | slack | teams")
    classification: str = Field(..., description="Email classification: STRATEGIC | JUNK")
    summary: str = Field(..., description="Short human-readable summary of the decision")
    actions_taken: List[str] = Field(default_factory=list, description="List of actions executed")
    pending_approvals: List[str] = Field(default_factory=list, description="Items requiring leader approval")
    original_subject: str = Field(default="", description="Original e-mail subject for reference")
    original_sender: str = Field(default="", description="Original e-mail sender for reference")


class LeaderNotificationTool(_BASE):
    """Send a structured decision-summary notification to the tech lead.

    Simulates dispatch to Telegram/Slack.  In production, replace
    ``_dispatch_telegram`` / ``_dispatch_slack`` with real API calls using
    ``python-telegram-bot`` or the Slack SDK.
    """
    name: str = "leader_notification"
    description: str = (
        "Sends a structured summary of the triage decision to the tech lead via "
        "Telegram or Slack (simulated).  Includes classification, actions taken, "
        "and items pending approval.  Returns JSON with delivery status."
    )
    args_schema: Type[BaseModel] = LeaderNotificationInput

    # Captured messages for testing
    _sent_messages: ClassVar[List[Dict[str, Any]]] = []

    def _run(self, **kwargs: Any) -> str:  # noqa: D401
        try:
            inp = LeaderNotificationInput(**kwargs)
        except Exception as exc:
            return json.dumps({"status": "error", "message": f"Invalid input: {exc}"})

        try:
            emoji = "🚨" if inp.classification == "STRATEGIC" else "🗑️"
            actions_block = "\n".join(f"  ✅ {a}" for a in inp.actions_taken) or "  (ninguna)"
            approvals_block = (
                "\n".join(f"  ⏳ {p}" for p in inp.pending_approvals)
                or "  (ninguna pendiente)"
            )

            message = (
                f"{emoji} *Triage Analítico — Resultado*\n"
                f"────────────────────────────\n"
                f"📧 *De:* {inp.original_sender}\n"
                f"📌 *Asunto:* {inp.original_subject}\n"
                f"🏷️ *Clasificación:* `{inp.classification}`\n\n"
                f"📝 *Resumen:*\n{inp.summary}\n\n"
                f"⚙️ *Acciones ejecutadas:*\n{actions_block}\n\n"
                f"🔐 *Pendiente de aprobación:*\n{approvals_block}\n"
                f"────────────────────────────\n"
                f"_Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_"
            )

            record: Dict[str, Any] = {
                "channel": inp.channel,
                "message": message,
                "classification": inp.classification,
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }
            self._sent_messages.append(record)

            # Dispatch simulation
            if inp.channel == "telegram":
                delivery = self._dispatch_telegram(message)
            elif inp.channel == "slack":
                delivery = self._dispatch_slack(message)
            else:
                delivery = self._dispatch_generic(inp.channel, message)

            result = {
                "status": "ok",
                "channel": inp.channel,
                "delivery": delivery,
                "message_preview": message[:200] + "..." if len(message) > 200 else message,
                "sent_at": record["sent_at"],
            }
            logger.info("[LeaderNotificationTool] Notification sent via %s", inp.channel)
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as exc:
            logger.exception("[LeaderNotificationTool] Unexpected error")
            return json.dumps({"status": "error", "message": str(exc)})

    @staticmethod
    def _dispatch_telegram(message: str) -> Dict[str, Any]:
        # TODO: Replace with python-telegram-bot call
        # bot.send_message(chat_id=LEADER_CHAT_ID, text=message, parse_mode="Markdown")
        return {"method": "telegram", "simulated": True, "message_length": len(message)}

    @staticmethod
    def _dispatch_slack(message: str) -> Dict[str, Any]:
        # TODO: Replace with slack_sdk WebClient call
        # client.chat_postMessage(channel=SLACK_CHANNEL, text=message, mrkdwn=True)
        return {"method": "slack", "simulated": True, "message_length": len(message)}

    @staticmethod
    def _dispatch_generic(channel: str, message: str) -> Dict[str, Any]:
        return {"method": channel, "simulated": True, "message_length": len(message)}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
__all__ = [
    "ConfluenceUpsertTool",
    "ConfluenceUpsertInput",
    "EmailDraftingTool",
    "EmailDraftingInput",
    "LeaderNotificationTool",
    "LeaderNotificationInput",
]
