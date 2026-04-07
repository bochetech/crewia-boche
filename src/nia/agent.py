"""
Nia — Central Strategic Agent.

Nia is channel-agnostic: she receives text from any channel adapter and
decides what to do with it (conversational reply or dispatch to a crew flow).

Key responsibilities
--------------------
- dispatch()         → classify intent, return flow_id or direct reply
- classify_email()   → spam | notification | important | analyzable
- summarize()        → executive summary (for notifications)
- run_flow()         → execute a named crew flow, return raw result
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent.parent  # repo root


# ---------------------------------------------------------------------------
# Config dataclass (mirrors config/nia.yaml)
# ---------------------------------------------------------------------------

@dataclass
class NiaConfig:
    name: str = "Nia"
    role: str = "Analista Estratégica de Triaje"
    personality: str = "Profesional, directa y estratégica. Responde en español."
    default_flow: str = "strategy_crew"
    telegram_feedback_enabled: bool = True
    memory_max_topics: int = 10

    @classmethod
    def from_yaml(cls, path: Path | str | None = None) -> "NiaConfig":
        yaml_path = Path(path) if path else _ROOT / "config" / "nia.yaml"
        if not yaml_path.exists():
            logger.warning("[NiaConfig] %s not found — using defaults", yaml_path)
            return cls()
        with open(yaml_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        nia = data.get("nia", {})
        return cls(
            name=nia.get("name", "Nia"),
            role=nia.get("role", "Analista Estratégica de Triaje"),
            personality=nia.get("personality", ""),
            default_flow=nia.get("default_flow", "strategy_crew"),
            telegram_feedback_enabled=nia.get("telegram_feedback_enabled", True),
            memory_max_topics=int(nia.get("memory_max_topics", 10)),
        )


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class DispatchResult:
    """What Nia decided to do with an incoming message."""
    # If flow_id is set → run that crew flow with input_text
    flow_id: Optional[str] = None
    input_text: Optional[str] = None
    # If response is set → conversational reply (no flow dispatched)
    response: Optional[str] = None
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_conversational(self) -> bool:
        return self.flow_id is None


class EmailClassification(str, Enum):
    SPAM = "spam"
    NOTIFICATION = "notification"
    IMPORTANT = "important"
    ANALYZABLE = "analyzable"


# ---------------------------------------------------------------------------
# Flow loader helper
# ---------------------------------------------------------------------------

def _load_flows() -> List[Dict[str, Any]]:
    """Read config/flows.yaml and return list of flow dicts."""
    flows_path = _ROOT / "config" / "flows.yaml"
    if not flows_path.exists():
        return []
    with open(flows_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    raw = data.get("flows", [])
    return raw if isinstance(raw, list) else []


# ---------------------------------------------------------------------------
# NiaAgent
# ---------------------------------------------------------------------------

class NiaAgent:
    """
    Channel-agnostic brain.  Receives input text, decides what to do.

    Parameters
    ----------
    config:
        NiaConfig instance.  If None, loaded from config/nia.yaml.
    crew:
        TriageCrew instance used to run flows.  If None, flows cannot
        be executed (useful for testing intent classification only).
    """

    def __init__(
        self,
        config: Optional[NiaConfig] = None,
        crew=None,
    ) -> None:
        self.config = config or NiaConfig.from_yaml()
        self.crew = crew
        self.flows: List[Dict[str, Any]] = _load_flows()
        logger.info(
            "[NiaAgent] Initialised as '%s' | default_flow=%s | %d flow(s) loaded",
            self.config.name,
            self.config.default_flow,
            len(self.flows),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def dispatch(
        self,
        text: str,
        user_id: str,
        memory=None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> DispatchResult:
        """
        Decide what to do with an incoming message.

        Returns a DispatchResult with either:
          - flow_id + input_text  → the caller should run that crew flow
          - response              → conversational reply, no flow needed
        """
        # Detect mode: email-like format or explicit triage keywords → run flow
        if self._should_run_flow(text):
            flow_id = self._choose_flow(text)
            assembled = self._assemble_triage_input(text, user_id, memory, history)
            return DispatchResult(
                flow_id=flow_id,
                input_text=assembled,
                confidence=0.9,
            )

        # Conversational — caller handles LLM reply via crew.kickoff_conversation
        return DispatchResult(
            response=None,  # None means caller should use kickoff_conversation
            confidence=0.8,
        )

    def classify_email(
        self,
        sender: str,
        subject: str,
        body: str,
    ) -> EmailClassification:
        """
        Classify an email as spam, notification, important, or analyzable.

        Uses keyword heuristics first; falls back to LLM if crew is available.
        """
        combined = f"{sender} {subject} {body}".lower()

        # ── Spam heuristics ──────────────────────────────────────────────────
        spam_signals = [
            "unsubscribe", "darse de baja", "click here", "free offer",
            "congratulations", "felicitaciones", "prize", "won ", "winner",
            "no-reply@", "noreply@", "newsletter", "promotion", "oferta especial",
        ]
        if any(sig in combined for sig in spam_signals):
            logger.info("[NiaAgent] Email classified as SPAM: %s", subject)
            return EmailClassification.SPAM

        # ── Notification heuristics ──────────────────────────────────────────
        notification_signals = [
            "notification", "notificación", "alert", "alerta",
            "automated", "automático", "do not reply", "no responder",
            "your order", "tu orden", "invoice #", "factura #",
            "confirmación de", "confirmation of", "receipt",
        ]
        if any(sig in combined for sig in notification_signals):
            logger.info("[NiaAgent] Email classified as NOTIFICATION: %s", subject)
            return EmailClassification.NOTIFICATION

        # ── Analyzable heuristics ────────────────────────────────────────────
        analyzable_signals = [
            "propuesta", "proposal", "proyecto", "project",
            "iniciativa", "initiative", "integración", "integration",
            "estrategia", "strategy", "reunión", "meeting", "agenda",
            "presupuesto", "budget", "cotización", "quote",
            "solicitud de", "request for", "oportunidad", "opportunity",
        ]
        if any(sig in combined for sig in analyzable_signals):
            logger.info("[NiaAgent] Email classified as ANALYZABLE: %s", subject)
            return EmailClassification.ANALYZABLE

        # Default: important (needs human review)
        logger.info("[NiaAgent] Email classified as IMPORTANT: %s", subject)
        return EmailClassification.IMPORTANT

    def summarize(self, text: str, max_chars: int = 300) -> str:
        """
        Return a short executive summary of the given text.

        Uses LLM if crew is available; otherwise returns a truncated excerpt.
        """
        if self.crew is not None:
            try:
                prompt = (
                    f"Resume el siguiente texto en máximo {max_chars} caracteres, "
                    f"en español, de forma ejecutiva y sin perder puntos clave:\n\n"
                    f"{text[:3000]}"
                )
                # Use crew's conversation mode for a quick summary
                result = self.crew.kickoff_conversation(
                    user_text=prompt,
                    history=[],
                    user_id="__system__",
                )
                return str(result)[:max_chars]
            except Exception as exc:
                logger.warning("[NiaAgent] summarize() LLM call failed: %s", exc)

        # Fallback: truncate
        clean = " ".join(text.split())
        return clean[:max_chars] + ("…" if len(clean) > max_chars else "")

    def run_flow(self, flow_id: str, input_text: str) -> Any:
        """
        Execute a named crew flow.  Blocks until complete.

        Returns the crew result object.
        Raises ValueError if crew is not set or flow_id is unknown.
        """
        if self.crew is None:
            raise ValueError("[NiaAgent] No crew attached — cannot run flows")

        known_ids = [f.get("id") for f in self.flows]
        if flow_id not in known_ids:
            logger.warning(
                "[NiaAgent] Unknown flow_id '%s'. Known: %s. Running anyway via crew.",
                flow_id, known_ids,
            )

        logger.info("[NiaAgent] Running flow '%s' (%d chars input)", flow_id, len(input_text))
        return self.crew.kickoff(input_text)

    def get_flows(self) -> List[Dict[str, Any]]:
        """Return the list of available flows (reload from disk each time)."""
        self.flows = _load_flows()
        return self.flows

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _should_run_flow(self, text: str) -> bool:
        """Return True if the message should be dispatched to a crew flow."""
        text_lower = text.lower()

        # Email-like format detection (first 5 lines have email headers)
        for line in text.split("\n")[:5]:
            stripped = line.strip().lower()
            if any(stripped.startswith(p) for p in ("de:", "from:", "asunto:", "subject:", "fecha:", "date:")):
                return True

        # Explicit triage keywords
        triage_keywords = [
            "clasifica esto", "clasifica el siguiente", "analiza este email",
            "triaje", "triage", "documenta esto", "es strategic", "es junk",
            "/iniciar",
        ]
        if any(kw in text_lower for kw in triage_keywords):
            return True

        # Very long messages (>100 words) are probably documents/emails
        if len(text.split()) > 100:
            return True

        return False

    def _choose_flow(self, text: str) -> str:
        """Choose the best flow for a given message.  Returns flow id."""
        # For now: always use the default flow.
        # Future: use LLM intent classifier over self.flows descriptions.
        return self.config.default_flow

    def _assemble_triage_input(
        self,
        text: str,
        user_id: str,
        memory,
        history: Optional[List[Dict[str, Any]]],
    ) -> str:
        """Build the full triage input text including context blocks."""
        parts: List[str] = []

        # Semantic memory context
        if memory is not None:
            try:
                semantic_ctx = memory.get_context_for_triage(query=None, max_messages=10)
                if semantic_ctx:
                    parts.append(
                        "MEMORIA SEMÁNTICA:\n"
                        "═══════════════════════════════════════\n"
                        + semantic_ctx +
                        "\n═══════════════════════════════════════\n"
                    )
            except Exception as exc:
                logger.warning("[NiaAgent] Memory retrieval failed: %s", exc)

        # Short-term conversation history
        if history:
            recent = history[-10:]
            lines = []
            for msg in recent:
                role = "Usuario" if msg.get("role") == "user" else "Nia"
                lines.append(f"{role}: {msg.get('content', '')[:300]}")
            parts.append(
                "CONTEXTO CONVERSACIONAL RECIENTE:\n"
                "───────────────────────────────────────\n"
                + "\n\n".join(lines) +
                "\n───────────────────────────────────────\n"
            )

        parts.append(f"MENSAJE ACTUAL:\n{text}")
        return "\n\n".join(parts)
