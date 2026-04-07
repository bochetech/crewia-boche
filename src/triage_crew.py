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
import re
from typing import Any, Dict, Generator, List, Optional, Tuple

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.tools import (
    ConfluenceUpsertTool,
    EmailDraftingTool,
    LeaderNotificationTool,
)
from src.strategy_tools.html_strategy_tool import HTMLStrategyTool
from src.input_sources import (
    EmailInboxTool,
    ChatMessageInboxTool,
    message_to_triage_text,
)

logger = logging.getLogger(__name__)

try:
    from crewai_tools import SerperDevTool  # type: ignore
except ImportError:
    SerperDevTool = None  # type: ignore
    logger.warning("SerperDevTool not available (install: pip install crewai-tools)")

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


# ---------------------------------------------------------------------------
# Reasoning sanitizer callback for CrewAI (DEPRECATED)
# ---------------------------------------------------------------------------

def _sanitize_reasoning_callback(step_output: Any) -> Any:
    """CrewAI step_callback para limpiar razonamiento visible de modelos LLM.
    
    ⚠️ DEPRECATED: Este callback ya no es necesario cuando se usa LMStudioLiteLLM.
    La API nativa de LM Studio separa razonamiento de mensajes mediante el
    atributo type en el output array, sin necesidad de regex frágiles.
    
    Se mantiene para compatibilidad con litellm estándar (Gemini, etc.)
    
    Soporta:
    1. Formato nativo LM Studio: output array con type="reasoning"|"message"
    2. Tags XML: <think>...</think>, <reasoning>...</reasoning>
    3. Comentarios HTML: <!-- thinking -->...<!-- /thinking -->
    4. Preámbulos analíticos: "Let me craft...", "I need to...", etc.
    5. Respuestas duplicadas: múltiples saludos o respuestas repetidas
    
    Args:
        step_output: Objeto CrewAI step output con atributo .output (string)
    
    Returns:
        El mismo objeto modificado con .output limpio
    """
    import re
    
    if not hasattr(step_output, 'output') or not isinstance(step_output.output, str):
        return step_output
    
    original = step_output.output
    cleaned = original
    
    # Paso 0: Detectar formato nativo LM Studio (output array)
    # Si litellm devolviera el JSON crudo del endpoint /api/v1/chat, extraer solo los mensajes
    try:
        # Intentar parsear como JSON para detectar estructura {"output": [...]}
        if original.strip().startswith('{') and '"output"' in original:
            data = json.loads(original)
            if isinstance(data.get('output'), list):
                # Extraer solo elementos con type="message"
                messages = [
                    item['content']
                    for item in data['output']
                    if isinstance(item, dict) and item.get('type') == 'message'
                ]
                if messages:
                    cleaned = '\n\n'.join(messages)
                    logger.debug("Reasoning sanitizer: extracted %d message(s) from LM Studio output array", len(messages))
                    step_output.output = cleaned
                    return step_output
    except (json.JSONDecodeError, KeyError, TypeError):
        pass  # No es formato LM Studio, continuar con otros métodos
    
    # Paso 1: Remover tags XML de razonamiento
    cleaned = re.sub(r'<think>.*?</think>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'<reasoning>.*?</reasoning>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    
    # Paso 2: Remover comentarios HTML de thinking
    cleaned = re.sub(
        r'<!--\s*thinking\s*-->.*?<!--\s*/thinking\s*-->',
        '',
        cleaned,
        flags=re.DOTALL | re.IGNORECASE
    )
    
    cleaned = cleaned.strip()
    
    # Paso 3: Detectar y remover preámbulos analíticos (razonamiento en texto plano)
    # El modelo puede escribir razonamiento visible antes del contenido útil.
    
    # Primero: remover frases típicas de "internal thinking" en inglés
    thinking_phrases = [
        r'Let me craft.*?answer:?\s*',
        r'Let me think.*?\n',
        r'I need to.*?\n',
        r'First,?\s+I.*?\n',
        r'My approach.*?\n',
        r'I\'ll start.*?\n',
        r'Internal reasoning:.*?\n',
    ]
    for phrase_pattern in thinking_phrases:
        cleaned = re.sub(phrase_pattern, '', cleaned, flags=re.IGNORECASE)
    
    cleaned = cleaned.strip()
    
    # Segundo: buscar patrones que indican el INICIO del contenido real
    content_start_patterns = [
        (r'\n#+\s+[A-ZÁÉÍÓÚÑ¡]', 0),          # \n## Título o ¡Hola!
        (r'\n\n[A-ZÁÉÍÓÚÑ¡][a-záéíóúñ]{2,}', 0),  # \n\nLa respuesta... o \n\n¡Hola!
        (r'\n(Para |La |El |Los |Las |En |Según |Descorcha |Nia |Basándome |Hola|¡Hola)', 0),
        (r'\n(Sí[,\.]|No[,\.]|Claro[,\.]|Por supuesto[,\.])', 0),
        (r'\n\d+\.\s+[A-ZÁÉÍÓÚÑ]', 0),       # \n1. Item
        (r'\n[-*]\s+[A-ZÁÉÍÓÚÑ]', 0),        # \n- Item
        (r'\n\{', 0),                         # \n{ (JSON response)
    ]
    
    best_pos = len(cleaned)
    for pattern, offset in content_start_patterns:
        match = re.search(pattern, cleaned)
        if match and match.start() < best_pos:
            best_pos = match.start() + offset
    
    # Si encontramos un punto de corte temprano (primeros 80% del texto)
    # y el contenido restante es sustancial (>30 chars), aplicar el corte
    if best_pos < len(cleaned) * 0.8:
        candidate = cleaned[best_pos:].strip()
        if len(candidate) > 30:
            cleaned = candidate
            logger.debug("Reasoning sanitizer: removed %d chars of preamble", len(original) - len(cleaned))
    
    # Paso 4: Eliminar respuestas duplicadas (el modelo a veces responde 2 veces)
    # Si hay múltiples saludos/respuestas similares, quedarse con la última
    lines = cleaned.split('\n')
    # Detectar si hay múltiples "¡Hola!" o respuestas duplicadas
    greeting_indices = [i for i, line in enumerate(lines) if line.strip().lower().startswith(('¡hola', 'hola!'))]
    if len(greeting_indices) >= 2:
        # Quedarse solo desde el último saludo en adelante
        last_greeting_idx = greeting_indices[-1]
        cleaned = '\n'.join(lines[last_greeting_idx:])
        logger.debug("Reasoning sanitizer: removed duplicate responses, kept last greeting")
    
    step_output.output = cleaned
    return step_output


def _build_local_llm(enable_reasoning: bool = True) -> Any:
    """Build an LLM pointing to the local LM Studio server.

    Usa crewai.LLM con litellm en modo OpenAI-compatible apuntando a LM Studio.
    
    Args:
        enable_reasoning: Si True, permite reasoning para análisis profundo (triage).
                         Si False, desactiva reasoning para respuestas rápidas (conversación).

    Reads from .env:
      LMSTUDIO_BASE_URL  (default: http://localhost:1234/v1)
      LMSTUDIO_MODEL     (opcional: nombre específico del modelo.
                          Si no se define, usa el modelo activo en LM Studio)

    LM Studio expone endpoint OpenAI-compatible en /v1/chat/completions
    que litellm puede consumir con formato "openai/<model>"
    """
    try:
        from crewai import LLM
        
        # Leer configuración de .env
        base_url = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
        model_name = os.getenv("LMSTUDIO_MODEL", "lmstudio-model")  # nombre dummy
        
        # Normalizar base_url para asegurar /v1 al final
        if not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        
        # Probar conexión al servidor LM Studio
        import requests
        try:
            # Endpoint de modelos disponibles
            models_url = base_url.replace("/v1", "") + "/v1/models"
            response = requests.get(models_url, timeout=2)
            
            if response.status_code == 200:
                models_data = response.json()
                available_models = models_data.get("data", [])
                if available_models:
                    # Usar el primer modelo activo
                    model_name = available_models[0].get("id", model_name)
                    logger.debug("LM Studio modelo detectado: %s", model_name)
        except Exception as check_exc:
            logger.debug("No se pudo verificar modelos en LM Studio: %s", check_exc)
        
        # Crear LLM de CrewAI apuntando a LM Studio
        # Formato: "openai/<model>" con base_url personalizada
        llm = LLM(
            model=f"openai/{model_name}",
            base_url=base_url,
            api_key="lm-studio",  # Dummy key (LM Studio no requiere auth)
            temperature=0.7,
            max_tokens=4000 if enable_reasoning else 1500,
        )
        
        logger.debug("LM Studio LLM creado: %s @ %s", model_name, base_url)
        return llm
        
    except Exception as exc:
        logger.debug("Could not build LM Studio LLM: %s", exc)
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

        # NOTA: Ya NO usamos ConfluenceUpsertTool, EmailDraftingTool ni LeaderNotificationTool
        # El único flujo es Multi-Agent Strategy Crew → HTMLStrategyTool (SSOT único)
        
        # Input source tools (read from email inbox and chat inbox)
        self.email_inbox_tool = EmailInboxTool()
        self.chat_inbox_tool = ChatMessageInboxTool()

        # stub_mode=True (o env var TRIAGE_STUB_MODE=1) omite toda la
        # inicialización de LLMs y crewai — ideal para tests unitarios rápidos.
        stub_mode = stub_mode or os.getenv("TRIAGE_STUB_MODE", "0") == "1"

        if stub_mode:
            self.llm = None
            self.local_llm = None
            return

        # ── PRIORIDAD: LM STUDIO LOCAL → GEMINI API (FALLBACK) ──────────────
        # Intentar construir LLM local (LM Studio) primero
        logger.info("🔍 Intentando conectar con LM Studio local...")
        local_llm = _build_local_llm(enable_reasoning=True)
        
        if local_llm is not None:
            logger.info("✅ LM Studio conectado exitosamente - usando modelo local")
            self.llm = local_llm
        else:
            logger.warning("⚠️ LM Studio no disponible, usando Gemini API como fallback")
            agent_cfg = self._agents_cfg.get("agents", {}).get("triage_analyst", {})
            tier = agent_cfg.get("default_tier", "standard")
            self.llm = _build_llm(tier=tier, api_key=self.api_key)

    # ------------------------------------------------------------------
    def _load_yaml(self, path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    # ------------------------------------------------------------------
    @staticmethod
    def _run_with_timeout(func, timeout_seconds: int = 120, **kwargs):
        """Execute a function with timeout to prevent infinite loops in reasoning models.
        
        Uses threading instead of signal.SIGALRM to work in executor threads.
        """
        import threading
        
        result = [None]
        exception = [None]
        
        def target():
            try:
                result[0] = func(**kwargs)
            except Exception as exc:
                exception[0] = exc
        
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(timeout=timeout_seconds)
        
        if thread.is_alive():
            # Thread still running after timeout
            raise TimeoutError(f"Function exceeded {timeout_seconds}s timeout")
        
        if exception[0]:
            raise exception[0]
        
        return result[0]

    # ------------------------------------------------------------------
    def _ensure_html_written(
        self,
        ba_output: Dict[str, Any],
        initiative_input: str,
        foco: Optional[str],
        researcher_output: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Guarantee the initiative is written to the HTML SSOT.

        The BA agent may report html_updated=True without having called the
        tool (LLM hallucination). This method checks whether an entry with
        the expected initiative_id actually exists in the HTML file; if not,
        it writes the initiative programmatically using the structured data
        that the BA reported.

        Returns the (possibly updated) ba_output dict, always with a real
        initiative_id and html_updated=True on success.
        
        Guards:
        - If ba_output has no meaningful content (title is generic placeholder),
          skip writing — the agent did not produce useful data.
        - Use a lower similarity threshold (0.7) to avoid near-duplicates.
        """
        from src.strategy_tools.html_strategy_tool import HTMLStrategyTool

        html_tool = HTMLStrategyTool()

        # 1. Determine the initiative_id the agent claimed to have written
        initiative_id = ba_output.get("initiative_id", "")

        # 2. Check if it actually exists in the HTML
        already_written = False
        if initiative_id:
            result = json.loads(html_tool._run(action="read", initiative_id=initiative_id))
            already_written = result.get("status") == "ok"

        if already_written:
            logger.info("✅ [ensure_html_written] Iniciativa %s ya existe en HTML — BA usó el tool correctamente", initiative_id)
            ba_output["html_updated"] = True
            return ba_output

        # 3. The HTML was NOT written — apply programmatic fallback
        logger.warning("⚠️ [ensure_html_written] BA no escribió al HTML (hallucination). Aplicando fallback programático…")
        print("\n⚠️  [ensure_html_written] Escritura programática al HTML (el agente no llamó al tool)\n")

        # Build initiative_data from BA output or sensible defaults
        content = ba_output.get("content", {}) or {}
        safe_foco = foco if foco in ("F1", "F2", "F3", "F4") else "F4"

        # ── GUARD: no escribir si no hay contenido real ───────────────────────
        # Si el BA no generó datos significativos (título es genérico o vacío),
        # significa que el parser falló y no hay información útil para escribir.
        title_candidate = (
            content.get("title")
            or ba_output.get("title")
            or ""
        ).strip()
        is_generic_title = (
            not title_candidate
            or title_candidate.lower().startswith("iniciativa estratégica (")
            or title_candidate.lower() == "tbd"
        )
        has_objective = bool(
            content.get("objective")
            or ba_output.get("objective")
            or ""
        )

        if is_generic_title and not has_objective:
            logger.warning(
                "⚠️ [ensure_html_written] BA output sin contenido real (título genérico, sin objetivo). "
                "Omitiendo escritura para evitar entrada vacía."
            )
            ba_output["html_updated"] = False
            ba_output["skip_reason"] = "no_content"
            return ba_output

        # ── SEARCH for duplicates with a lower threshold ──────────────────────
        # Use 0.7 instead of 0.85 to catch near-duplicates with slightly different wording
        search_result = json.loads(
            html_tool._run(action="search", query=initiative_input[:300], threshold=0.7)
        )
        matches = search_result.get("matches", [])

        if matches:
            # UPDATE existing initiative
            best_match = matches[0]
            existing_id = best_match.get("initiative_id", "")
            similarity = best_match.get("similarity", 0)
            logger.info("[ensure_html_written] Duplicado encontrado: %s (sim=%.2f) — actualizando", existing_id, similarity)

            new_content = {
                "title": title_candidate or f"Iniciativa estratégica ({safe_foco})",
                "objective": content.get("objective") or initiative_input[:200],
                "impact": content.get("impact") or researcher_output.get("effort_estimate", "TBD"),
                "owner": content.get("owner") or "TBD",
                "deadline": content.get("deadline") or "TBD",
            }
            write_result = json.loads(
                html_tool._run(
                    action="update",
                    initiative_id=existing_id,
                    new_content=new_content,
                    mark_changed=True,
                )
            )
            if write_result.get("status") == "ok":
                logger.info("✅ [ensure_html_written] Iniciativa %s actualizada", existing_id)
                ba_output["action"] = "MODIFICACIÓN"
                ba_output["initiative_id"] = existing_id
                ba_output["html_updated"] = True
            else:
                logger.error("❌ [ensure_html_written] Error actualizando: %s", write_result)
                ba_output["html_updated"] = False
        else:
            # CREATE new initiative
            initiative_data = {
                "title": title_candidate or f"Iniciativa estratégica ({safe_foco})",
                "status": content.get("status") or "Planificado",
                "objective": content.get("objective") or initiative_input[:200],
                "impact": content.get("impact") or "TBD",
                "owner": content.get("owner") or "TBD",
                "deadline": content.get("deadline") or "TBD",
            }
            write_result = json.loads(
                html_tool._run(action="create", foco=safe_foco, initiative_data=initiative_data)
            )
            if write_result.get("status") == "ok":
                new_id = write_result.get("initiative_id", "")
                logger.info("✅ [ensure_html_written] Nueva iniciativa creada: %s", new_id)
                ba_output["action"] = "NUEVA_INICIATIVA"
                ba_output["initiative_id"] = new_id
                ba_output["html_updated"] = True
            else:
                logger.error("❌ [ensure_html_written] Error creando: %s", write_result)
                ba_output["html_updated"] = False

        return ba_output

    # ------------------------------------------------------------------
    def kickoff_strategy_crew(self, initiative_input: str) -> Dict[str, Any]:
        """Run multi-agent strategy crew to process strategic initiative.
        
        Flujo completo:
        1. Triage Strategist clasifica en F1-F4 (single-agent crew)
        2. Business Analyst (deduplicación + escribe HTML) y Researcher
           (validación técnica) se ejecutan en paralelo real con threads.
        3. _ensure_html_written garantiza escritura programática como fallback.
        4. Coordinator aprueba resultado final (single-agent crew).
        
        Args:
            initiative_input: Descripción de la iniciativa
            
        Returns:
            Dict con resultado del procesamiento multi-agente
        """
        try:
            import threading
            from crewai import Agent, Crew, Task  # type: ignore
            
            logger.info("🚀 Activando Multi-Agent Strategy Crew…")

            # ── Helper: extract JSON from a Task after kickoff ─────────────
            def _extract_task_output(task: "Task", crew_result: Any) -> Dict[str, Any]:
                """Return parsed JSON from task.output.raw first, then CrewOutput."""
                # 1. task.output.raw  → Final Answer only (no verbose frame)
                if hasattr(task, 'output') and task.output:
                    t = task.output
                    if hasattr(t, 'json_dict') and t.json_dict:
                        return t.json_dict
                    if hasattr(t, 'raw') and t.raw:
                        parsed = self._parse_json_output(t.raw)
                        if parsed:
                            return parsed
                # 2. Fallback: CrewOutput
                if hasattr(crew_result, 'json_dict') and crew_result.json_dict:
                    return crew_result.json_dict
                if hasattr(crew_result, 'raw') and crew_result.raw:
                    return self._parse_json_output(crew_result.raw)
                return self._parse_json_output(str(crew_result))

            # ── PASO 1: TRIAGE STRATEGIST (clasificación F1-F4) ──────────────
            strategist_cfg = self._agents_cfg.get("agents", {}).get("triage_strategist", {})
            strategist_agent = Agent(
                role=strategist_cfg.get("role", "Estratega de Clasificación"),
                goal=strategist_cfg.get("goal", "Clasificar iniciativa en Focos F1-F4"),
                backstory=strategist_cfg.get("backstory", ""),
                llm=self.llm,
                tools=[],
                verbose=True,
                max_iter=1,
                allow_delegation=False,
            )
            strategy_task_cfg = next(
                (t for t in self._tasks_cfg.get("tasks", []) if t.get("id") == "strategy_classify"),
                {}
            )
            strategist_task = Task(
                description=strategy_task_cfg.get("description", "Clasificar iniciativa").format(
                    initiative_input=initiative_input
                ),
                expected_output=strategy_task_cfg.get("expected_result", "JSON con foco"),
                agent=strategist_agent,
            )
            strategist_crew = Crew(
                agents=[strategist_agent],
                tasks=[strategist_task],
                verbose=True,
            )
            logger.info("🔍 Paso 1: Triage Strategist clasificando iniciativa…")
            strategist_result = strategist_crew.kickoff()
            strategist_output = _extract_task_output(strategist_task, strategist_result)
            logger.debug("Strategist output: %s", strategist_output)

            if strategist_output.get("classification") == "JUNK":
                logger.warning("❌ Iniciativa rechazada por Triage Strategist: no es estratégica")
                return {
                    "status": "rejected",
                    "reason": strategist_output.get("reasoning", "No alineada con Focos estratégicos"),
                    "details": strategist_output,
                }

            foco = strategist_output.get("foco")
            logger.info("✅ Foco detectado: %s", foco)

            # ── PASO 2 & 3: BA + RESEARCHER en threads paralelos reales ──────
            # CrewAI sequential process always runs tasks one-by-one.
            # True parallelism requires running two independent single-task Crews
            # in separate threads and joining them.
            ba_cfg = self._agents_cfg.get("agents", {}).get("business_analyst", {})
            researcher_cfg = self._agents_cfg.get("agents", {}).get("researcher", {})
            ba_task_cfg = next(
                (t for t in self._tasks_cfg.get("tasks", []) if t.get("id") == "strategy_document"),
                {}
            )
            researcher_task_cfg = next(
                (t for t in self._tasks_cfg.get("tasks", []) if t.get("id") == "strategy_research"),
                {}
            )

            # Results containers (mutable so threads can write to them)
            ba_result_box: Dict[str, Any] = {}
            researcher_result_box: Dict[str, Any] = {}
            ba_error_box: List[str] = []
            researcher_error_box: List[str] = []

            def _run_ba():
                try:
                    html_tool_instance = HTMLStrategyTool()
                    _ba_agent = Agent(
                        role=ba_cfg.get("role", "Analista de Negocio"),
                        goal=ba_cfg.get("goal", "Documentar iniciativa sin duplicar"),
                        backstory=ba_cfg.get("backstory", ""),
                        llm=self.llm,
                        tools=[html_tool_instance],
                        verbose=True,
                        max_iter=3,
                        allow_delegation=False,
                    )
                    _ba_task = Task(
                        description=ba_task_cfg.get("description", "Documentar iniciativa").format(
                            initiative_input=initiative_input,
                            foco=foco
                        ),
                        expected_output=ba_task_cfg.get("expected_result", "JSON con HTML updated"),
                        agent=_ba_agent,
                    )
                    _ba_crew = Crew(agents=[_ba_agent], tasks=[_ba_task], verbose=True)
                    _result = _ba_crew.kickoff()
                    ba_result_box.update(_extract_task_output(_ba_task, _result))
                except Exception as exc:
                    logger.error("❌ BA thread error: %s", exc)
                    ba_error_box.append(str(exc))

            def _run_researcher():
                try:
                    # Use SerperDevTool if available, otherwise run without search tool
                    _researcher_tools = []
                    if SerperDevTool is not None:
                        try:
                            _researcher_tools = [SerperDevTool()]
                        except Exception as st_exc:
                            logger.warning("SerperDevTool instantiation failed: %s", st_exc)

                    _researcher_agent = Agent(
                        role=researcher_cfg.get("role", "Investigador Técnico"),
                        goal=researcher_cfg.get("goal", "Validar viabilidad técnica"),
                        backstory=researcher_cfg.get("backstory", ""),
                        llm=self.llm,
                        tools=_researcher_tools,
                        verbose=True,
                        max_iter=2,
                        allow_delegation=False,
                    )
                    _researcher_task = Task(
                        description=researcher_task_cfg.get("description", "Validar técnicamente").format(
                            initiative_input=initiative_input
                        ),
                        expected_output=researcher_task_cfg.get("expected_result", "JSON con viabilidad"),
                        agent=_researcher_agent,
                    )
                    _researcher_crew = Crew(agents=[_researcher_agent], tasks=[_researcher_task], verbose=True)
                    _result = _researcher_crew.kickoff()
                    researcher_result_box.update(_extract_task_output(_researcher_task, _result))
                except Exception as exc:
                    logger.error("❌ Researcher thread error: %s", exc)
                    researcher_error_box.append(str(exc))

            logger.info("📝 Paso 2: Business Analyst + Researcher trabajando en paralelo…")
            ba_thread = threading.Thread(target=_run_ba, daemon=True)
            researcher_thread = threading.Thread(target=_run_researcher, daemon=True)
            ba_thread.start()
            researcher_thread.start()
            ba_thread.join(timeout=300)       # 5-minute hard limit per agent
            researcher_thread.join(timeout=300)

            if ba_thread.is_alive():
                logger.warning("⚠️ BA thread timed out after 300s — using empty output")
            if researcher_thread.is_alive():
                logger.warning("⚠️ Researcher thread timed out after 300s — using empty output")

            ba_output: Dict[str, Any] = ba_result_box
            researcher_output: Dict[str, Any] = researcher_result_box

            logger.info("✅ BA completado: %s", ba_output.get('action', 'unknown'))
            logger.info("✅ Researcher completado: viable=%s", researcher_output.get('viable', 'unknown'))

            # ── FALLBACK PROGRAMÁTICO: garantizar escritura real en HTML ──────
            ba_output = self._ensure_html_written(
                ba_output=ba_output,
                initiative_input=initiative_input,
                foco=foco,
                researcher_output=researcher_output,
            )

            # ── PASO 4: COORDINATOR (aprobación final) ────────────────────────
            coordinator_cfg = self._agents_cfg.get("agents", {}).get("coordinator", {})
            coordinator_agent = Agent(
                role=coordinator_cfg.get("role", "Coordinador Estratégico"),
                goal=coordinator_cfg.get("goal", "Aprobar resultado final"),
                backstory=coordinator_cfg.get("backstory", ""),
                llm=self.llm,
                tools=[],
                verbose=True,
                max_iter=1,
                allow_delegation=False,
            )
            coordinator_task_cfg = next(
                (t for t in self._tasks_cfg.get("tasks", []) if t.get("id") == "strategy_coordinate"),
                {}
            )
            approval_input = (
                f"Iniciativa: {initiative_input}\n\n"
                f"Resultados del crew:\n"
                f"- Foco: {foco}\n"
                f"- BA: {json.dumps(ba_output, ensure_ascii=False)}\n"
                f"- Researcher: {json.dumps(researcher_output, ensure_ascii=False)}\n\n"
                f"¿Aprobar escritura al HTML SSOT?"
            )
            coordinator_task = Task(
                description=coordinator_task_cfg.get("description", "Aprobar resultado").format(
                    initiative_input=approval_input
                ),
                expected_output=coordinator_task_cfg.get("expected_result", "JSON con aprobación"),
                agent=coordinator_agent,
            )
            coordinator_crew = Crew(
                agents=[coordinator_agent],
                tasks=[coordinator_task],
                verbose=True,
            )
            logger.info("🎯 Paso 3: Coordinator revisando resultado…")
            coordinator_result = coordinator_crew.kickoff()
            coordinator_output = _extract_task_output(coordinator_task, coordinator_result)
            logger.debug("Coordinator output: %s", coordinator_output)

            # Aprobación: Coordinator dice APPROVED, o el HTML ya fue escrito (fallback)
            coordinator_approved = coordinator_output.get("action") == "APPROVED"
            html_was_written = ba_output.get("html_updated", False)

            if coordinator_approved or html_was_written:
                if not coordinator_approved:
                    logger.info("✅ Coordinator no parseado pero HTML ya escrito — aprobando por fallback")
                else:
                    logger.info("✅ ¡Iniciativa APROBADA por Coordinator!")
                return {
                    "status": "approved",
                    "foco": foco,
                    "action": ba_output.get("action"),
                    "initiative_id": ba_output.get("initiative_id"),
                    "technical_validation": researcher_output,
                    "html_updated": html_was_written,
                    "message": "Iniciativa procesada exitosamente por Multi-Agent Strategy Crew",
                }
            else:
                reason = coordinator_output.get("message") or coordinator_output.get("reason", "No aprobado por Coordinator")
                logger.warning("⚠️ Iniciativa RECHAZADA: %s", reason)
                return {
                    "status": "rejected",
                    "reason": reason,
                    "details": coordinator_output,
                }

        except Exception as exc:
            logger.error("❌ Error en Multi-Agent Strategy Crew: %s", exc)
            return {
                "status": "error",
                "message": str(exc),
            }

    
    @staticmethod
    def _parse_json_output(text: str) -> Dict[str, Any]:
        """Parse JSON output from agent (handles <think> blocks and extra text)."""
        if not text or not text.strip():
            logger.warning("_parse_json_output: texto vacío")
            return {}
        
        try:
            # Remover bloques de reasoning
            cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
            cleaned = re.sub(r'<reasoning>.*?</reasoning>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
            
            # Remover markdown code fences (con posibles espacios/│ de CrewAI verbose frame)
            # Normalizar primero: quitar el frame visual "│  " de CrewAI
            cleaned = re.sub(r'^\s*│\s?', '', cleaned, flags=re.MULTILINE)
            
            # Remover backtick fences
            cleaned = re.sub(r'```json\s*', '', cleaned)
            cleaned = re.sub(r'```\s*', '', cleaned)
            
            # Buscar el primer bloque JSON válido (busca { ... } con anidamiento)
            # Usar un enfoque más robusto que cuenta llaves
            brace_start = cleaned.find('{')
            if brace_start != -1:
                depth = 0
                for i, ch in enumerate(cleaned[brace_start:], start=brace_start):
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            json_candidate = cleaned[brace_start:i+1]
                            try:
                                return json.loads(json_candidate)
                            except json.JSONDecodeError:
                                # Intentar reparar comillas simples o trailing commas
                                repaired = re.sub(r',\s*}', '}', json_candidate)
                                repaired = re.sub(r',\s*]', ']', repaired)
                                try:
                                    return json.loads(repaired)
                                except json.JSONDecodeError:
                                    pass
                            break
            
            # Intentar parsear el texto completo limpio
            try:
                return json.loads(cleaned.strip())
            except json.JSONDecodeError:
                pass
            
            # Fallback: retornar dict vacío
            logger.warning(f"No se pudo parsear JSON de: {text[:200]}...")
            return {}
            
        except Exception as exc:
            logger.error(f"Error en _parse_json_output: {exc}")
            logger.debug(f"Texto original: {text[:300]}...")
            return {}

    # ------------------------------------------------------------------
    def kickoff(self, email_entrante: str) -> TriageDecisionOutput:
        """Run the UNIFIED triage pipeline using Multi-Agent Strategy Crew.
        
        NUEVO FLUJO (sin triage "rápido"):
        1. Todo mensaje/email pasa por Multi-Agent Strategy Crew
        2. Triage Strategist clasifica en F1-F4 o JUNK
        3. Business Analyst busca duplicados y actualiza HTML (única fuente de verdad)
        4. Researcher valida viabilidad técnica
        5. Coordinator aprueba antes de escribir
        
        No más ConfluenceMock ni stub pipeline — solo HTMLStrategyTool.

        Args:
            email_entrante: Raw email text including headers like
                            ``De: ...\nAsunto: ...\n\n<body>``.

        Returns:
            TriageDecisionOutput validated Pydantic model.
        """
        if not email_entrante or not email_entrante.strip():
            raise ValueError("email_entrante must be a non-empty string")

        logger.info("🚀 Iniciando triage con Multi-Agent Strategy Crew…")
        
        # Ejecutar Multi-Agent Crew (el ÚNICO flujo)
        try:
            strategy_result = self.kickoff_strategy_crew(email_entrante)
            
            # Convertir resultado del Strategy Crew a TriageDecisionOutput
            if strategy_result.get("status") == "approved":
                return TriageDecisionOutput(
                    classification="STRATEGIC",
                    reasoning=f"Iniciativa clasificada como {strategy_result.get('foco')} y {strategy_result.get('action')}.",
                    email_summary=EmailSummary(
                        sender=_stub_extract_metadata(email_entrante).get("sender", "unknown"),
                        subject=_stub_extract_metadata(email_entrante).get("subject", ""),
                        key_topics=[t for t in [strategy_result.get('foco'), strategy_result.get('action')] if t is not None]
                    ),
                    actions_taken=[
                        ActionRecord(
                            tool="HTMLStrategyTool",
                            status="ok",
                            details=f"{strategy_result.get('action')} en {strategy_result.get('initiative_id')} (Foco {strategy_result.get('foco')})"
                        )
                    ],
                    pending_approvals=[],
                    discarded=False
                )
            elif strategy_result.get("status") == "rejected":
                return TriageDecisionOutput(
                    classification="JUNK",
                    reasoning=strategy_result.get("reason", "No alineado con focos estratégicos"),
                    email_summary=EmailSummary(
                        sender=_stub_extract_metadata(email_entrante).get("sender", "unknown"),
                        subject=_stub_extract_metadata(email_entrante).get("subject", ""),
                        key_topics=[]
                    ),
                    actions_taken=[],
                    pending_approvals=[],
                    discarded=True,
                    discard_reason=strategy_result.get("reason")
                )
            else:
                # Error en Strategy Crew
                return TriageDecisionOutput(
                    classification="STRATEGIC",
                    reasoning=f"Error procesando: {strategy_result.get('message', 'unknown error')}",
                    email_summary=EmailSummary(
                        sender=_stub_extract_metadata(email_entrante).get("sender", "unknown"),
                        subject=_stub_extract_metadata(email_entrante).get("subject", ""),
                        key_topics=[]
                    ),
                    actions_taken=[],
                    pending_approvals=["Revisar error manualmente"],
                    discarded=False
                )
        
        except Exception as exc:
            logger.error(f"❌ Error fatal en kickoff: {exc}")
            # Fallback mínimo
            return TriageDecisionOutput(
                classification="STRATEGIC",
                reasoning=f"Error procesando mensaje: {str(exc)}",
                email_summary=EmailSummary(
                    sender="error",
                    subject="Error",
                    key_topics=[]
                ),
                actions_taken=[],
                pending_approvals=["Revisar error manualmente"],
                discarded=False
            )

    # ------------------------------------------------------------------
    def kickoff_conversation(self, user_message: str, conversation_history: list = None, user_id: str = "default") -> str:
        """Run a lightweight conversation (NO REASONING) for quick responses.
        
        Diferencia clave con kickoff():
        - kickoff() → Triage analítico profundo (task: triage_email, llm_config con reasoning)
        - kickoff_conversation() → Respuestas rápidas (task: conversation_assist, llm_config sin reasoning)
        
        Consulta memoria semántica PRIMERO antes de responder, especialmente si el usuario
        menciona "recuerda", "memoria", "conversamos", "requerimiento", etc.
        
        Args:
            user_message: Mensaje del usuario (pregunta, saludo, etc.)
            conversation_history: Lista de mensajes previos (opcional)
            user_id: ID del usuario para acceder a su memoria episódica
            
        Returns:
            Respuesta de texto directo (no TriageDecisionOutput)
        """
        try:
            # ── PASO 1: CONSULTAR MEMORIA EPISÓDICA ────────────────────────────
            # Detectar si el usuario pide recordar algo o menciona conversaciones previas
            from src.conversation_memory import create_user_memory
            
            semantic_context = ""
            user_message_lower = user_message.lower()
            
            # Keywords que indican búsqueda en memoria
            memory_triggers = [
                "recuerda", "recordar", "memoria", "conversamos", "hablamos",
                "dijimos", "mencionaste", "mencioné", "requerimiento", "propuesta",
                "proyecto", "tema", "asunto", "lo que", "anterior", "antes",
                "más reciente", "último", "última"
            ]
            
            needs_memory_search = any(trigger in user_message_lower for trigger in memory_triggers)
            
            if needs_memory_search:
                try:
                    memory = create_user_memory(user_id, max_topics=10)
                    
                    # Detectar tema específico mencionado (SAP, Shopify, requerimiento, etc.)
                    topic_keywords = {
                        "sap", "shopify", "3pl", "carrier", "integración", "integracion",
                        "ecommerce", "e-commerce", "bokun", "bókun", "mantenimiento",
                        "viña", "vina", "sistema", "requerimiento", "propuesta"
                    }
                    
                    detected_topic = None
                    for keyword in topic_keywords:
                        if keyword in user_message_lower:
                            detected_topic = keyword
                            break
                    
                    # Búsqueda semántica (por tema específico o más reciente)
                    context_messages = memory.get_context_for_triage(query=detected_topic, max_messages=5)
                    
                    if context_messages and len(context_messages.strip()) > 50:
                        # Formato simple como "conversaciones previas" (sin estructura especial)
                        semantic_context = f"\n\nCONVERSACIONES PREVIAS (para tu referencia interna):\n{context_messages}\n"
                        logger.info("[Conversación] Memoria semántica recuperada: %d chars", len(semantic_context))
                    else:
                        logger.info("[Conversación] No se encontró contexto relevante en memoria episódica")
                
                except Exception as mem_exc:
                    logger.warning("[Conversación] Error accediendo memoria episódica: %s", mem_exc)
            
            # ── PASO 2: CONSTRUIR PROMPT CON PERSONALIDAD NIA ──────────────────
            # Usar el LLM ya inicializado (sin reasoning para conversaciones)
            # Si no hay LLM disponible, fallback a mensaje de error
            if self.llm is None:
                logger.error("No LLM available for conversation")
                return "Lo siento, no puedo procesar tu mensaje en este momento."
            
            logger.info("Using LLM for conversation: %s", type(self.llm).__name__)
            
            # System prompt con personalidad de Nia (analista estratégica Descorcha)
            system_prompt = """Eres Nia, la asistente estratégica de Descorcha. Respondes en español.

MODO CONVERSACIONAL — guía de comportamiento:
- Si el mensaje es un saludo ("hola", "buenos días", "¿qué tal?", etc.): responde con UN saludo breve y natural, sin elaborar.
- Si es una pregunta concreta: responde directamente y de forma concisa.
- Si es una solicitud de tarea o análisis: pregunta por los detalles que necesitas.
- NUNCA asumas contexto de trabajo si el usuario no lo ha mencionado en este hilo.
- NUNCA inventes temas, proyectos o integraciones que el usuario no haya mencionado.

Reglas de respuesta:
1. Usa las "CONVERSACIONES PREVIAS" solo si son relevantes para lo que el usuario acaba de decir.
2. Responde DIRECTAMENTE al usuario. Sin listas de metadatos ni etiquetas internas.
3. Máximo 3 oraciones para saludos o preguntas simples. 2-3 párrafos para temas complejos.
4. Si no tienes información relevante → pregunta brevemente por contexto."""

            # Construir prompt con contexto conversacional (corto plazo)
            short_term_context = ""
            if conversation_history and len(conversation_history) > 0:
                recent = conversation_history[-3:]  # Últimos 3 intercambios
                short_term_context = "\n".join([
                    f"{msg.get('role', 'user').capitalize()}: {msg.get('content', '')[:150]}"
                    for msg in recent
                ])

            # ── PASO 2.3: DETECTAR SALUDO / CHIT-CHAT ──────────────────────────
            # Si el mensaje es puramente conversacional, NO activar strategy_crew
            _greeting_patterns = [
                r"^hola\b", r"^buenos?\s+d[ií]as?\b", r"^buenas?\s+tardes?\b",
                r"^buenas?\s+noches?\b", r"^hey\b", r"^qu[eé]\s+tal\b",
                r"^c[oó]mo\s+est[aá]s?\b", r"^todo\s+bien\b", r"^hola\s+n[ií]a\b",
                r"^hi\b", r"^hello\b",
            ]
            import re as _re_greet
            _msg_stripped = user_message_lower.strip().rstrip("!?.¿¡")
            is_greeting = any(
                _re_greet.search(pat, _msg_stripped)
                for pat in _greeting_patterns
            ) or len(user_message.split()) <= 3 and not any(
                c in user_message_lower for c in ["?", "qué", "cuál", "cómo", "cuando", "dónde"]
            )

            # ── PASO 2.5: DETECTAR INICIATIVA ESTRATÉGICA ──────────────────────
            # Si el mensaje contiene keywords de iniciativas, activar multi-agent crew
            initiative_keywords = [
                # Acciones estratégicas
                "implementar", "integrar", "desarrollar", "ajustar",
                "optimizar", "automatizar", "migrar", "rediseñar",
                # Sistemas/tecnologías (solo si acompañan una acción)
                "shopify", "sap", "bokun", "bókun", "3pl", "carrier",
                # Decisiones estratégicas
                "propuesta", "iniciativa", "proyecto", "requerimiento",
                "estrategia", "roadmap", "prioridad"
            ]

            # Comandos explícitos de registro
            registration_triggers = [
                "registrar", "registra", "documenta", "documentar",
                "agrega", "agregar", "añade", "añadir",
                "crea la iniciativa", "crear iniciativa"
            ]

            explicit_registration = any(trigger in user_message_lower for trigger in registration_triggers)

            # Detectar si hay iniciativa — los saludos nunca son iniciativas
            is_strategic_initiative = (
                not is_greeting
                and (
                    any(kw in user_message_lower for kw in initiative_keywords)
                    or explicit_registration
                )
            )
            
            # Si se pide registro pero no hay iniciativa en el mensaje actual,
            # buscar en el historial conversacional reciente
            if explicit_registration and not any(kw in user_message_lower for kw in initiative_keywords):
                if conversation_history and len(conversation_history) > 0:
                    # Buscar iniciativa en los últimos 5 mensajes
                    recent_messages = conversation_history[-5:]
                    for msg in recent_messages:
                        content = msg.get('content', '').lower()
                        if any(kw in content for kw in initiative_keywords):
                            # Encontramos la iniciativa en el contexto reciente
                            # Combinar mensaje actual + contexto para el Strategy Crew
                            user_message = f"{msg.get('content', '')}\n\nAcción solicitada: {user_message}"
                            is_strategic_initiative = True
                            logger.info("🔍 Iniciativa detectada en contexto conversacional previo")
                            break
            
            # Activar multi-agent crew si detecta iniciativa
            strategy_crew_result = None
            if is_strategic_initiative:
                logger.info("🚀 [Conversación] Detectada iniciativa estratégica, activando Multi-Agent Crew…")
                logger.info(f"📝 Input para Strategy Crew: {user_message[:200]}...")
                try:
                    strategy_crew_result = self.kickoff_strategy_crew(user_message)
                    
                    if strategy_crew_result.get("status") == "approved":
                        # Agregar resultado al contexto para que Nia lo mencione
                        initiative_summary = f"""
[INICIATIVA PROCESADA POR STRATEGY CREW]
- Foco: {strategy_crew_result.get('foco')}
- Acción: {strategy_crew_result.get('action')}
- ID: {strategy_crew_result.get('initiative_id')}
- Validación técnica: {"✓ Viable" if strategy_crew_result.get('technical_validation', {}).get('viable') else "⚠ Requiere revisión"}
"""
                        semantic_context += initiative_summary
                        logger.info("✅ Iniciativa procesada exitosamente")
                    else:
                        logger.warning("⚠️ Iniciativa rechazada o con error: %s", strategy_crew_result)
                
                except Exception as strategy_exc:
                    logger.error("❌ Error ejecutando Strategy Crew: %s", strategy_exc)
            
            # ── PASO 3: GENERAR RESPUESTA CONVERSACIONAL ───────────────────────
            
            # Combinar: system + memoria episódica + corto plazo + mensaje actual
            if semantic_context or short_term_context:
                prompt = f"""{system_prompt}

{semantic_context}

CONVERSACIÓN RECIENTE (corto plazo):
{short_term_context}

Usuario: {user_message}

Nia (responde directamente al usuario, usando el contexto disponible pero SIN repetirlo):"""
            else:
                prompt = f"""{system_prompt}

Usuario: {user_message}

Nia (responde de forma concisa y directa):"""
            
            print(f"\n{'='*80}")
            print(f"📤 PROMPT ENVIADO:")
            print(f"{'='*80}")
            print(prompt[:500])
            print(f"{'='*80}\n")
            
            # Llamada al LLM usando la API nativa de LM Studio (/api/v1/chat)
            # Esto permite control explícito de reasoning via el campo "reasoning".
            logger.info("Calling LLM with prompt length: %d", len(prompt))

            try:
                from src.lmstudio_litellm import build_lmstudio_llm

                # Construir cliente nativo con reasoning="off" para conversaciones
                # LM Studio soporta: "off"|"low"|"medium"|"high"|"on"
                # Para un saludo o pregunta simple → "off" (sin pensar, respuesta directa)
                # Para análisis o preguntas complejas → "low" (pensamiento mínimo)
                reasoning_level = "off" if is_greeting else "low"

                lm = build_lmstudio_llm(
                    enable_reasoning=False,  # base: sin reasoning
                    max_tokens=300 if is_greeting else 500,
                )
                # Sobrescribir reasoning según tipo de mensaje
                lm.reasoning = reasoning_level

                result = lm(prompt)
                
                logger.info("LLM returned result length: %d", len(result) if result else 0)
                
            except Exception as llm_exc:
                logger.error("Error calling LLM: %s", llm_exc)
                return "Lo siento, ocurrió un error al generar la respuesta."
            
            print(f"\n{'='*80}")
            print(f"📥 RESPUESTA DEL MODELO:")
            print(f"{'='*80}")
            print(f"TIPO: {type(result)}")
            print(f"CONTENIDO: '{result[:500]}'")
            print(f"{'='*80}\n")
            
            if not result or not result.strip():
                return "Lo siento, no pude generar una respuesta. ¿Puedes intentar de nuevo?"
            
            # ── PASO 3: LIMPIAR RESPUESTA ──────────────────────────────────────
            # Remover cualquier repetición del contexto interno que el modelo pueda haber generado
            cleaned_result = result.strip()
            
            # Remover bloques explícitos de metadata/contexto
            import re
            
            # Remover encabezado "**MEMORIA EPISÓDICA:**" y todo hasta el separador "---"
            cleaned_result = re.sub(
                r'\*\*MEMORIA EPISÓDICA:\*\*.*?(?:---+\s*\n|(?=\n\n[A-Z]))',
                '',
                cleaned_result,
                flags=re.DOTALL | re.IGNORECASE
            )
            
            # Remover viñetas con "* **Tema:**", "* **Contexto:**", etc.
            cleaned_result = re.sub(
                r'^\s*\*\s+\*\*(?:Tema|Contexto|Acción tomada):\*\*[^\n]*\n',
                '',
                cleaned_result,
                flags=re.MULTILINE | re.IGNORECASE
            )
            
            # Remover bloques "CONVERSACIONES PREVIAS (para tu referencia...)" si el modelo los repitió
            cleaned_result = re.sub(
                r'CONVERSACIONES PREVIAS \(para tu referencia[^\)]*\):.*?(?=\n\n[A-Z]|\Z)',
                '',
                cleaned_result,
                flags=re.DOTALL | re.IGNORECASE
            )
            
            # Remover separadores "---" excesivos
            cleaned_result = re.sub(r'\n\s*---+\s*\n', '\n\n', cleaned_result)
            
            # Limpiar espacios múltiples
            cleaned_result = re.sub(r'\n{3,}', '\n\n', cleaned_result).strip()
            
            # Safety check: si limpiamos demasiado, usar original
            if len(cleaned_result) < len(result) * 0.3:
                logger.warning("[Conversación] Limpieza removió demasiado (%d → %d chars), usando respuesta original", len(result), len(cleaned_result))
                return result.strip()
            
            if len(cleaned_result) < len(result):
                logger.info("[Conversación] Limpieza aplicada: %d → %d chars", len(result), len(cleaned_result))
            
            return cleaned_result
            
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

            # Extraer el objeto JSON principal (el más grande, no el último).
            # El modelo puede emitir varios objetos: el JSON raíz completo y objetos
            # anidados como {"tool": "...", "status": "..."} dentro de actions_taken.
            # Tomar el ÚLTIMO causaba el error: si el modelo terminaba con un objeto
            # anidado, ese se usaba como raíz y faltaban classification/reasoning.
            # Estrategia: intentar parsear todos los candidatos y quedarse con el
            # primero que tenga los campos requeridos (classification + reasoning).
            matches = list(_re.finditer(r"\{.*?\}", text, _re.DOTALL))
            if matches:
                if len(matches) > 1:
                    logger.debug("Multiple JSON objects found (%d), picking best candidate", len(matches))
                    # Buscar el primero que tenga classification y reasoning
                    best = None
                    for m in matches:
                        try:
                            candidate = json.loads(m.group(0))
                            if "classification" in candidate and "reasoning" in candidate:
                                best = m.group(0)
                                break
                        except json.JSONDecodeError:
                            continue
                    # Si ninguno tiene ambos campos, usar el más largo (probablemente el raíz)
                    if best is None:
                        best = max(matches, key=lambda m: len(m.group(0))).group(0)
                    text = best
                else:
                    text = matches[0].group(0)

            # Intentar parsear; si falla porque el JSON está truncado, reparar
            try:
                data = json.loads(text.strip())
            except json.JSONDecodeError:
                # JSON truncado: el LLM se quedó sin tokens en medio de la respuesta.
                # Intentar extraer campos parciales con regex antes de caer al fallback.
                logger.warning("JSON truncated, attempting partial field extraction")
                classification_match = _re.search(
                    r'"classification"\s*:\s*"(STRATEGIC|JUNK)"', text, _re.IGNORECASE
                )
                reasoning_match = _re.search(
                    r'"reasoning"\s*:\s*"([^"]{0,300})', text
                )
                data = {
                    "classification": classification_match.group(1).upper() if classification_match else "STRATEGIC",
                    "reasoning": reasoning_match.group(1) if reasoning_match else "Respuesta incompleta (JSON truncado por límite de tokens)",
                }

            return TriageDecisionOutput(**data)

        except Exception as exc:
            logger.warning("Could not parse crewai output as TriageDecisionOutput: %s", exc)
            meta = _stub_extract_metadata(email_text)
            return TriageDecisionOutput(
                classification="STRATEGIC",
                reasoning="No se pudo procesar la respuesta del modelo correctamente.",
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
