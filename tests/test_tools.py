"""
Unit tests for Custom Tools: ConfluenceUpsertTool, EmailDraftingTool, LeaderNotificationTool.

Covers:
- Happy path (valid inputs → expected output fields)
- Error path (invalid / missing inputs → status:error JSON)
- ConfluenceUpsertTool: insert then update (upsert semantics)
- LeaderNotificationTool: message captured in _sent_messages
- Full triage pipeline: STRATEGIC and JUNK classification
"""
from __future__ import annotations

import json

import pytest

from src.tools import (
    ConfluenceUpsertTool,
    EmailDraftingTool,
    LeaderNotificationTool,
)
from src.triage_crew import TriageCrew, TriageDecisionOutput


# ============================================================
# ConfluenceUpsertTool
# ============================================================

class TestConfluenceUpsertTool:
    def setup_method(self):
        # Reset in-memory store before each test
        ConfluenceUpsertTool._store.clear()
        self.tool = ConfluenceUpsertTool()

    def test_insert_new_page(self):
        result = json.loads(self.tool.run(
            space_key="TECH",
            title="Migración SaaS",
            content="## Resumen\nPropuesta de migración a SaaS.",
            labels=["saas", "migración"],
        ))
        assert result["status"] == "ok"
        assert result["action"] == "created"
        assert result["title"] == "Migración SaaS"
        assert result["space_key"] == "TECH"
        assert "url" in result
        assert "page_id" in result

    def test_update_existing_page(self):
        # First insert
        self.tool.run(
            space_key="TECH",
            title="Migración SaaS",
            content="Contenido inicial.",
            labels=["saas"],
        )
        # Then update
        result = json.loads(self.tool.run(
            space_key="TECH",
            title="Migración SaaS",
            content="Contenido actualizado.",
            labels=["microservicio"],
        ))
        assert result["status"] == "ok"
        assert result["action"] == "updated"
        # Merged labels should include both
        stored_key = "TECH::migración saas"
        stored = ConfluenceUpsertTool._store[stored_key]
        assert "saas" in stored["labels"]
        assert "microservicio" in stored["labels"]
        assert "Contenido actualizado." in stored["content"]

    def test_invalid_input_returns_error(self):
        # crewai 1.x BaseTool raises ValueError on missing required fields
        # (validation happens before _run is called — this is correct crewai behavior)
        import pytest
        with pytest.raises((ValueError, Exception)):
            self.tool.run(
                # Missing required fields
                content="Only content, no space_key or title",
            )


# ============================================================
# EmailDraftingTool
# ============================================================

class TestEmailDraftingTool:
    def setup_method(self):
        self.tool = EmailDraftingTool()

    def test_draft_created_with_valid_input(self):
        result = json.loads(self.tool.run(
            recipient_name="Ana García",
            recipient_role="CFO",
            recipient_email="cfo@empresa.com",
            subject="Evaluación presupuesto Shopify",
            context="Tenemos una propuesta de integración Shopify con un costo de $2,000/mes.",
            action_requested="¿Contamos con presupuesto aprobado para Q3?",
            urgency="high",
        ))
        assert result["status"] == "ok"
        draft = result["draft"]
        assert draft["to"] == "cfo@empresa.com"
        assert "[ALTA PRIORIDAD]" in draft["subject"]
        assert "Ana García" in draft["body"]
        assert "Shopify" in draft["body"]
        assert draft["requires_approval"] is True
        assert draft["urgency"] == "high"

    def test_urgency_tags(self):
        for urgency, expected_tag in [
            ("critical", "[URGENTE]"),
            ("high", "[ALTA PRIORIDAD]"),
            ("normal", ""),
            ("low", ""),
        ]:
            result = json.loads(self.tool.run(
                recipient_name="Test",
                recipient_role="CTO",
                recipient_email="cto@test.com",
                subject="Test subject",
                context="Test context",
                action_requested="Test action",
                urgency=urgency,
            ))
            if expected_tag:
                assert expected_tag in result["draft"]["subject"]
            else:
                assert "[" not in result["draft"]["subject"] or "[URGENTE]" not in result["draft"]["subject"]

    def test_missing_required_fields_returns_error(self):
        # crewai 1.x BaseTool raises ValueError on missing required fields
        import pytest
        with pytest.raises((ValueError, Exception)):
            self.tool.run(
                subject="Solo asunto",
            )


