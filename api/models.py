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
    agent:        str            # agent id — matches FlowStep.agent_id
    event:        str            # "started" | "tool_call" | "tool_result" | "completed" | "error"
    payload:      Dict[str, Any] = Field(default_factory=dict)
    timestamp:    datetime       = Field(default_factory=datetime.utcnow)


class ExecutionRecord(BaseModel):
    """Persisted record of one crew execution."""
    id:             str          = Field(default_factory=lambda: str(uuid.uuid4()))
    input_text:     str
    flow_id:        Optional[str]   = None   # which flow was executed
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
    """Represents one agent entry in agents.yaml."""
    id:        str
    role:      str
    goal:      str       = ""
    backstory: str       = ""
    max_iter:  int       = 3
    llm_model: str       = "gemini-2.5-flash"
    tools:     List[str] = Field(default_factory=list)  # list of tool ids


class TaskConfig(BaseModel):
    """Represents one task entry in tasks.yaml."""
    id:              str
    title:           str       = ""
    description:     str
    expected_result: str
    agent_id:        str       # maps to AgentConfig.id


class ToolConfig(BaseModel):
    """Represents a registered tool (read-only — defined in Python code)."""
    id:          str
    name:        str
    description: str
    source:      str       = ""   # python class / module path
    parameters:  List[str] = Field(default_factory=list)


class FlowStep(BaseModel):
    """One step (node) in a flow: which agent runs which task."""
    agent_id:    str
    task_id:     str
    label:       str       = ""
    parallel_group: Optional[str] = None  # steps with the same group run in parallel


class Flow(BaseModel):
    """A named flow that orchestrates multiple agents/tasks toward a goal."""
    id:          str       = Field(default_factory=lambda: str(uuid.uuid4()))
    name:        str
    description: str       = ""
    goal:        str       = ""
    steps:       List[FlowStep] = Field(default_factory=list)
    output_type: Optional[str]  = None   # e.g. "initiatives" — links to a results view
    created_at:  datetime  = Field(default_factory=datetime.utcnow)


class CrewConfig(BaseModel):
    agents: List[AgentConfig]
    tasks:  List[TaskConfig]
    tools:  List[ToolConfig] = Field(default_factory=list)
    flows:  List[Flow]       = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API request / response
# ---------------------------------------------------------------------------

class RunCrewRequest(BaseModel):
    input_text: str       = Field(..., min_length=1, description="Iniciativa o mensaje a procesar")
    flow_id:    Optional[str] = Field(None, description="ID del flujo a ejecutar (opcional)")


class RunCrewResponse(BaseModel):
    execution_id: str
    message:      str = "Ejecución iniciada"


# ---------------------------------------------------------------------------
# Nia + Channel config models
# ---------------------------------------------------------------------------

class TelegramChannelConfig(BaseModel):
    """Configuration for the Telegram channel adapter."""
    enabled:          bool            = True
    mode:             str             = "conversational"   # "conversational" | "triage_only"
    voice_input:      bool            = True
    voice_output:     bool            = True
    notify_chat_id:   Optional[str]   = None
    commands:         Dict[str, str]  = Field(default_factory=dict)


class EmailPipelineOption(BaseModel):
    label:  str
    action: str             # "dispatch_flow" | "save_to_memory" | "discard"
    flow:   Optional[str]   = None


class EmailPipelineStep(BaseModel):
    step:         str                         # "classify"|"summarize"|"notify_telegram"|"ask_feedback"|"execute"
    discard_if:   List[str]                   = Field(default_factory=list)
    if_condition: Optional[str]               = None   # renamed from "if" (reserved keyword)
    format:       Optional[str]               = None
    options:      List[EmailPipelineOption]   = Field(default_factory=list)


class EmailChannelConfig(BaseModel):
    """Configuration for the Email channel adapter."""
    enabled:                bool                      = False
    poll_interval_seconds:  int                       = 60
    pipeline:               List[EmailPipelineStep]   = Field(default_factory=list)


class NiaConfig(BaseModel):
    """Top-level Nia agent configuration (mirrors config/nia.yaml → nia section)."""
    name:                        str                   = "Nia"
    role:                        str                   = "Analista Estratégica de Triaje"
    personality:                 str                   = ""
    default_flow:                str                   = "strategy_crew"
    telegram_feedback_enabled:   bool                  = True
    memory_max_topics:           int                   = 10
    telegram:                    TelegramChannelConfig = Field(default_factory=TelegramChannelConfig)
    email:                       EmailChannelConfig    = Field(default_factory=EmailChannelConfig)


class ConfigUpdateResponse(BaseModel):
    ok:      bool = True
    message: str  = "Configuración guardada"
