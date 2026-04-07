"""
CrewIA Panel — FastAPI backend
===============================
Endpoints
  GET  /api/config                    → agentes + tareas + herramientas + flujos
  PUT  /api/config                    → guarda agentes + tareas + flujos
  GET  /api/config/lmstudio           → estado de conexión LM Studio

  GET  /api/agents                    → lista agentes
  POST /api/agents                    → crear agente
  PUT  /api/agents/{id}               → editar agente
  DELETE /api/agents/{id}             → eliminar agente

  GET  /api/tasks                     → lista tareas (con agente asociado)
  POST /api/tasks                     → crear tarea
  PUT  /api/tasks/{id}                → editar tarea
  DELETE /api/tasks/{id}              → eliminar tarea

  GET  /api/tools                     → lista herramientas registradas (read-only)

  GET  /api/flows                     → lista flujos
  POST /api/flows                     → crear flujo
  PUT  /api/flows/{id}                → editar flujo
  DELETE /api/flows/{id}              → eliminar flujo

  POST /api/crew/run                  → lanza ejecución en background
  GET  /api/executions                → historial
  GET  /api/executions/{id}           → detalle
  GET  /api/initiatives               → HTML SSOT
  WS   /ws/execution/{id}             → streaming en tiempo real
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid as _uuid_mod
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    EmailChannelConfig,
    EmailPipelineStep,
    ExecutionRecord,
    ExecutionStatus,
    Flow,
    FlowStep,
    NiaConfig,
    RunCrewRequest,
    RunCrewResponse,
    TaskConfig,
    TelegramChannelConfig,
    ToolConfig,
)
from api.store import store

logger = logging.getLogger("crewia.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")

# ---------------------------------------------------------------------------
# Config paths
# ---------------------------------------------------------------------------
AGENTS_CFG = _ROOT / "config" / "agents.yaml"
TASKS_CFG  = _ROOT / "config" / "tasks.yaml"
FLOWS_CFG  = _ROOT / "config" / "flows.yaml"
NIA_CFG    = _ROOT / "config" / "nia.yaml"


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
            llm_model=cfg.get("llm_model", "gemini-2.5-flash"),
            tools=cfg.get("tools", []),
        ))
    return result


def _tasks_yaml_to_list(raw: dict) -> List[TaskConfig]:
    tasks_raw = raw.get("tasks", [])
    result = []
    for t in tasks_raw:
        result.append(TaskConfig(
            id=t.get("id", ""),
            title=t.get("title", ""),
            description=t.get("description", ""),
            expected_result=t.get("expected_result", ""),
            agent_id=t.get("owner", t.get("agent", "")),
        ))
    return result


def _flows_yaml_to_list(raw: dict) -> List[Flow]:
    flows_raw = raw.get("flows", [])
    result = []
    for f in flows_raw:
        steps = [
            FlowStep(
                agent_id=s.get("agent_id", ""),
                task_id=s.get("task_id", ""),
                label=s.get("label", ""),
                parallel_group=s.get("parallel_group"),
            )
            for s in f.get("steps", [])
        ]
        result.append(Flow(
            id=f.get("id", str(_uuid_mod.uuid4())),
            name=f.get("name", ""),
            description=f.get("description", ""),
            goal=f.get("goal", ""),
            steps=steps,
            output_type=f.get("output_type"),
        ))
    return result


def _get_registered_tools() -> List[ToolConfig]:
    """Return the list of tools that are registered in the codebase."""
    tools = [
        ToolConfig(
            id="html_strategy_database",
            name="HTML Strategy Database",
            description="Lee, crea, actualiza y busca iniciativas en el HTML SSOT (estrategia_descorcha.html). Usa ChromaDB para búsqueda semántica de duplicados.",
            source="src.strategy_tools.html_strategy_tool.HTMLStrategyTool",
            parameters=["action", "initiative_id", "foco", "initiative_data", "query", "threshold"],
        ),
        ToolConfig(
            id="serper_search",
            name="SerperDev Web Search",
            description="Busca información técnica en la web (APIs, documentación, benchmarks). Requiere SERPER_API_KEY.",
            source="crewai_tools.SerperDevTool",
            parameters=["search_query"],
        ),
        ToolConfig(
            id="email_drafting",
            name="Email Drafting Tool",
            description="Redacta borradores de correos electrónicos de seguimiento estratégico.",
            source="src.tools.EmailDraftingTool",
            parameters=["recipient_name", "recipient_email", "subject", "context", "action_requested", "urgency"],
        ),
        ToolConfig(
            id="confluence_upsert",
            name="Confluence Upsert Tool",
            description="Crea o actualiza páginas en Confluence con información estratégica.",
            source="src.tools.ConfluenceUpsertTool",
            parameters=["space_key", "title", "content", "labels"],
        ),
        ToolConfig(
            id="leader_notification",
            name="Leader Notification Tool",
            description="Envía notificaciones al líder vía Telegram con el resultado del triage.",
            source="src.tools.LeaderNotificationTool",
            parameters=["channel", "classification", "summary", "actions_taken", "pending_approvals"],
        ),
        ToolConfig(
            id="email_inbox",
            name="Email Inbox Tool",
            description="Lee mensajes pendientes de la bandeja de entrada de email.",
            source="src.input_sources.EmailInboxTool",
            parameters=[],
        ),
        ToolConfig(
            id="chat_inbox",
            name="Chat Message Inbox Tool",
            description="Lee mensajes pendientes del inbox de chat (Telegram, etc.).",
            source="src.input_sources.ChatMessageInboxTool",
            parameters=[],
        ),
    ]
    return tools


# ---------------------------------------------------------------------------
# Routes — Config (combined)
# ---------------------------------------------------------------------------

@app.get("/api/config", response_model=CrewConfig, tags=["Config"])
def get_config():
    """Devuelve la configuración completa: agentes, tareas, herramientas y flujos."""
    agents_raw = _load_yaml(AGENTS_CFG)
    tasks_raw  = _load_yaml(TASKS_CFG)
    flows_raw  = _load_yaml(FLOWS_CFG)
    return CrewConfig(
        agents=_agents_yaml_to_list(agents_raw),
        tasks=_tasks_yaml_to_list(tasks_raw),
        tools=_get_registered_tools(),
        flows=_flows_yaml_to_list(flows_raw),
    )


@app.put("/api/config", response_model=ConfigUpdateResponse, tags=["Config"])
def update_config(body: CrewConfig):
    """Guarda agentes, tareas y flujos en disco (YAML)."""
    # agents.yaml
    agents_dict: Dict[str, Any] = {}
    for a in body.agents:
        agents_dict[a.id] = {
            "role":      a.role,
            "goal":      a.goal,
            "backstory": a.backstory,
            "max_iter":  a.max_iter,
            "llm_model": a.llm_model,
            "tools":     a.tools,
        }
    _save_yaml(AGENTS_CFG, {"agents": agents_dict})

    # tasks.yaml
    tasks_list = []
    for t in body.tasks:
        tasks_list.append({
            "id":              t.id,
            "title":           t.title,
            "description":     t.description,
            "expected_result": t.expected_result,
            "owner":           t.agent_id,
        })
    _save_yaml(TASKS_CFG, {"tasks": tasks_list})

    # flows.yaml
    flows_list = []
    for f in body.flows:
        flows_list.append({
            "id":          f.id,
            "name":        f.name,
            "description": f.description,
            "goal":        f.goal,
            "steps":       [
                {
                    "agent_id":       s.agent_id,
                    "task_id":        s.task_id,
                    "label":          s.label,
                    "parallel_group": s.parallel_group,
                }
                for s in f.steps
            ],
        })
    _save_yaml(FLOWS_CFG, {"flows": flows_list})

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
# Routes — Agents CRUD
# ---------------------------------------------------------------------------

@app.get("/api/agents", response_model=List[AgentConfig], tags=["Agents"])
def list_agents():
    return _agents_yaml_to_list(_load_yaml(AGENTS_CFG))


@app.post("/api/agents", response_model=AgentConfig, tags=["Agents"])
def create_agent(agent: AgentConfig):
    raw = _load_yaml(AGENTS_CFG)
    agents = raw.get("agents", {})
    if agent.id in agents:
        raise HTTPException(status_code=409, detail=f"Ya existe un agente con id '{agent.id}'")
    agents[agent.id] = {
        "role": agent.role, "goal": agent.goal, "backstory": agent.backstory,
        "max_iter": agent.max_iter, "llm_model": agent.llm_model, "tools": agent.tools,
    }
    _save_yaml(AGENTS_CFG, {"agents": agents})
    return agent


@app.put("/api/agents/{agent_id}", response_model=AgentConfig, tags=["Agents"])
def update_agent(agent_id: str, agent: AgentConfig):
    raw = _load_yaml(AGENTS_CFG)
    agents = raw.get("agents", {})
    if agent_id not in agents:
        raise HTTPException(status_code=404, detail="Agente no encontrado")
    agents[agent_id] = {
        "role": agent.role, "goal": agent.goal, "backstory": agent.backstory,
        "max_iter": agent.max_iter, "llm_model": agent.llm_model, "tools": agent.tools,
    }
    _save_yaml(AGENTS_CFG, {"agents": agents})
    return agent


@app.delete("/api/agents/{agent_id}", tags=["Agents"])
def delete_agent(agent_id: str):
    raw = _load_yaml(AGENTS_CFG)
    agents = raw.get("agents", {})
    if agent_id not in agents:
        raise HTTPException(status_code=404, detail="Agente no encontrado")
    del agents[agent_id]
    _save_yaml(AGENTS_CFG, {"agents": agents})
    return {"ok": True, "message": f"Agente '{agent_id}' eliminado"}


# ---------------------------------------------------------------------------
# Routes — Tasks CRUD
# ---------------------------------------------------------------------------

@app.get("/api/tasks", response_model=List[TaskConfig], tags=["Tasks"])
def list_tasks():
    return _tasks_yaml_to_list(_load_yaml(TASKS_CFG))


@app.post("/api/tasks", response_model=TaskConfig, tags=["Tasks"])
def create_task(task: TaskConfig):
    raw = _load_yaml(TASKS_CFG)
    tasks = raw.get("tasks", [])
    if any(t.get("id") == task.id for t in tasks):
        raise HTTPException(status_code=409, detail=f"Ya existe una tarea con id '{task.id}'")
    tasks.append({
        "id": task.id, "title": task.title, "description": task.description,
        "expected_result": task.expected_result, "owner": task.agent_id,
    })
    _save_yaml(TASKS_CFG, {"tasks": tasks})
    return task


@app.put("/api/tasks/{task_id}", response_model=TaskConfig, tags=["Tasks"])
def update_task(task_id: str, task: TaskConfig):
    raw = _load_yaml(TASKS_CFG)
    tasks = raw.get("tasks", [])
    idx = next((i for i, t in enumerate(tasks) if t.get("id") == task_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    tasks[idx] = {
        "id": task.id, "title": task.title, "description": task.description,
        "expected_result": task.expected_result, "owner": task.agent_id,
    }
    _save_yaml(TASKS_CFG, {"tasks": tasks})
    return task


@app.delete("/api/tasks/{task_id}", tags=["Tasks"])
def delete_task(task_id: str):
    raw = _load_yaml(TASKS_CFG)
    tasks = raw.get("tasks", [])
    new_tasks = [t for t in tasks if t.get("id") != task_id]
    if len(new_tasks) == len(tasks):
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    _save_yaml(TASKS_CFG, {"tasks": new_tasks})
    return {"ok": True, "message": f"Tarea '{task_id}' eliminada"}


# ---------------------------------------------------------------------------
# Routes — Tools (read-only registry)
# ---------------------------------------------------------------------------

@app.get("/api/tools", response_model=List[ToolConfig], tags=["Tools"])
def list_tools():
    """Lista todas las herramientas registradas en el código (read-only)."""
    return _get_registered_tools()


# ---------------------------------------------------------------------------
# Routes — Flows CRUD
# ---------------------------------------------------------------------------

@app.get("/api/flows", response_model=List[Flow], tags=["Flows"])
def list_flows():
    return _flows_yaml_to_list(_load_yaml(FLOWS_CFG))


@app.post("/api/flows", response_model=Flow, tags=["Flows"])
def create_flow(flow: Flow):
    raw = _load_yaml(FLOWS_CFG)
    flows = raw.get("flows", [])
    if not flow.id:
        flow = flow.model_copy(update={"id": str(_uuid_mod.uuid4())})
    if any(f.get("id") == flow.id for f in flows):
        raise HTTPException(status_code=409, detail=f"Ya existe un flujo con id '{flow.id}'")
    flows.append({
        "id": flow.id, "name": flow.name, "description": flow.description,
        "goal": flow.goal,
        "steps": [
            {"agent_id": s.agent_id, "task_id": s.task_id,
             "label": s.label, "parallel_group": s.parallel_group}
            for s in flow.steps
        ],
    })
    _save_yaml(FLOWS_CFG, {"flows": flows})
    return flow


@app.put("/api/flows/{flow_id}", response_model=Flow, tags=["Flows"])
def update_flow(flow_id: str, flow: Flow):
    raw = _load_yaml(FLOWS_CFG)
    flows = raw.get("flows", [])
    idx = next((i for i, f in enumerate(flows) if f.get("id") == flow_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Flujo no encontrado")
    flows[idx] = {
        "id": flow.id, "name": flow.name, "description": flow.description,
        "goal": flow.goal,
        "steps": [
            {"agent_id": s.agent_id, "task_id": s.task_id,
             "label": s.label, "parallel_group": s.parallel_group}
            for s in flow.steps
        ],
    }
    _save_yaml(FLOWS_CFG, {"flows": flows})
    return flow


@app.delete("/api/flows/{flow_id}", tags=["Flows"])
def delete_flow(flow_id: str):
    raw = _load_yaml(FLOWS_CFG)
    flows = raw.get("flows", [])
    new_flows = [f for f in flows if f.get("id") != flow_id]
    if len(new_flows) == len(flows):
        raise HTTPException(status_code=404, detail="Flujo no encontrado")
    _save_yaml(FLOWS_CFG, {"flows": new_flows})
    return {"ok": True, "message": f"Flujo '{flow_id}' eliminado"}


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

async def _run_crew_background(execution_id: str, input_text: str, flow_id: Optional[str] = None) -> None:
    """Executes the crew for the given flow_id in a thread and publishes events via WebSocket.

    Supported flow_id values:
      - "strategy_crew"  (default) → kickoff_strategy_crew
      - "triage_email_flow"        → run_triage  (single-agent email triage)
      - None / unknown             → falls back to strategy_crew
    """

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

        def _run_triage_flow(input_text: str) -> dict:
            """Run the single-agent email triage flow."""
            loop.call_soon_threadsafe(
                asyncio.ensure_future,
                emit("triage_analyst", "started", {"input": input_text[:300]})
            )
            result = crew.run_triage(input_text)
            classification = result.get("classification", "unknown") if isinstance(result, dict) else str(result)
            loop.call_soon_threadsafe(
                asyncio.ensure_future,
                emit("triage_analyst", "completed", {"classification": classification})
            )
            return result if isinstance(result, dict) else {"classification": classification, "status": "approved"}

        # ── Dispatch by flow_id ──────────────────────────────────────────────
        resolved_flow_id = flow_id or "strategy_crew"
        logger.info("🎯 Ejecutando flujo: %s", resolved_flow_id)
        await emit("system", "flow_selected", {"flow_id": resolved_flow_id})

        if resolved_flow_id == "triage_email_flow":
            result = await loop.run_in_executor(None, _run_triage_flow, input_text)
        else:
            # Default: strategy_crew (and any unknown flow_id falls back here)
            if resolved_flow_id != "strategy_crew":
                logger.warning("⚠️ Flujo '%s' no reconocido — usando strategy_crew como fallback", resolved_flow_id)
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
    """Lanza una nueva ejecución del flujo especificado (o strategy_crew por defecto)."""
    rec = ExecutionRecord(input_text=body.input_text, flow_id=body.flow_id)
    store.create(rec)
    background_tasks.add_task(_run_crew_background, rec.id, body.input_text, body.flow_id)
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


# ---------------------------------------------------------------------------
# Routes — Nia config
# ---------------------------------------------------------------------------

def _load_nia_config() -> NiaConfig:
    """Load NiaConfig from config/nia.yaml."""
    raw = _load_yaml(NIA_CFG)
    nia = raw.get("nia", {})
    channels = raw.get("channels", {})
    tg = channels.get("telegram", {})
    em = channels.get("email", {})

    # Parse email pipeline steps
    email_steps = []
    for s in em.get("pipeline", []):
        opts = [
            {"label": o.get("label", ""), "action": o.get("action", "discard"), "flow": o.get("flow")}
            for o in s.get("options", [])
        ]
        email_steps.append(EmailPipelineStep(
            step=s.get("step", ""),
            discard_if=s.get("discard_if", []),
            if_condition=s.get("if"),
            format=s.get("format"),
            options=opts,
        ))

    tg_commands = tg.get("commands", {})
    if isinstance(tg_commands, list):
        # Handle list format: [{command: action}] → dict
        tg_commands = {list(item.keys())[0]: list(item.values())[0] for item in tg_commands if isinstance(item, dict)}

    return NiaConfig(
        name=nia.get("name", "Nia"),
        role=nia.get("role", "Analista Estratégica de Triaje"),
        personality=nia.get("personality", ""),
        default_flow=nia.get("default_flow", "strategy_crew"),
        telegram_feedback_enabled=nia.get("telegram_feedback_enabled", True),
        memory_max_topics=int(nia.get("memory_max_topics", 10)),
        telegram=TelegramChannelConfig(
            enabled=tg.get("enabled", True),
            mode=tg.get("mode", "conversational"),
            voice_input=tg.get("voice_input", True),
            voice_output=tg.get("voice_output", True),
            notify_chat_id=tg.get("notify_chat_id"),
            commands=tg_commands,
        ),
        email=EmailChannelConfig(
            enabled=em.get("enabled", False),
            poll_interval_seconds=int(em.get("poll_interval_seconds", 60)),
            pipeline=email_steps,
        ),
    )


def _save_nia_config(cfg: NiaConfig) -> None:
    """Save NiaConfig back to config/nia.yaml."""
    email_pipeline = []
    for step in cfg.email.pipeline:
        d: Dict[str, Any] = {"step": step.step}
        if step.discard_if:
            d["discard_if"] = step.discard_if
        if step.if_condition:
            d["if"] = step.if_condition
        if step.format:
            d["format"] = step.format
        if step.options:
            d["options"] = [
                {k: v for k, v in {"label": o.label, "action": o.action, "flow": o.flow}.items() if v is not None}
                for o in step.options
            ]
        email_pipeline.append(d)

    data = {
        "nia": {
            "name": cfg.name,
            "role": cfg.role,
            "personality": cfg.personality,
            "default_flow": cfg.default_flow,
            "telegram_feedback_enabled": cfg.telegram_feedback_enabled,
            "memory_max_topics": cfg.memory_max_topics,
        },
        "channels": {
            "telegram": {
                "enabled": cfg.telegram.enabled,
                "mode": cfg.telegram.mode,
                "voice_input": cfg.telegram.voice_input,
                "voice_output": cfg.telegram.voice_output,
                "notify_chat_id": cfg.telegram.notify_chat_id,
                "commands": cfg.telegram.commands,
            },
            "email": {
                "enabled": cfg.email.enabled,
                "poll_interval_seconds": cfg.email.poll_interval_seconds,
                "pipeline": email_pipeline,
            },
        },
    }
    _save_yaml(NIA_CFG, data)


@app.get("/api/nia/config", response_model=NiaConfig, tags=["Nia"])
def get_nia_config():
    """Devuelve la configuración de Nia y sus canales."""
    return _load_nia_config()


@app.put("/api/nia/config", response_model=NiaConfig, tags=["Nia"])
def update_nia_config(body: NiaConfig):
    """Guarda la configuración de Nia en config/nia.yaml."""
    _save_nia_config(body)
    return body
