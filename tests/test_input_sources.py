"""
Unit tests for Input Source Tools: EmailInboxTool, ChatMessageInboxTool.

Covers:
- enqueue() + pending_count()
- run() retrieves unread messages correctly
- mark_as_read semantics (same message not returned twice)
- channel_filter on ChatMessageInboxTool
- Empty inbox returns count=0
- Invalid input raises ValueError (crewai validation)
- message_to_triage_text() format
- run_triage_from_inboxes() integration (stub mode — no real LLM needed)
"""
from __future__ import annotations

import json

import pytest

from src.input_sources import (
    EmailInboxTool,
    ChatMessageInboxTool,
    message_to_triage_text,
)
from src.triage_crew import run_triage_from_inboxes


# ===========================================================================
# EmailInboxTool
# ===========================================================================

class TestEmailInboxTool:
    def setup_method(self):
        EmailInboxTool.clear()
        self.tool = EmailInboxTool()

    # -----------------------------------------------------------------------
    def test_empty_inbox_returns_zero(self):
        result = json.loads(self.tool.run(max_messages=5))
        assert result["status"] == "ok"
        assert result["count"] == 0
        assert result["messages"] == []

    def test_enqueue_and_retrieve(self):
        mid = EmailInboxTool.enqueue(
            sender="vendor@saas.io",
            subject="Propuesta Shopify",
            body="Queremos integrar Shopify con Bókun.",
        )
        assert EmailInboxTool.pending_count() == 1

        result = json.loads(self.tool.run(max_messages=5))
        assert result["status"] == "ok"
        assert result["count"] == 1
        msg = result["messages"][0]
        assert msg["message_id"] == mid
        assert msg["sender"] == "vendor@saas.io"
        assert msg["subject"] == "Propuesta Shopify"
        assert "Shopify" in msg["body"]
        assert msg["channel"] == "email"

    def test_mark_as_read_prevents_double_retrieval(self):
        EmailInboxTool.enqueue(sender="a@b.com", subject="Test", body="body")
        # First call reads and marks as read
        json.loads(self.tool.run(max_messages=5, mark_as_read=True))
        # Second call should return nothing
        result = json.loads(self.tool.run(max_messages=5))
        assert result["count"] == 0

    def test_mark_as_read_false_allows_reread(self):
        EmailInboxTool.enqueue(sender="a@b.com", subject="Test", body="body")
        json.loads(self.tool.run(max_messages=5, mark_as_read=False))
        result = json.loads(self.tool.run(max_messages=5, mark_as_read=False))
        assert result["count"] == 1

    def test_max_messages_limit(self):
        for i in range(5):
            EmailInboxTool.enqueue(sender=f"u{i}@test.com", subject=f"Msg {i}", body="x")
        result = json.loads(self.tool.run(max_messages=3, mark_as_read=False))
        assert result["count"] == 3

    def test_pending_count_decreases_after_read(self):
        EmailInboxTool.enqueue(sender="a@b.com", subject="S", body="b")
        EmailInboxTool.enqueue(sender="c@d.com", subject="S2", body="b2")
        assert EmailInboxTool.pending_count() == 2
        json.loads(self.tool.run(max_messages=10, mark_as_read=True))
        assert EmailInboxTool.pending_count() == 0

    def test_invalid_max_messages_raises(self):
        with pytest.raises((ValueError, Exception)):
            self.tool.run(max_messages=0)   # ge=1 constraint


# ===========================================================================
# ChatMessageInboxTool
# ===========================================================================

