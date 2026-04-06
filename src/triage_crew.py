"""
Triage Analytical Pipeline — core Crew orchestration.

This module contains:
- TriageDecisionOutput    : Pydantic model for the structured agent output
- TriageCrew              : Orchestrates the triage_analyst agent + triage_email task
                            wired with the three custom output tools and two input
                            source tools (EmailInboxTool, ChatMessageInboxTool).
                            
                            LLM cascade (in order):
                              1. Local LM Studio (primary)
                              2. Gemini (fallback si local falla)
                              3. Stub determinístico (fallback final)
                            
- run_triage(email)       : Convenience function for a single email text.
- run_triage_from_inboxes(): Poll both inboxes and triage every pending message.

When crewai is not installed the module runs in STUB mode: the agent logic is
replaced by a deterministic rule-based classifier that exercises all tools,
so the pipeline is fully testable without external dependencies.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Generator, List, Optional, Tuple

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.tools import (
    ConfluenceUpsertTool,
    EmailDraftingTool,
    LeaderNotificationTool,
)
from src.input_sources import (
    EmailInboxTool,
    ChatMessageInboxTool,
    message_to_triage_text,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment loading (same pattern as original crew.py)
# ---------------------------------------------------------------------------

def load_env(dotenv_path: Optional[str] = None) -> None:
    """Load API keys from .env first, then Colab userdata as fallback."""
    load_dotenv(dotenv_path or os.path.join(os.getcwd(), ".env"))
    if not os.getenv("GEMINI_API_KEY"):
        try:
            import google.colab as colab  # type: ignore
            userdata = getattr(colab, "userdata", None)
            if isinstance(userdata, dict):
                key = userdata.get("GEMINI_API_KEY")
                if key:
                    os.environ["GEMINI_API_KEY"] = key
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Model tiers
# ---------------------------------------------------------------------------

MODEL_TIERS: Dict[str, str] = {
    "standard": "gemini-2.5-flash",
    "premium": "gemini-2.5-pro",
}

# Local LM Studio fallback — loaded from .env
# LMSTUDIO_BASE_URL=http://localhost:1234/v1
# LMSTUDIO_MODEL=<nombre_modelo>  (opcional — si no se define, usa el activo)
_LMSTUDIO_DEFAULT_URL = "http://localhost:1234/v1"


def _build_llm(tier: str = "premium", api_key: Optional[str] = None) -> Any:
    """Build a Gemini LLM client. Falls back to stub if SDKs are absent.

    crewai 1.x routes LLM calls through LiteLLM, which requires the
    ``"gemini/<model>"`` prefix for Google AI Studio models.
    """
    model_name = MODEL_TIERS.get(tier, MODEL_TIERS["premium"])
    litellm_name = f"gemini/{model_name}"   # required by crewai/LiteLLM
    if api_key is None:
        api_key = os.getenv("GEMINI_API_KEY")

    try:
        from crewai import LLM  # type: ignore
        return LLM(model=litellm_name, api_key=api_key)
    except Exception:
        pass

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore
        return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key)
    except Exception:
        pass

    # Stub LLM — used in tests and when no provider is installed
    class _StubLLM:
        def __init__(self, model: str, api_key: Optional[str] = None):
            self.model = model
            self.api_key = api_key

        def invoke(self, prompt: str) -> str:
            return f"[stub:{self.model}] {prompt[:80]}..."

        def __call__(self, prompt: str) -> str:
            return self.invoke(prompt)

    return _StubLLM(model_name, api_key)


def _build_local_llm(enable_reasoning: bool = True) -> Any:
    """Build an LLM pointing to the local LM Studio server.

    Uses LiteLLM's OpenAI-compatible provider via crewai LLM:
      model   = "openai/auto" (LM Studio usará el modelo activo)
      api_base = http://localhost:1234/v1
      api_key  = "lm-studio"  (any non-empty string works)

    Args:
        enable_reasoning: Si True, permite reasoning (<think>) para análisis profundo.
                         Si False, suprime reasoning para respuestas rápidas (conversación).

    Reads from .env:
      LMSTUDIO_BASE_URL  (default: http://localhost:1234/v1)
      LMSTUDIO_MODEL     (opcional: nombre específico del modelo. 
                          Si no se define, usa el modelo activo en LM Studio)
    """
    base_url = os.getenv("LMSTUDIO_BASE_URL", _LMSTUDIO_DEFAULT_URL).rstrip("/")
    model = os.getenv("LMSTUDIO_MODEL", "")
    # Si no hay modelo explícito, LM Studio usa el que esté cargado.
    # Usamos "auto" como placeholder que LM Studio ignora.
    litellm_name = f"openai/{model}" if model else "openai/auto"

    try:
        from crewai import LLM  # type: ignore
        
        llm_config = {
            "model": litellm_name,
            "base_url": base_url,
            "api_key": "lm-studio",
            "temperature": 0.7,
            "max_tokens": 2000,
        }
        
        # Configurar reasoning según el contexto de uso
        if not enable_reasoning:
            # CONVERSACIÓN: Deshabilitar reasoning para respuestas rápidas
            try:
                llm_config["extra_body"] = {
                    "reasoning_content": False,  # No incluir <think>
                    "stop": ["<think>", "</think>"],  # Detener si empieza
                }
                logger.debug("LLM config: reasoning DISABLED (conversation mode)")
            except Exception:
                pass
        else:
            # TRIAGE: Permitir reasoning pero extraer solo respuesta final
            # El parser en _parse_crewai_output extraerá el JSON después de <think>
            logger.debug("LLM config: reasoning ENABLED (triage mode)")
        
        return LLM(**llm_config)
    except Exception as exc:
        logger.debug("Could not build local LLM: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Structured output model
# ---------------------------------------------------------------------------

class ActionRecord(BaseModel):
    """Log of a single tool invocation."""
    tool: str
    status: str  # "ok" | "error" | "skipped"
    details: str


class EmailSummary(BaseModel):
    sender: str = ""
    subject: str = ""
    key_topics: List[str] = Field(default_factory=list)


class TriageDecisionOutput(BaseModel):
    """Validated structured output of the triage pipeline.

    This model is JSON-serialisable and ready to be forwarded to any
    downstream microservice or stored in an audit log.
    """
    classification: str                          # "STRATEGIC" | "JUNK"
    reasoning: str                               # agent's rationale
    email_summary: EmailSummary = Field(default_factory=EmailSummary)
    actions_taken: List[ActionRecord] = Field(default_factory=list)
    pending_approvals: List[str] = Field(default_factory=list)
    discarded: bool = False
    discard_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Stub-mode triage logic (used when crewai is not installed)
# ---------------------------------------------------------------------------

# Keywords derivadas directamente del PDF de estrategia Descorcha (Confluence).
# Se agrupan por pilar estratégico para facilitar el mantenimiento.
_STRATEGY_KEYWORDS = {
    # Aspiración / canal digital
    "ecommerce", "e-commerce", "canal digital", "dtc", "direct-to-consumer",
    # Dónde jugar
    "fidelización", "fidelizacion", "recompra", "ticket promedio",
    "logística", "logistica", "catálogo", "catalogo", "pagos",
    # Cómo ganar / roadmap
    "roadmap", "hipótesis", "hipotesis", "experimentación", "experimentacion",
    # Focos estratégicos
    "3pl", "3pls", "carrier", "carriers", "última milla", "ultima milla",
    "bff", "adaptador", "adaptadores", "sap", "bokun", "bókun",
    "integración", "integracion", "integration",
    # Tecnología
    "saas", "microservicio", "microservice", "api", "cloud",
    "infraestructura", "plataforma", "automatización", "automatizacion",
    # Cliente / competencia
    "conveniencia", "curaduría", "curaduria", "omnicanal", "omnichannel",
    "marketplace", "conversión", "conversion", "margen",
    # Shopify / Bókun (herramientas mencionadas explícitamente en el PDF)
    "shopify", "ticketing", "ticket", "reserva",
    # Diagnóstico
    "escalabilidad", "confiabilidad", "operativa",
}


def _stub_classify(email_text: str) -> bool:
    """Return True (STRATEGIC) if the email contains strategy keywords."""
    lower = email_text.lower()
    return any(kw in lower for kw in _STRATEGY_KEYWORDS)


def _stub_extract_metadata(email_text: str) -> Dict[str, Any]:
    """Extract a minimal metadata dict from raw email text."""
    lines = [l.strip() for l in email_text.strip().splitlines() if l.strip()]
    sender = next((l.split(":", 1)[1].strip() for l in lines if l.lower().startswith("de:")), "unknown@example.com")
    subject = next((l.split(":", 1)[1].strip() for l in lines if l.lower().startswith("asunto:")), "(sin asunto)")
    return {"sender": sender, "subject": subject, "body": email_text}


def _run_stub_pipeline(email_text: str) -> TriageDecisionOutput:
    """
    Deterministic triage pipeline used when crewai / real LLM is absent.

    Exercises all three tools so the full flow can be tested locally.
    """
    meta = _stub_extract_metadata(email_text)
    is_strategic = _stub_classify(email_text)

    tools = {
        "confluence": ConfluenceUpsertTool(),
        "email": EmailDraftingTool(),
        "notification": LeaderNotificationTool(),
    }

    actions: List[ActionRecord] = []
    pending: List[str] = []

    if not is_strategic:
        # JUNK path — just notify the leader of the discard
        notif_result = json.loads(
            tools["notification"].run(
                channel="telegram",
                classification="JUNK",
                summary="El correo fue descartado por no alinearse con la estrategia corporativa.",
                actions_taken=[],
                pending_approvals=[],
                original_subject=meta["subject"],
                original_sender=meta["sender"],
            )
        )
        actions.append(ActionRecord(
            tool="LeaderNotificationTool",
            status=notif_result.get("status", "ok"),
            details="Líder notificado del descarte.",
        ))
        return TriageDecisionOutput(
            classification="JUNK",
            reasoning="El correo no contiene términos ni contexto alineados con la estrategia corporativa.",
            email_summary=EmailSummary(
                sender=meta["sender"],
                subject=meta["subject"],
                key_topics=[],
            ),
            actions_taken=actions,
            pending_approvals=[],
            discarded=True,
            discard_reason="Sin alineación estratégica detectada.",
        )

    # STRATEGIC path
    key_topics = [kw for kw in _STRATEGY_KEYWORDS if kw in email_text.lower()]

    # A) Document in Confluence
    conf_result = json.loads(
        tools["confluence"].run(
            space_key="TECH",
            title=f"Oportunidad Estratégica: {meta['subject']}",
            content=(
                f"## Resumen\n\n**Remitente:** {meta['sender']}\n\n"
                f"**Asunto:** {meta['subject']}\n\n"
                f"**Temas clave:** {', '.join(key_topics)}\n\n"
                f"## Contenido Original\n\n{meta['body']}"
            ),
            labels=["triage", "estrategia"] + key_topics[:3],
        )
    )
    actions.append(ActionRecord(
        tool="ConfluenceUpsertTool",
        status=conf_result.get("status", "ok"),
        details=f"Página '{conf_result.get('action','?')}' en TECH: {conf_result.get('url','')}",
    ))

    # B) Draft collaboration email if topic warrants external input
    draft_result = json.loads(
        tools["email"].run(
            recipient_name="CTO / Product Manager",
            recipient_role="CTO",
            recipient_email="cto@empresa.com",
            subject=f"Revisión requerida: {meta['subject']}",
            context=(
                f"Hemos recibido un correo estratégico de {meta['sender']} relacionado con: "
                f"{', '.join(key_topics[:4])}."
            ),
            action_requested=(
                "Por favor confirma si debemos avanzar con una evaluación técnica formal "
                "y si contamos con presupuesto asignado para esta iniciativa."
            ),
            urgency="high",
        )
    )
    actions.append(ActionRecord(
        tool="EmailDraftingTool",
        status=draft_result.get("status", "ok"),
        details=f"Borrador listo para: {draft_result.get('draft', {}).get('to', '?')} | "
                f"Asunto: {draft_result.get('draft', {}).get('subject', '?')}",
    ))
    pending.append("Aprobar y enviar borrador de correo al CTO")

    # C) Notify leader (always for STRATEGIC)
    notif_result = json.loads(
        tools["notification"].run(
            channel="telegram",
            classification="STRATEGIC",
            summary=(
                f"Correo estratégico procesado. Temas: {', '.join(key_topics[:4])}. "
                f"Se documentó en Confluence y se redactó un borrador de seguimiento."
            ),
            actions_taken=[a.details for a in actions],
            pending_approvals=pending,
            original_subject=meta["subject"],
            original_sender=meta["sender"],
        )
    )
    actions.append(ActionRecord(
        tool="LeaderNotificationTool",
        status=notif_result.get("status", "ok"),
        details=f"Notificación enviada vía {notif_result.get('channel','?')}",
    ))

    return TriageDecisionOutput(
        classification="STRATEGIC",
        reasoning=(
            f"El correo contiene referencia a temas estratégicos: {', '.join(key_topics[:6])}. "
            "Se alinea con los pilares de transformación tecnológica y optimización de recursos."
        ),
        email_summary=EmailSummary(
            sender=meta["sender"],
            subject=meta["subject"],
            key_topics=key_topics[:6],
        ),
        actions_taken=actions,
        pending_approvals=pending,
        discarded=False,
    )


# ---------------------------------------------------------------------------
# TriageCrew — main orchestrator
# ---------------------------------------------------------------------------

class TriageCrew:
    """Triage Analytical Pipeline crew.

    When crewai + Gemini API are available the real LLM drives decisions.
    When they are absent the deterministic stub pipeline handles the flow,
    which is identical from the caller's perspective.
    """

    AGENTS_CFG = "config/agents.yaml"
    TASKS_CFG = "config/tasks.yaml"

    def __init__(self, api_key: Optional[str] = None, stub_mode: bool = False) -> None:
        load_env()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._agents_cfg = self._load_yaml(self.AGENTS_CFG)
        self._tasks_cfg = self._load_yaml(self.TASKS_CFG)

        # Output tools (write to Confluence, draft emails, notify leader)
        self.confluence_tool = ConfluenceUpsertTool()
        self.email_tool = EmailDraftingTool()
        self.notification_tool = LeaderNotificationTool()

        # Input source tools (read from email inbox and chat inbox)
        self.email_inbox_tool = EmailInboxTool()
        self.chat_inbox_tool = ChatMessageInboxTool()

        # Full tool list exposed to the crewai agent
        self._tools = [
            self.email_inbox_tool,
            self.chat_inbox_tool,
            self.confluence_tool,
            self.email_tool,
            self.notification_tool,
        ]

        # stub_mode=True (o env var TRIAGE_STUB_MODE=1) omite toda la
        # inicialización de LLMs y crewai — ideal para tests unitarios rápidos.
        stub_mode = stub_mode or os.getenv("TRIAGE_STUB_MODE", "0") == "1"

        if stub_mode:
            self.llm = None
            self.local_llm = None
            self._crew = None
            self._local_crew = None
            return

        # Build primary LLM (Gemini)
        agent_cfg = self._agents_cfg.get("agents", {}).get("triage_analyst", {})
        tier = agent_cfg.get("default_tier", "standard")
        self.llm = _build_llm(tier=tier, api_key=self.api_key)

        # Build local LLM fallback (LM Studio)
        self.local_llm = _build_local_llm()

        # Attempt to build real crewai Agent + Task
        self._crew = self._build_crewai_crew(agent_cfg, self.llm, use_pydantic_output=True)
        # Local crew: disable output_pydantic — reasoning models emit <think> blocks
        # before JSON which breaks crewai's pydantic validator. We parse raw ourselves.
        self._local_crew = self._build_crewai_crew(agent_cfg, self.local_llm, use_pydantic_output=False) if self.local_llm else None

    # ------------------------------------------------------------------
    def _load_yaml(self, path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    # ------------------------------------------------------------------
    def _build_crewai_crew(self, agent_cfg: Dict[str, Any], llm: Any = None, use_pydantic_output: bool = True) -> Optional[Any]:
        """Try to build a real crewai Crew. Returns None if crewai unavailable or llm is None."""
        if llm is None:
            return None
        try:
            from crewai import Agent, Crew, Task  # type: ignore

            agent = Agent(
                role=agent_cfg.get("role", "Nia — Analista Estratégica de Triaje"),
                goal=agent_cfg.get("goal", "Triaje de correos"),
                backstory=agent_cfg.get("backstory", ""),
                llm=llm,
                tools=self._tools,
                verbose=True,
                max_iter=3,  # Máximo 3 iteraciones — evita loops infinitos en reasoning models
                allow_delegation=False,  # No delegar tareas — evita conversaciones multi-agente
            )

            task_cfg = next(
                (t for t in self._tasks_cfg.get("tasks", []) if t.get("id") == "triage_email"),
                {},
            )

            task_kwargs: Dict[str, Any] = dict(
                description=task_cfg.get("description", "Procesa el email: {email_entrante}"),
                expected_output=task_cfg.get("expected_output", "JSON estructurado con clasificación"),
                agent=agent,
            )
            # Reasoning models (qwen3, deepseek-r1, etc.) emit a long <think>…</think>
            # block before the actual JSON.  output_pydantic tries to validate the
            # entire string and fails.  We skip it for local crews and parse raw ourselves.
            if use_pydantic_output:
                task_kwargs["output_pydantic"] = TriageDecisionOutput

            task = Task(**task_kwargs)
            return Crew(
                agents=[agent],
                tasks=[task],
                verbose=True,
                max_rpm=10,  # Rate limit: máximo 10 requests por minuto al LLM
            )
        except Exception as exc:
            logger.debug("crewai crew build failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    @staticmethod
    def _run_with_timeout(func, timeout_seconds: int = 120, **kwargs):
        """Execute a function with timeout to prevent infinite loops in reasoning models."""
        import signal
        
        def timeout_handler(signum, frame):
            raise TimeoutError(f"Function exceeded {timeout_seconds}s timeout")
        
        # Set the signal handler and alarm
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout_seconds)
        
        try:
            result = func(**kwargs)
            signal.alarm(0)  # Disable the alarm
            return result
        finally:
            signal.signal(signal.SIGALRM, old_handler)

    # ------------------------------------------------------------------
    def kickoff(self, email_entrante: str) -> TriageDecisionOutput:
        """Run the triage pipeline on the given raw email text.

        Args:
            email_entrante: Raw email text including headers like
                            ``De: ...\nAsunto: ...\n\n<body>``.

        Returns:
            TriageDecisionOutput validated Pydantic model.
        """
        if not email_entrante or not email_entrante.strip():
            raise ValueError("email_entrante must be a non-empty string")

        # ── Tier 1: Local LM Studio (primary) ───────────────────────────────
        # El modelo local es el motor principal de Nia. Solo recurre a Gemini
        # si falla (ej: contexto demasiado largo) o si no está disponible.
        if self._local_crew is not None:
            try:
                logger.info("Running triage with local LLM (LM Studio — primary)…")
                raw = self._run_with_timeout(
                    self._local_crew.kickoff,
                    inputs={"email_entrante": email_entrante},
                    timeout_seconds=120  # 2 minutos máximo
                )
                return self._parse_crewai_output(raw, email_entrante)
            except TimeoutError:
                logger.warning("Local LLM timeout (120s) — reasoning model loop detected; trying Gemini fallback…")
            except Exception as exc:
                # Si es un error de contexto demasiado largo, intentamos Gemini
                is_context_error = "context length" in str(exc).lower() or "400" in str(exc)
                if is_context_error:
                    logger.warning("Local LLM context overflow; trying Gemini fallback…")
                else:
                    logger.warning("Local LLM kickoff failed (%s); trying Gemini fallback…", exc)

        # ── Tier 2: Gemini (fallback) ───────────────────────────────────────
        if self._crew is not None:
            try:
                logger.info("Running triage with Gemini (fallback)…")
                raw = self._run_with_timeout(
                    self._crew.kickoff,
                    inputs={"email_entrante": email_entrante},
                    timeout_seconds=60  # 1 minuto máximo para Gemini
                )
                return self._parse_crewai_output(raw, email_entrante)
            except TimeoutError:
                logger.warning("Gemini timeout (60s); falling back to stub")
            except Exception as exc:
                is_quota = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
                if is_quota:
                    logger.warning("Gemini quota exhausted (429); falling back to stub")
                else:
                    logger.warning("Gemini kickoff failed (%s); falling back to stub", exc)

        # ── Tier 3: Deterministic stub ──────────────────────────────────────
        logger.warning("All LLMs unavailable — using deterministic stub pipeline")
        return _run_stub_pipeline(email_entrante)

    # ------------------------------------------------------------------
    def kickoff_conversation(self, user_message: str, conversation_history: list = None) -> str:
        """Run a lightweight conversation (NO REASONING) for quick responses.
        
        Diferencia clave con kickoff():
        - kickoff() → Triage analítico profundo con reasoning habilitado
        - kickoff_conversation() → Respuestas rápidas sin <think> blocks
        
        Args:
            user_message: Mensaje del usuario (pregunta, saludo, etc.)
            conversation_history: Lista de mensajes previos (opcional)
            
        Returns:
            Respuesta de texto directo (no TriageDecisionOutput)
        """
        # Build temporary LLM WITHOUT reasoning for fast responses
        conversation_llm = _build_local_llm(enable_reasoning=False)
        
        if conversation_llm is None:
            return "Lo siento, no puedo procesar tu mensaje en este momento."
        
        try:
            from crewai import Agent, Crew, Task  # type: ignore
            
            # Agent con personalidad de Nia pero sin herramientas de triage
            agent = Agent(
                role="Nia — Asistente Conversacional",
                goal="Responder preguntas y mantener conversaciones naturales",
                backstory=self._agents_cfg.get("agents", {}).get("triage_analyst", {}).get("backstory", ""),
                llm=conversation_llm,
                tools=[],  # Sin herramientas — solo conversación
                verbose=False,
                max_iter=1,  # Solo una respuesta directa
                allow_delegation=False,
            )
            
            # Task de conversación simple
            context_str = ""
            if conversation_history:
                context_str = "\n\nContexto de la conversación previa:\n"
                context_str += "\n".join([f"- {msg['role']}: {msg['content']}" for msg in conversation_history[-5:]])
            
            task = Task(
                description=f"""Responde de forma natural y conversacional al usuario.
                
Mensaje del usuario: {user_message}
{context_str}

IMPORTANTE:
- Responde DIRECTAMENTE en texto plano (no JSON)
- Sé breve y clara (máximo 2-3 oraciones)
- Usa un tono amigable y profesional
- NO uses bloques de razonamiento (<think>, etc.)
- Si te preguntan sobre triaje, ofrece ayuda pero no ejecutes triage aquí
""",
                expected_output="Respuesta conversacional en texto plano",
                agent=agent,
            )
            
            crew = Crew(
                agents=[agent],
                tasks=[task],
                verbose=False,
            )
            
            # Ejecutar con timeout corto (30s para conversación)
            raw = self._run_with_timeout(
                crew.kickoff,
                timeout_seconds=30
            )
            
            # Extraer texto de la respuesta
            if hasattr(raw, "raw"):
                return raw.raw.strip()
            return str(raw).strip()
            
        except TimeoutError:
            return "Disculpa, tardé demasiado en responder. ¿Puedes reformular tu pregunta?"
        except Exception as exc:
            logger.warning("Conversation kickoff failed: %s", exc)
            return "Ocurrió un error procesando tu mensaje. ¿Puedes intentar de nuevo?"

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_crewai_output(raw: Any, email_text: str) -> TriageDecisionOutput:
        """Best-effort parse of a crewai CrewOutput into TriageDecisionOutput.

        crewai 1.x returns a ``CrewOutput`` object with three attributes:
          - ``.pydantic``   : Already-validated Pydantic model (when output_pydantic set)
          - ``.json_dict``  : Parsed dict (when output is valid JSON)
          - ``.raw``        : Raw string output from the LLM
        
        Para modelos razonadores (qwen3, deepseek-r1, etc):
        - Detecta y remueve bloques <think>...</think>
        - Extrae solo la respuesta final (JSON después del razonamiento)
        - Registra cuando encuentra cadenas de pensamiento
        """
        try:
            # 1) Best case: crewai already validated into our Pydantic model
            if hasattr(raw, "pydantic") and raw.pydantic is not None:
                data = raw.pydantic.model_dump()
                return TriageDecisionOutput(**data)

            # 2) crewai parsed JSON dict
            if hasattr(raw, "json_dict") and raw.json_dict:
                return TriageDecisionOutput(**raw.json_dict)

            # 3) Raw string — strip reasoning blocks and extract final answer
            text = raw.raw if hasattr(raw, "raw") else str(raw)
            original_length = len(text)
            
            # Detectar y remover bloques de razonamiento comunes:
            # - <think>...</think> (qwen3.5, deepseek-r1)
            # - <reasoning>...</reasoning> (algunos modelos custom)
            # - <!-- thinking -->...</!-- /thinking --> (modelos que usan comentarios HTML)
            import re as _re
            
            # Remover bloques <think>
            text_after_think = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL | _re.IGNORECASE)
            
            # Remover bloques <reasoning>
            text_after_reasoning = _re.sub(r"<reasoning>.*?</reasoning>", "", text_after_think, flags=_re.DOTALL | _re.IGNORECASE)
            
            # Remover comentarios HTML de pensamiento
            text_cleaned = _re.sub(r"<!--\s*thinking\s*-->.*?<!--\s*/thinking\s*-->", "", text_after_reasoning, flags=_re.DOTALL | _re.IGNORECASE)
            
            text = text_cleaned.strip()
            
            # Log cuando detectamos razonamiento (útil para debug)
            if len(text) < original_length * 0.8:  # Si eliminamos más del 20%
                removed_chars = original_length - len(text)
                logger.info(
                    "🧠 Reasoning block detected and removed: %d chars → %d chars (-%d)",
                    original_length, len(text), removed_chars
                )

            # Strip markdown code fences (```json...```)
            if "```" in text:
                parts = text.split("```")
                # Buscar el primer bloque que parezca JSON
                for part in parts[1::2]:  # Solo bloques dentro de ```
                    if part.strip().startswith("json"):
                        text = part[4:].strip()
                        break
                    elif part.strip().startswith("{"):
                        text = part.strip()
                        break

            # Extraer el JSON final (última aparición si hay múltiples)
            # Algunos modelos reasoning emiten JSON, luego piensan, luego JSON final
            matches = list(_re.finditer(r"\{.*?\}", text, _re.DOTALL))
            if matches:
                # Tomar el ÚLTIMO match (respuesta final después de razonar)
                text = matches[-1].group(0)
                if len(matches) > 1:
                    logger.debug("Multiple JSON objects found, using the last one (final answer)")

            data = json.loads(text.strip())
            return TriageDecisionOutput(**data)

        except Exception as exc:
            logger.warning("Could not parse crewai output as TriageDecisionOutput: %s", exc)
            meta = _stub_extract_metadata(email_text)
            raw_text = getattr(raw, "raw", None) or str(raw)
            return TriageDecisionOutput(
                classification="STRATEGIC",
                reasoning=raw_text[:500],
                email_summary=EmailSummary(sender=meta["sender"], subject=meta["subject"]),
                actions_taken=[],
                pending_approvals=["Revisar output del agente manualmente"],
            )

    # ------------------------------------------------------------------
    # Inbox polling
    # ------------------------------------------------------------------

    def poll(
        self,
        max_messages: int = 20,
    ) -> Generator[Tuple[Dict[str, Any], TriageDecisionOutput], None, None]:
        """Poll email and chat inboxes and triage every pending message.

        Yields (message_dict, TriageDecisionOutput) pairs for each message
        processed, so callers can log, display or forward results incrementally.

        Args:
            max_messages: Upper bound on messages to process per poll call.

        Example::

            crew = TriageCrew()
            for msg, result in crew.poll():
                print(msg["subject"], "→", result.classification)
        """
        total = 0

        # --- Email inbox ---
        raw_email = json.loads(
            self.email_inbox_tool.run(max_messages=max_messages, mark_as_read=True)
        )
        for msg in raw_email.get("messages", []):
            if total >= max_messages:
                break
            text = message_to_triage_text(msg)
            result = self.kickoff(text)
            total += 1
            yield msg, result

        # --- Chat inbox ---
        remaining = max_messages - total
        if remaining > 0:
            raw_chat = json.loads(
                self.chat_inbox_tool.run(max_messages=remaining, mark_as_read=True)
            )
            for msg in raw_chat.get("messages", []):
                if total >= max_messages:
                    break
                text = message_to_triage_text(msg)
                result = self.kickoff(text)
                total += 1
                yield msg, result

        if total == 0:
            logger.info("[TriageCrew.poll] No pending messages in any inbox.")


# ---------------------------------------------------------------------------
# Convenience entry-points
# ---------------------------------------------------------------------------

def run_triage(email_entrante: str, api_key: Optional[str] = None) -> TriageDecisionOutput:
    """Load env, build TriageCrew and run kickoff on a raw email/chat text.

    Args:
        email_entrante: Raw message text in the format::

            De: sender@example.com
            Asunto: Subject line

            Body of the message...

    Returns:
        TriageDecisionOutput validated Pydantic model.
    """
    crew = TriageCrew(api_key=api_key)
    return crew.kickoff(email_entrante)


def run_triage_from_inboxes(
    api_key: Optional[str] = None,
    max_messages: int = 20,
) -> List[Tuple[Dict[str, Any], TriageDecisionOutput]]:
    """Poll both inboxes (email + chat) and triage all pending messages.

    Returns a list of (message_dict, TriageDecisionOutput) pairs.

    Usage::

        # 1. Enqueue messages from anywhere
        from src.input_sources import EmailInboxTool, ChatMessageInboxTool
        EmailInboxTool.enqueue(sender="partner@saas.io", subject="Propuesta", body="...")
        ChatMessageInboxTool.enqueue(sender="@ceo", body="¿Viste la propuesta de Shopify?")

        # 2. Run triage on all pending
        results = run_triage_from_inboxes()
        for msg, decision in results:
            print(msg["subject"], "→", decision.classification)
    """
    crew = TriageCrew(api_key=api_key)
    return list(crew.poll(max_messages=max_messages))


__all__ = [
    "TriageCrew",
    "TriageDecisionOutput",
    "ActionRecord",
    "EmailSummary",
    "run_triage",
    "run_triage_from_inboxes",
    # Legacy exports kept for backward compat
    "load_env",
    "MODEL_TIERS",
]
