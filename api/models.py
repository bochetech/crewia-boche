"""Pydantic models for the API layer."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Execution models
# ---------------------------------------------------------------------------

class ExecutionStatus(str, Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    APPROVED = "approved"
    REJECTED = "rejected"
    ERROR    = "error"


class AgentStepEvent(BaseModel):
    """Single agent step emitted over WebSocket."""
    execution_id: str
    agent:        str            # "strategist" | "ba" | "researcher" | "coordinator"
    event:        str            # "started" | "tool_call" | "tool_result" | "completed" | "error"
    payload:      Dict[str, Any] = Field(default_factory=dict)
    timestamp:    datetime       = Field(default_factory=datetime.utcnow)


class ExecutionRecord(BaseModel):
    """Persisted record of one crew execution."""
    id:             str          = Field(default_factory=lambda: str(uuid.uuid4()))
    input_text:     str
    status:         ExecutionStatus = ExecutionStatus.PENDING
    foco:           Optional[str]   = None
    initiative_id:  Optional[str]   = None
    action:         Optional[str]   = None
    result:         Optional[Dict[str, Any]] = None
    steps:          List[AgentStepEvent]     = Field(default_factory=list)
    started_at:     datetime        = Field(default_factory=datetime.utcnow)
    finished_at:    Optional[datetime] = None
    error:          Optional[str]   = None


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------

class AgentConfig(BaseModel):
    id:        str
    role:      str
    goal:      str
    backstory: str
    max_iter:  int  = 3
    tools:     List[str] = Field(default_factory=list)


class TaskConfig(BaseModel):
    id:              str
    description:     str
    expected_result: str
    agent_id:        str


class CrewConfig(BaseModel):
    agents: List[AgentConfig]
    tasks:  List[TaskConfig]


# ---------------------------------------------------------------------------
# API request / response
# ---------------------------------------------------------------------------

class RunCrewRequest(BaseModel):
    input_text: str = Field(..., min_length=1, description="Iniciativa o mensaje a procesar")


class RunCrewResponse(BaseModel):
    execution_id: str
    message:      str = "Ejecución iniciada"


class ConfigUpdateResponse(BaseModel):
    ok:      bool = True
    message: str  = "Configuración guardada"