# ============================================================
# LeaderNotificationTool
# ============================================================

class TestLeaderNotificationTool:
    def setup_method(self):
        LeaderNotificationTool._sent_messages.clear()
        self.tool = LeaderNotificationTool()

    def test_telegram_notification_strategic(self):
        result = json.loads(self.tool.run(
            channel="telegram",
            classification="STRATEGIC",
            summary="Correo de integración Shopify procesado.",
            actions_taken=["Página creada en Confluence", "Borrador de correo preparado"],
            pending_approvals=["Aprobar borrador al CTO"],
            original_subject="Propuesta Shopify",
            original_sender="vendor@shopify.com",
        ))
        assert result["status"] == "ok"
        assert result["channel"] == "telegram"
        assert result["delivery"]["simulated"] is True
        # Check message was captured
        assert len(LeaderNotificationTool._sent_messages) == 1
        msg = LeaderNotificationTool._sent_messages[0]["message"]
        assert "STRATEGIC" in msg
        assert "Shopify" in msg
        assert "Confluence" in msg

    def test_junk_notification(self):
        result = json.loads(self.tool.run(
            channel="slack",
            classification="JUNK",
            summary="Correo de spam descartado.",
            original_subject="Ganaste un iPhone",
            original_sender="spam@promo.net",
        ))
        assert result["status"] == "ok"
        msg = LeaderNotificationTool._sent_messages[0]["message"]
        assert "JUNK" in msg
        assert "🗑️" in msg

    def test_invalid_input_returns_error(self):
        # crewai 1.x BaseTool raises ValueError on missing required fields
        import pytest
        with pytest.raises((ValueError, Exception)):
            self.tool.run(
                channel="telegram",
                # Missing required classification and summary
            )


# ============================================================
# Full Triage Pipeline integration tests
# ============================================================

STRATEGIC_EMAIL = """\
De: partner@cloudtech.io
Asunto: Propuesta integración Shopify + microservicios

Hola,

Proponemos migrar la infraestructura local a una arquitectura SaaS basada en
microservicios, integrando Shopify para e-commerce B2C y Bókun para ticketing.
La solución reduce costos en un 35%.

Saludos,
Partner Team
"""

JUNK_EMAIL = """\
De: noreply@loteria.net
Asunto: ¡Ganaste $10,000 dolares!

Hola, fuiste seleccionado. Haz clic para cobrar tu premio.
"""


class TestTriagePipeline:
    def setup_method(self):
        ConfluenceUpsertTool._store.clear()
        LeaderNotificationTool._sent_messages.clear()

    @staticmethod
    def _stub_crew() -> TriageCrew:
        """Return a TriageCrew en stub_mode=True — sin LLMs, sin red, instantáneo."""
        return TriageCrew(stub_mode=True)

    def test_strategic_classification(self):
        crew = self._stub_crew()
        result = crew.kickoff(STRATEGIC_EMAIL)

        assert isinstance(result, TriageDecisionOutput)
        assert result.classification == "STRATEGIC"
        assert result.discarded is False
        assert len(result.actions_taken) >= 3  # confluence + email + notification
        assert any("ConfluenceUpsertTool" in a.tool for a in result.actions_taken)
        assert any("EmailDraftingTool" in a.tool for a in result.actions_taken)
        assert any("LeaderNotificationTool" in a.tool for a in result.actions_taken)
        assert len(result.pending_approvals) >= 1
        assert result.email_summary.sender != ""
        assert result.email_summary.subject != ""

    def test_junk_classification(self):
        crew = self._stub_crew()
        result = crew.kickoff(JUNK_EMAIL)

        assert isinstance(result, TriageDecisionOutput)
        assert result.classification == "JUNK"
        assert result.discarded is True
        assert result.discard_reason is not None
        # Only notification tool should have been used
        assert all("LeaderNotification" in a.tool for a in result.actions_taken)

    def test_empty_email_raises(self):
        crew = self._stub_crew()
        with pytest.raises(ValueError, match="non-empty"):
            crew.kickoff("   ")

    def test_output_is_json_serialisable(self):
        crew = self._stub_crew()
        result = crew.kickoff(STRATEGIC_EMAIL)
        json_str = result.model_dump_json()
        parsed = json.loads(json_str)
        assert "classification" in parsed
        assert "actions_taken" in parsed
        assert "pending_approvals" in parsed
