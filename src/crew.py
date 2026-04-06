"""
Core Crew module implementing a lightweight Crew pattern with Agent wiring.

This module is intentionally defensive: it provides no-op decorator fallbacks
when the real CrewAI decorators are not available, and uses lazy imports for
LLM providers. Replace stubs with real CrewAI integrations when running in
production with the proper packages installed.

Key parts:
- ModelTier management (standard/premium) -> model name mapping
- Environment/key loading with .env and Colab fallback
- Agent classes for Analyst and Architect
- Architect task returns structured Pydantic output
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel
import yaml

# Attempt to import CrewAI-style decorators; provide safe no-op fallbacks.
try:
    # These names are illustrative — adapt if your CrewAI package exposes
    # different decorator names or locations.
    from crewai.decorators import CrewBase, agent, task, crew  # type: ignore
except Exception:
    # Define no-op decorators so module can be imported safely without crewai installed.
    def _noop_decorator(x=None, **kwargs):
        def _wrap(fn):
            return fn

        if x is None:
            return _wrap
        return _wrap(x)

    CrewBase = _noop_decorator
    agent = _noop_decorator
    task = _noop_decorator
    crew = _noop_decorator


MODEL_TIERS = {
    "standard": "gemini-2.5-flash",
    "premium": "gemini-2.5-pro",
}


def load_env(dotenv_path: Optional[str] = None) -> None:
    """Load environment variables from a .env file (if present) and try Colab fallback.

    Priority:
    1. Explicit environment variables already present
    2. .env file loaded via python-dotenv
    3. google.colab.userdata fallback (best-effort)
    """
    # 1) Load from .env if available
    if dotenv_path is None:
        dotenv_path = os.path.join(os.getcwd(), ".env")
    load_dotenv(dotenv_path)

    # 2) If GEMINI_API_KEY still not set, try Colab userdata (best-effort)
    if not os.getenv("GEMINI_API_KEY"):
        try:
            import google.colab as colab  # type: ignore

            # google.colab may not expose userdata in all runtimes; this is a
            # best-effort attempt. If your Colab notebook sets a python variable
            # `userdata = { 'GEMINI_API_KEY': '...' }` in the notebook scope, you
            # can instead pass it explicitly to the script.
            userdata = getattr(colab, "userdata", None)
            if isinstance(userdata, dict):
                key = userdata.get("GEMINI_API_KEY")
                if key:
                    os.environ["GEMINI_API_KEY"] = key
        except Exception:
            # No colab available or userdata not present; that's fine.
            pass


def get_gemini_api_key() -> Optional[str]:
    """Return GEMINI_API_KEY from environment if present."""
    return os.getenv("GEMINI_API_KEY")


def create_gemini_client(tier: str = "standard", api_key: Optional[str] = None) -> Any:
    """Factory to create a provider client for Gemini based on tier.

    This function uses lazy imports so the module can be inspected without
    installing heavy dependencies. Swap the provider creation code to match
    the exact SDK/API you use (CrewAI, LangChain provider, or google genai).
    """
    model_name = MODEL_TIERS.get(tier, MODEL_TIERS["standard"])
    if api_key is None:
        api_key = get_gemini_api_key()

    # Try to instantiate using crewai first, then LangChain provider. If both
    # are missing, return a stub that simulates responses for testing.
    try:
        # Example: crewai client factory (replace with real usage)
        from crewai import LLM  # type: ignore

        return LLM(model_name=model_name, api_key=api_key)
    except Exception:
        try:
            # Example: langchain-google-genai provider (replace with real usage)
            from langchain_google_genai import Gemini  # type: ignore

            return Gemini(model=model_name, api_key=api_key)
        except Exception:
            # Fallback stub
            class _StubLLM:
                def __init__(self, model_name, api_key=None):
                    self.model_name = model_name
                    self.api_key = api_key

                def generate(self, prompt: str) -> Dict[str, Any]:
                    # Minimal deterministic stub useful for local tests
                    return {
                        "model": self.model_name,
                        "prompt": prompt,
                        "output": f"[stub response from {self.model_name}]",
                        "tokens_used": len(prompt.split()),
                    }

            return _StubLLM(model_name, api_key)


class ArchitectOutput(BaseModel):
    """Structured output model for Architect agent tasks.

    Fields:
    - decision: short textual summary of the architectural decision
    - rationale: why this choice was selected
    - estimated_tokens: rough tokens cost estimate for the suggested pipeline
    - next_steps: actionable next steps for implementation
    """

    decision: str
    rationale: str
    estimated_tokens: int
    next_steps: List[str]


@CrewBase
class Crew:
    """Main Crew orchestration class.

    Responsibilities:
    - Load agent and task configuration
    - Instantiate agents with appropriate LLM tiers
    - Provide a simple kickoff runner
    """

    def __init__(self, agents_config_path: str, tasks_config_path: str, api_key: Optional[str] = None):
        self.agents_config_path = agents_config_path
        self.tasks_config_path = tasks_config_path
        self.api_key = api_key

        # load configs
        self.agents_config = self._load_yaml(self.agents_config_path)
        self.tasks_config = self._load_yaml(self.tasks_config_path)

        # instantiate agent objects
        self.agents: Dict[str, Any] = {}
        self._instantiate_agents()

    def _load_yaml(self, path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _instantiate_agents(self) -> None:
        # Analyst agent uses standard tier
        analyst_cfg = self.agents_config.get("agents", {}).get("analyst", {})
        architect_cfg = self.agents_config.get("agents", {}).get("architect", {})

        self.agents["analyst"] = AnalystAgent(
            role=analyst_cfg.get("role", "Analyst"),
            backstory=analyst_cfg.get("backstory", ""),
            llm=create_gemini_client(tier="standard", api_key=self.api_key),
        )

        self.agents["architect"] = ArchitectAgent(
            role=architect_cfg.get("role", "Architect"),
            backstory=architect_cfg.get("backstory", ""),
            llm=create_gemini_client(tier="premium", api_key=self.api_key),
        )

    def kickoff(self) -> None:
        """Simple kickoff: run tasks sequentially and print outputs.

        In a real CrewAI deployment you'd schedule tasks, handle retries,
        streaming outputs, and provide observability. This method demonstrates
        wiring and structured output for the Architect.
        """
        tasks = self.tasks_config.get("tasks", [])

        for t in tasks:
            owner = t.get("owner")
            if owner not in self.agents:
                print(f"No agent registered for owner: {owner}")
                continue

            agent_obj = self.agents[owner]
            print(f"--- Running {t.get('id')} -> {owner} ({agent_obj.role})")
            result = agent_obj.run_task(t)

            # Architect tasks produce structured Pydantic output
            if isinstance(result, BaseModel):
                print(result.model_dump_json(indent=2))
            else:
                # Best-effort serialization
                try:
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                except Exception:
                    print(str(result))


@dataclass
class BaseAgent:
    role: str
    backstory: str
    llm: Any

    def run_task(self, task: Dict[str, Any]) -> Any:
        raise NotImplementedError()


@agent
class AnalystAgent(BaseAgent):
    """Analyst agent wired to the 'standard' LLM tier."""

    @task
    def run_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        prompt = f"Analyst task: {task.get('description')}\nBackstory: {self.backstory}\nProduce JSON summary."
        # Use llm.generate or provider-specific call. We handle both cases.
        if hasattr(self.llm, "generate"):
            out = self.llm.generate(prompt)
            # Expecting dict with tokens usage
            return {
                "task_id": task.get("id"),
                "model": getattr(self.llm, "model_name", getattr(self.llm, "model", None)),
                "raw": out,
            }
        else:
            # Try callable
            text = self.llm(prompt) if callable(self.llm) else str(self.llm)
            return {"task_id": task.get("id"), "model": None, "raw": text}


@agent
class ArchitectAgent(BaseAgent):
    """Architect agent wired to the 'premium' LLM tier. Returns structured output.

    For production replace the stub generation with the provider's sync/async
    generation API and robust parsing/validation.
    """

    @task
    def run_task(self, task: Dict[str, Any]) -> ArchitectOutput:
        prompt = (
            f"Architect task: {task.get('description')}\nBackstory: {self.backstory}\n"
            "Produce a JSON object with decision, rationale, estimated_tokens and next_steps."
        )

        # Call the llm (provider-specific).
        if hasattr(self.llm, "generate"):
            response = self.llm.generate(prompt)
            raw_text = response.get("output") if isinstance(response, dict) else str(response)
            # Heuristic token estimate
            tokens = int(response.get("tokens_used", 0)) if isinstance(response, dict) else len(raw_text.split())
        else:
            raw_text = self.llm(prompt) if callable(self.llm) else str(self.llm)
            tokens = len(raw_text.split())

        # In a production integration, ask the model to return strict JSON and
        # validate it. Here we build a small structured response using the
        # raw_text as the rationale placeholder.
        decision = "Propuesta de pipeline multi-LLM (tiered routing + prompt cache)"
        rationale = raw_text[:1000]
        estimated_tokens = max(100, tokens)
        next_steps = [
            "Implement prompt routing layer to select Standard vs Premium models",
            "Add prompt templates and a token budget per request",
            "Instrument token usage and fallbacks for latency/cost",
        ]

        return ArchitectOutput(
            decision=decision,
            rationale=rationale,
            estimated_tokens=estimated_tokens,
            next_steps=next_steps,
        )


def discover_and_run(agents_cfg: str = "config/agents.yaml", tasks_cfg: str = "config/tasks.yaml") -> None:
    """Helper to load env, instantiate Crew and run kickoff."""
    load_env()
    api_key = get_gemini_api_key()
    crew = Crew(agents_config_path=agents_cfg, tasks_config_path=tasks_cfg, api_key=api_key)
    crew.kickoff()


__all__ = [
    "Crew",
    "AnalystAgent",
    "ArchitectAgent",
    "ArchitectOutput",
    "create_gemini_client",
    "load_env",
    "discover_and_run",
]
