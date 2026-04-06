import os

import pytest

from src import crew
from src.crew import ArchitectOutput


def test_load_env_and_get_key(tmp_path, monkeypatch):
    # Ensure .env loading doesn't raise when file doesn't exist
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    crew.load_env(dotenv_path=str(tmp_path / ".env"))
    assert crew.get_gemini_api_key() is None


def test_create_gemini_client_returns_stub(monkeypatch):
    # Ensure no provider libs are present by forcing ImportError paths (best-effort)
    monkeypatch.setenv("GEMINI_API_KEY", "")
    client = crew.create_gemini_client(tier="standard", api_key=None)
    # stub should implement generate
    assert hasattr(client, "generate")
    out = client.generate("hello world")
    assert isinstance(out, dict)
    assert "output" in out
    assert out["model"] == crew.MODEL_TIERS["standard"]


def test_architect_output_model():
    ao = ArchitectOutput(
        decision="Choice A",
        rationale="Because...",
        estimated_tokens=150,
        next_steps=["step1", "step2"],
    )
    j = ao.model_dump_json()
    assert "Choice A" in j
