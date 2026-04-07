"""
CrewIA Panel — FastAPI backend
===============================
Endpoints
  GET  /api/config              → devuelve agents.yaml + tasks.yaml como JSON
  PUT  /api/config              → guarda cambios en agents.yaml + tasks.yaml
  GET  /api/config/lmstudio     → estado de conexión LM Studio
  POST /api/crew/run            → lanza kickoff_strategy_crew en background
  GET  /api/executions          → historial de ejecuciones
  GET  /api/executions/{id}     → detalle de una ejecución
  GET  /api/initiatives         → lista todas las iniciativas del HTML SSOT
  WS   /ws/execution/{id}       → streaming de eventos en tiempo real
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import requests
import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

# Ensure project root is in sys.path so `src.*` imports work
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from api.models import (
    AgentConfig,
    AgentStepEvent,
    ConfigUpdateResponse,
    CrewConfig,
    ExecutionRecord,
    ExecutionStatus,
    RunCrewRequest,
    RunCrewResponse,
    TaskConfig,
)
from api.store import store

logger = logging.getLogger("crewia.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")

# ---------------------------------------------------------------------------
# Config paths
# ---------------------------------------------------------------------------
AGENTS_CFG = _ROOT / "config" / "agents.yaml"
TASKS_CFG  = _ROOT / "config" / "tasks.yaml"


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 CrewIA Panel API iniciando…")
    yield
    logger.info("🛑 CrewIA Panel API deteniendo…")


app = FastAPI(
    title="CrewIA Panel",
    version="1.0.0",
    description="Panel web de configuración y monitoreo para crewia-boche",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_yaml(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)


def _agents_yaml_to_list(raw: dict) -> List[AgentConfig]:
    agents_raw = raw.get("agents", {})
    result = []
    for agent_id, cfg in agents_raw.items():
        result.append(AgentConfig(
            id=agent_id,
            role=cfg.get("role", ""),
            goal=cfg.get("goal", ""),
            backstory=cfg.get("backstory", ""),
            max_iter=cfg.get("max_iter", 3),
            tools=cfg.get("tools", []),
        ))
    return result


def _tasks_yaml_to_list(raw: dict) -> List[TaskConfig]:
    tasks_raw = raw.get("tasks", [])
    result = []
    for t in tasks_raw:
        result.append(TaskConfig(
            id=t.get("id", ""),
            description=t.get("description", ""),
            expected_result=t.get("expected_result", ""),
            agent_id=t.get("agent", ""),
        ))
    return result


# ---------------------------------------------------------------------------
# Routes — Config
# ---------------------------------------------------------------------------

@app.get("/api/config", response_model=CrewConfig, tags=["Config"])
def get_config():
    """Devuelve la configuración actual de agentes y tareas."""
    agents_raw = _load_yaml(AGENTS_CFG)
    tasks_raw  = _load_yaml(TASKS_CFG)
    return CrewConfig(
        agents=_agents_yaml_to_list(agents_raw),
        tasks=_tasks_yaml_to_list(tasks_raw),
    )


@app.put("/api/config", response_model=ConfigUpdateResponse, tags=["Config"])
def update_config(body: CrewConfig):
    """Guarda la configuración de agentes y tareas en disco (YAML)."""
    # Rebuild agents.yaml
    agents_dict: Dict[str, Any] = {}
    for a in body.agents:
        agents_dict[a.id] = {
            "role":      a.role,
            "goal":      a.goal,
            "backstory": a.backstory,
            "max_iter":  a.max_iter,
            "tools":     a.tools,
        }
    _save_yaml(AGENTS_CFG, {"agents": agents_dict})

    # Rebuild tasks.yaml
    tasks_list = []
    for t in body.tasks:
        tasks_list.append({
            "id":              t.id,
            "description":     t.description,
            "expected_result": t.expected_result,
            "agent":           t.agent_id,
        })
    _save_yaml(TASKS_CFG, {"tasks": tasks_list})

    return ConfigUpdateResponse(message="Configuración guardada correctamente")


@app.get("/api/config/lmstudio", tags=["Config"])
def lmstudio_status():
    """Verifica conectividad con LM Studio."""
    base_url = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
    try:
        resp = requests.get(f"{base_url}/models", timeout=2)
        if resp.status_code == 200:
            models = [m.get("id") for m in resp.json().get("data", [])]
            return {"status": "connected", "models": models, "base_url": base_url}
    except Exception as exc:
        return {"status": "disconnected", "error": str(exc), "base_url": base_url}
    return {"status": "disconnected", "base_url": base_url}


# ---------------------------------------------------------------------------
# Routes — Initiatives (HTML SSOT)
# ---------------------------------------------------------------------------

@app.get("/api/initiatives", tags=["Initiatives"])
def list_initiatives():
    """Lista todas las iniciativas estratégicas del HTML SSOT."""
    try:
        from src.strategy_tools.html_strategy_tool import HTMLStrategyTool
        tool = HTMLStrategyTool()
        raw = tool._run(action="list_all")
        return json.loads(raw)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Routes — Executions
# ---------------------------------------------------------------------------

@app.get("/api/executions", tags=["Executions"])
def list_executions(limit: int = 50):
    """Historial de las últimas ejecuciones."""
    return [r.model_dump() for r in store.list_all(limit=limit)]


@app.get("/api/executions/{execution_id}", tags=["Executions"])
def get_execution(execution_id: str):
    """Detalle de una ejecución específica, incluyendo todos los pasos."""
    rec = store.get(execution_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Ejecución no encontrada")
    return rec.model_dump()


# ---------------------------------------------------------------------------
# Background crew runner
# ---------------------------------------------------------------------------

async def _run_crew_background(execution_id: str, input_text: str) -> None:
    """Executes kickoff_strategy_crew in a thread and publishes events via WebSocket."""

    loop = asyncio.get_event_loop()

    async def emit(agent: str, event: str, payload: dict) -> None:
        step = AgentStepEvent(
            execution_id=execution_id,
            agent=agent,
            event=event,
            payload=payload,
        )
        await store.publish(execution_id, step)

    store.update_status(execution_id, ExecutionStatus.RUNNING)
    await emit("system", "started", {"input_text": input_text})

    try:
        # Import here so the API can start even if crewai is not installed
        from src.triage_crew import TriageCrew

        # Patch: intercept CrewAI events by monkey-patching TriageCrew methods
        # to emit WebSocket events at each agent step.
        crew = TriageCrew()

        # Wrap kickoff_strategy_crew to emit granular events
        original_kickoff = crew.kickoff_strategy_crew

        def _patched_kickoff(initiative_input: str) -> dict:
            """Synchronous wrapper that emits events during execution."""

            # Emit strategist start
            loop.call_soon_threadsafe(
                asyncio.ensure_future,
                emit("strategist", "started", {"input": initiative_input[:300]})
            )

            # We hook into the internal flow by wrapping _ensure_html_written
            original_ensure = crew._ensure_html_written

            def _wrapped_ensure(ba_output, initiative_input, foco, researcher_output):
                loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    emit("ba", "tool_call", {
                        "tool": "HTMLStrategyTool",
                        "action": "ensure_html_written",
                        "foco": foco,
                    })
                )
                result = original_ensure(ba_output, initiative_input, foco, researcher_output)
                loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    emit("ba", "tool_result", {
                        "html_updated": result.get("html_updated", False),
                        "initiative_id": result.get("initiative_id"),
                        "action": result.get("action"),
                    })
                )
                return result

            crew._ensure_html_written = _wrapped_ensure
            result = original_kickoff(initiative_input)

            # Emit per-agent completed events from result
            foco = result.get("foco")
            status = result.get("status")
            loop.call_soon_threadsafe(
                asyncio.ensure_future,
                emit("strategist", "completed", {"foco": foco, "status": status})
            )
            loop.call_soon_threadsafe(
                asyncio.ensure_future,
                emit("coordinator", "completed", {
                    "status": status,
                    "initiative_id": result.get("initiative_id"),
                    "action": result.get("action"),
                })
            )
            return result

        # Run the crew in a thread (it's synchronous / blocking)
        result = await loop.run_in_executor(None, _patched_kickoff, input_text)

        final_status = {
            "approved": ExecutionStatus.APPROVED,
            "rejected": ExecutionStatus.REJECTED,
        }.get(result.get("status", ""), ExecutionStatus.ERROR)

        store.update_status(
            execution_id,
            final_status,
            result=result,
            foco=result.get("foco"),
            initiative_id=result.get("initiative_id"),
            action=result.get("action"),
        )
        await emit("system", "finished", {"status": result.get("status"), "result": result})

    except Exception as exc:
        logger.exception("Error en ejecución %s", execution_id)
        store.update_status(execution_id, ExecutionStatus.ERROR, error=str(exc))
        await emit("system", "error", {"error": str(exc)})

    finally:
        await store.publish_done(execution_id)


@app.post("/api/crew/run", response_model=RunCrewResponse, tags=["Executions"])
async def run_crew(body: RunCrewRequest, background_tasks: BackgroundTasks):
    """Lanza una nueva ejecución del Multi-Agent Strategy Crew."""
    rec = ExecutionRecord(input_text=body.input_text)
    store.create(rec)
    background_tasks.add_task(_run_crew_background, rec.id, body.input_text)
    return RunCrewResponse(execution_id=rec.id)


# ---------------------------------------------------------------------------
# WebSocket — real-time execution events
# ---------------------------------------------------------------------------

@app.websocket("/ws/execution/{execution_id}")
async def ws_execution(websocket: WebSocket, execution_id: str):
    """Stream agent step events for a running execution."""
    await websocket.accept()

    # If execution already finished, send all recorded steps + done
    rec = store.get(execution_id)
    if rec is None:
        await websocket.send_text(json.dumps({"error": "Ejecución no encontrada"}))
        await websocket.close()
        return

    if rec.status not in (ExecutionStatus.PENDING, ExecutionStatus.RUNNING):
        # Replay stored steps
        for step in rec.steps:
            await websocket.send_text(step.model_dump_json())
        await websocket.send_text("__DONE__")
        await websocket.close()
        return

    # Subscribe to live events
    q = store.subscribe(execution_id)
    try:
        while True:
            msg = await asyncio.wait_for(q.get(), timeout=360)
            await websocket.send_text(msg)
            if msg == "__DONE__":
                break
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    finally:
        store.unsubscribe(execution_id, q)
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
