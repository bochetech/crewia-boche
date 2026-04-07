"""
LM Studio LiteLLM — Drop-in replacement for litellm with native LM Studio API support.

Esta implementación usa el endpoint nativo /api/v1/chat de LM Studio en lugar del
OpenAI-compatible /v1/chat/completions, lo que permite:

1. Control explícito de reasoning: "off"|"low"|"medium"|"high"|"on"
2. Separación inequívoca de contenido: output array con type="reasoning"|"message"
3. Sin regex frágiles: el tipo viene en la estructura JSON de respuesta

API Reference: https://lmstudio.ai/docs/api/rest-api
Endpoint: POST /api/v1/chat
Response: {"output": [{"type": "reasoning"|"message", "content": "..."}]}

Interfaz compatible con crewai.LLM para drop-in replacement.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Union

import requests

logger = logging.getLogger(__name__)


class LMStudioLiteLLM:
    """Cliente directo a la API nativa de LM Studio con control de reasoning.
    
    Compatible con crewai.LLM — puede usarse como reemplazo directo en Agent(llm=...).
    
    Args:
        model: Nombre del modelo (opcional, LM Studio usa el activo si es "auto")
        base_url: URL base del servidor LM Studio (default: http://localhost:1234)
        api_key: Ignorado (solo para compatibilidad con litellm)
        temperature: Temperatura de sampling (0.0-2.0)
        max_tokens: Máximo tokens de salida (mapeado a max_output_tokens)
        reasoning: Nivel de reasoning: "off"|"low"|"medium"|"high"|"on" (default: "off")
        extra_body: Parámetros adicionales (repeat_penalty, top_p, top_k, min_p, etc.)
        verbose: Log detallado de requests/responses
        **kwargs: Parámetros adicionales ignorados (para compatibilidad)
    
    Ejemplo:
        >>> llm = LMStudioLiteLLM(
        ...     model="auto",
        ...     base_url="http://localhost:1234",
        ...     temperature=0.7,
        ...     max_tokens=500,
        ...     reasoning="off",
        ...     extra_body={"repeat_penalty": 1.05, "top_p": 0.95}
        ... )
        >>> response = llm("¿Qué es la transformación digital?")
        >>> print(response)
    """
    
    def __init__(
        self,
        model: str = "auto",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,  # Ignorado
        temperature: float = 0.7,
        max_tokens: int = 500,
        reasoning: str = "off",
        extra_body: Optional[Dict[str, Any]] = None,
        verbose: bool = False,
        **kwargs  # Absorbe parámetros extra de crewai
    ):
        self.model = model
        # Normalizar base_url: remover /v1 si está presente (es para OpenAI-compatible)
        base_url_raw = (base_url or os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234")).rstrip("/")
        # Si termina en /v1, quitarlo (la API nativa usa /api/v1/chat, no /v1/api/v1/chat)
        if base_url_raw.endswith("/v1"):
            base_url_raw = base_url_raw[:-3]
        self.base_url = base_url_raw
        
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning = reasoning
        self.extra_body = extra_body or {}
        self.verbose = verbose or os.getenv("LMSTUDIO_VERBOSE") == "1"
        
        # Atributos de compatibilidad con litellm/crewai
        self.api_key = api_key or "lm-studio"  # Dummy key
        
        # Endpoint nativo (NO OpenAI-compatible)
        self._endpoint = f"{self.base_url}/api/v1/chat"
        
        if self.verbose:
            logger.info(
                "🔧 LMStudioLiteLLM initialized: endpoint=%s, reasoning=%s, max_tokens=%d",
                self._endpoint, self.reasoning, self.max_tokens
            )
    
    def _format_messages(self, messages: Union[str, List[Dict[str, str]]]) -> str:
        """Convierte mensajes a formato de input de LM Studio.
        
        LM Studio espera un string de texto plano, no array de mensajes.
        Si recibe un array (formato OpenAI), concatenamos el contenido.
        
        Args:
            messages: String directo o lista de {"role": "...", "content": "..."}
        
        Returns:
            String de input para la API
        """
        if isinstance(messages, str):
            return messages
        
        if isinstance(messages, list):
            # Concatenar mensajes con formato role: content
            parts = []
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if content:
                    parts.append(f"{role}: {content}")
            return "\n\n".join(parts)
        
        return str(messages)
    
    def _call_api(self, input_text: str) -> Dict[str, Any]:
        """Llama a POST /api/v1/chat y retorna la respuesta JSON completa.
        
        Args:
            input_text: Texto de entrada (prompt)
        
        Returns:
            Respuesta JSON: {"output": [{"type": "...", "content": "..."}], ...}
        
        Raises:
            requests.HTTPError: Si la API retorna error HTTP
            json.JSONDecodeError: Si la respuesta no es JSON válido
        """
        # LM Studio requiere el nombre del modelo explícitamente en /api/v1/chat
        # Si model="auto", usar el que esté cargado (leer de /v1/models primero)
        model_name = self.model
        if model_name == "auto":
            try:
                models_resp = requests.get(f"{self.base_url}/v1/models", timeout=5)
                models_data = models_resp.json()
                if models_data.get("data") and len(models_data["data"]) > 0:
                    model_name = models_data["data"][0]["id"]
                    if self.verbose:
                        logger.info("   auto-detected model: %s", model_name)
            except Exception as exc:
                logger.warning("Could not auto-detect model: %s. Using 'auto' as fallback.", exc)
                model_name = "auto"  # LM Studio podría aceptar "auto" como nombre
        
        payload = {
            "model": model_name,  # ← REQUERIDO por LM Studio
            "input": input_text,
            "reasoning": self.reasoning,
            "max_output_tokens": self.max_tokens,
            "temperature": self.temperature,
            **self.extra_body,
        }
        
        if self.verbose:
            logger.info("📤 LM Studio API request:")
            logger.info("   URL: %s", self._endpoint)
            logger.info("   model: %s", model_name)
            logger.info("   reasoning: %s", self.reasoning)
            logger.info("   max_output_tokens: %d", self.max_tokens)
            logger.info("   input (first 200 chars): %s", input_text[:200])
        
        try:
            response = requests.post(
                self._endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=120,  # 2 minutos timeout
            )
            response.raise_for_status()
            data = response.json()
            
            if self.verbose:
                logger.info("📥 LM Studio API response:")
                logger.info("   Status: %d", response.status_code)
                logger.info("   Output items: %d", len(data.get("output", [])))
                for item in data.get("output", []):
                    logger.info("     - type: %s, length: %d", item.get("type"), len(item.get("content", "")))
            
            return data
        
        except requests.exceptions.Timeout:
            logger.error("❌ LM Studio API timeout (120s)")
            raise
        except requests.exceptions.ConnectionError as exc:
            logger.error("❌ LM Studio connection error: %s", exc)
            logger.error("   Verifica que LM Studio esté corriendo en %s", self.base_url)
            raise
        except requests.exceptions.HTTPError as exc:
            logger.error("❌ LM Studio API error: %s", exc)
            logger.error("   Response: %s", exc.response.text if exc.response else "N/A")
            raise
    
    def _extract_messages(self, response_data: Dict[str, Any], include_reasoning: bool = False) -> str:
        """Extrae solo los mensajes (type="message") del output array.
        
        Esta es la clave: LM Studio separa explícitamente el razonamiento del mensaje
        usando el atributo "type". No necesitamos regex ni heurísticas.
        
        Args:
            response_data: JSON de respuesta de LM Studio
            include_reasoning: Si True, también incluye type="reasoning" (para debug)
        
        Returns:
            Contenido concatenado de los mensajes (sin razonamiento)
        """
        output = response_data.get("output", [])
        
        if not isinstance(output, list):
            logger.warning("⚠️ LM Studio output no es array: %s", type(output))
            return str(output)
        
        messages = []
        reasoning_count = 0
        
        for item in output:
            if not isinstance(item, dict):
                continue
            
            item_type = item.get("type", "")
            content = item.get("content", "")
            
            if item_type == "message":
                messages.append(content)
            elif item_type == "reasoning":
                reasoning_count += 1
                if include_reasoning:
                    messages.append(f"[REASONING: {content[:100]}...]")
        
        if self.verbose and reasoning_count > 0:
            logger.info("🧠 Reasoning blocks detected: %d (excluded from output)", reasoning_count)
        
        result = "\n\n".join(messages).strip()
        
        if not result and reasoning_count > 0:
            logger.warning("⚠️ Only reasoning found, no message content. Check reasoning level.")
        
        return result
    
    def __call__(self, messages: Union[str, List[Dict[str, str]]], **kwargs) -> str:
        """Invoca el LLM con mensajes y retorna la respuesta limpia.
        
        Compatibilidad con crewai: Agent.llm(prompt) llama a este método.
        
        Args:
            messages: Prompt (string o lista de mensajes)
            **kwargs: Parámetros adicionales (sobrescriben configuración)
        
        Returns:
            Respuesta del modelo (solo type="message", sin razonamiento)
        """
        # Permitir sobrescribir reasoning por llamada
        reasoning = kwargs.pop("reasoning", self.reasoning)
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)
        temperature = kwargs.pop("temperature", self.temperature)
        
        # Temporal override de configuración
        original_reasoning = self.reasoning
        original_max_tokens = self.max_tokens
        original_temp = self.temperature
        
        self.reasoning = reasoning
        self.max_tokens = max_tokens
        self.temperature = temperature
        
        try:
            input_text = self._format_messages(messages)
            response_data = self._call_api(input_text)
            result = self._extract_messages(response_data)
            return result
        finally:
            # Restaurar configuración original
            self.reasoning = original_reasoning
            self.max_tokens = original_max_tokens
            self.temperature = original_temp
    
    def invoke(self, prompt: str, **kwargs) -> str:
        """Compatibilidad con LangChain: llm.invoke(prompt)."""
        return self(prompt, **kwargs)
    
    def call(self, messages: Union[str, List[Dict[str, str]]], **kwargs) -> str:
        """Llamada directa compatible con crewai Agent.
        
        crewai llama a llm.call(prompt) en lugar de llm(prompt).
        
        Args:
            messages: Prompt (string o lista de mensajes)
            **kwargs: Parámetros adicionales (sobrescriben configuración)
        
        Returns:
            Respuesta del modelo (solo type="message", sin razonamiento)
        """
        return self(messages, **kwargs)
    
    async def acall(self, messages: Union[str, List[Dict[str, str]]], **kwargs) -> str:
        """Versión async de call (crewai puede usar async).
        
        Por ahora es sync porque requests no es async, pero crewai lo acepta.
        """
        return self.call(messages, **kwargs)
    
    # ── Métodos de compatibilidad con crewai/litellm ───────────────────────
    
    @property
    def model_name(self) -> str:
        """Compatibilidad con crewai: llm.model_name."""
        return self.model
    
    def set_reasoning(self, level: str) -> None:
        """Cambia el nivel de reasoning dinámicamente.
        
        Útil para alternar entre triage (con reasoning) y conversación (sin reasoning).
        
        Args:
            level: "off"|"low"|"medium"|"high"|"on"
        """
        valid_levels = ["off", "low", "medium", "high", "on"]
        if level not in valid_levels:
            raise ValueError(f"Invalid reasoning level: {level}. Must be one of {valid_levels}")
        
        old_level = self.reasoning
        self.reasoning = level
        
        if self.verbose:
            logger.info("🔄 Reasoning level changed: %s → %s", old_level, level)
    
    def __repr__(self) -> str:
        return (
            f"LMStudioLiteLLM(model={self.model!r}, "
            f"reasoning={self.reasoning!r}, "
            f"max_tokens={self.max_tokens})"
        )


def build_lmstudio_llm(
    enable_reasoning: bool = True,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
) -> LMStudioLiteLLM:
    """Factory function para crear LMStudioLiteLLM con configuración de triage_crew.
    
    Reemplaza _build_local_llm() en triage_crew.py.
    
    Args:
        enable_reasoning: Si True, usa reasoning="on" (triage profundo).
                         Si False, usa reasoning="off" (conversación rápida).
        base_url: URL del servidor LM Studio (default: LMSTUDIO_BASE_URL env var)
        model: Nombre del modelo (default: LMSTUDIO_MODEL env var o "auto")
        **kwargs: Parámetros adicionales (temperature, max_tokens, etc.)
    
    Returns:
        LMStudioLiteLLM configurado
    
    Example:
        >>> # Para triage analítico (con reasoning)
        >>> llm_triage = build_lmstudio_llm(
        ...     enable_reasoning=True,
        ...     max_tokens=1500,
        ...     extra_body={"repeat_penalty": 1.05}
        ... )
        
        >>> # Para conversación rápida (sin reasoning)
        >>> llm_chat = build_lmstudio_llm(
        ...     enable_reasoning=False,
        ...     max_tokens=300,
        ...     extra_body={"repeat_penalty": 1.1, "top_p": 0.9}
        ... )
    """
    base_url = base_url or os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234")
    model = model or os.getenv("LMSTUDIO_MODEL", "auto")
    
    if enable_reasoning:
        # ── TRIAGE ──────────────────────────────────────────────────────
        # Reasoning habilitado: el modelo piensa antes de clasificar.
        # El output array separará automáticamente type="reasoning" de type="message".
        config = {
            "model": model,
            "base_url": base_url,
            "temperature": 0.7,
            "max_tokens": 1500,
            "reasoning": "on",  # ← Control nativo
            "extra_body": {
                "repeat_penalty": 1.05,
                "top_p": 0.95,
            },
            "verbose": True,
        }
        logger.info("🔧 LLM config (TRIAGE): reasoning=on, max_tokens=1500")
    else:
        # ── CONVERSACIÓN ─────────────────────────────────────────────────
        # Sin reasoning: respuesta directa y rápida.
        config = {
            "model": model,
            "base_url": base_url,
            "temperature": 0.7,
            "max_tokens": 300,
            "reasoning": "off",  # ← Control nativo
            "extra_body": {
                "repeat_penalty": 1.1,
                "top_p": 0.9,
                "min_p": 0.05,
            },
            "verbose": True,
        }
        logger.info("🔧 LLM config (CONVERSACIÓN): reasoning=off, max_tokens=300")
    
    # Sobrescribir con kwargs del usuario
    config.update(kwargs)
    
    return LMStudioLiteLLM(**config)


__all__ = [
    "LMStudioLiteLLM",
    "build_lmstudio_llm",
]
