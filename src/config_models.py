"""Pydantic models for validating agent and task configuration YAML files.

These models help validate `config/agents.yaml` and `config/tasks.yaml` at
startup so the Crew fails fast on malformed config.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, validator


class AgentConfig(BaseModel):
    role: str
    backstory: str
    default_tier: Optional[str] = Field(default="standard")


class AgentsFile(BaseModel):
    agents: dict

    @validator("agents")
    def ensure_agents_have_roles(cls, v: dict):
        if not isinstance(v, dict):
            raise ValueError("agents must be a mapping of agent_id -> AgentConfig")
        # Minimal validation loop
        for key, val in v.items():
            if not isinstance(val, dict):
                raise ValueError(f"agent {key} must be a mapping")
            if "role" not in val:
                raise ValueError(f"agent {key} missing required field 'role'")
        return v


class TaskItem(BaseModel):
    id: str
    title: str
    owner: str
    description: str
    expected_result: Optional[str]


class TasksFile(BaseModel):
    tasks: List[TaskItem]


def validate_agents_yaml(data: dict) -> AgentsFile:
    return AgentsFile(agents=data.get("agents", {}))


def validate_tasks_yaml(data: dict) -> TasksFile:
    return TasksFile(tasks=data.get("tasks", []))