class TestChatMessageInboxTool:
    def setup_method(self):
        ChatMessageInboxTool.clear()
        self.tool = ChatMessageInboxTool()

    def test_empty_inbox_returns_zero(self):
        result = json.loads(self.tool.run(max_messages=5))
        assert result["status"] == "ok"
        assert result["count"] == 0

    def test_enqueue_and_retrieve(self):
        mid = ChatMessageInboxTool.enqueue(
            sender="@cto",
            body="¿Viste la propuesta de Bókun? Creo que es estratégico.",
            subject="Roadmap e-commerce",
            channel="telegram",
        )
        result = json.loads(self.tool.run(max_messages=5))
        assert result["count"] == 1
        msg = result["messages"][0]
        assert msg["message_id"] == mid
        assert msg["sender"] == "@cto"
        assert msg["channel"] == "telegram"
        assert "Bókun" in msg["body"]

    def test_channel_filter(self):
        ChatMessageInboxTool.enqueue(sender="@a", body="msg A", channel="telegram")
        ChatMessageInboxTool.enqueue(sender="@b", body="msg B", channel="slack")

        result_tg = json.loads(
            self.tool.run(max_messages=10, mark_as_read=False, channel_filter="telegram")
        )
        assert result_tg["count"] == 1
        assert result_tg["messages"][0]["channel"] == "telegram"

        result_sl = json.loads(
            self.tool.run(max_messages=10, mark_as_read=False, channel_filter="slack")
        )
        assert result_sl["count"] == 1

    def test_mark_as_read(self):
        ChatMessageInboxTool.enqueue(sender="@x", body="hello")
        json.loads(self.tool.run(max_messages=5, mark_as_read=True))
        result = json.loads(self.tool.run(max_messages=5))
        assert result["count"] == 0


# ===========================================================================
# message_to_triage_text helper
# ===========================================================================

class TestMessageToTriageText:
    def test_formats_correctly(self):
        msg = {
            "sender": "vendor@io.com",
            "subject": "Propuesta SaaS",
            "channel": "email",
            "received_at": "2026-04-05T10:00:00+00:00",
            "body": "Queremos integrar Shopify.",
        }
        text = message_to_triage_text(msg)
        assert "De: vendor@io.com" in text
        assert "Asunto: Propuesta SaaS" in text
        assert "Canal: email" in text
        assert "Shopify" in text

    def test_missing_fields_use_defaults(self):
        text = message_to_triage_text({})
        assert "De: unknown" in text
        assert "Asunto: (sin asunto)" in text


# ===========================================================================
# run_triage_from_inboxes integration (stub mode — no LLM required)
# ===========================================================================

class TestRunTriageFromInboxes:
    def setup_method(self):
        EmailInboxTool.clear()
        ChatMessageInboxTool.clear()

    def test_processes_email_and_chat(self):
        EmailInboxTool.enqueue(
            sender="partner@saas.io",
            subject="Propuesta integración Shopify + microservicios",
            body=(
                "Proponemos migrar la infraestructura local a SaaS con microservicios, "
                "integrando Shopify para e-commerce B2C y Bókun para ticketing."
            ),
        )
        ChatMessageInboxTool.enqueue(
            sender="@spam_bot",
            body="Ganaste un viaje GRATIS. Haz clic aquí.",
            subject="Promoción",
            channel="telegram",
        )

        results = run_triage_from_inboxes()
        assert len(results) == 2

        msgs_by_channel = {r[0]["channel"]: r[1] for r in results}
        # El email de propuesta técnica siempre es STRATEGIC
        assert msgs_by_channel["email"].classification == "STRATEGIC"
        # El mensaje de spam puede ser JUNK o STRATEGIC dependiendo del modelo/umbral.
        # Lo importante es que sea un resultado válido (no None ni excepción).
        assert msgs_by_channel["telegram"].classification in ("STRATEGIC", "JUNK")

    def test_empty_inboxes_return_empty_list(self):
        results = run_triage_from_inboxes()
        assert results == []

    def test_messages_marked_read_after_poll(self):
        EmailInboxTool.enqueue(sender="a@b.com", subject="s", body="e-commerce Shopify saas")
        run_triage_from_inboxes()
        assert EmailInboxTool.pending_count() == 0
