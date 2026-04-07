"""In-memory execution store (swap for SQLite/Postgres in production)."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime
from typing import Dict, List, Optional, Set

from api.models import AgentStepEvent, ExecutionRecord, ExecutionStatus


class ExecutionStore:
    """Thread-safe, async-friendly store for execution records."""

    _MAX = 200  # keep last N executions in memory

    def __init__(self) -> None:
        self._records: OrderedDict[str, ExecutionRecord] = OrderedDict()
        # per-execution queues for WebSocket fans
        self._queues: Dict[str, Set[asyncio.Queue]] = {}

    # ------------------------------------------------------------------ CRUD

    def create(self, record: ExecutionRecord) -> ExecutionRecord:
        self._records[record.id] = record
        if len(self._records) > self._MAX:
            self._records.popitem(last=False)
        return record

    def get(self, exec_id: str) -> Optional[ExecutionRecord]:
        return self._records.get(exec_id)

    def list_all(self, limit: int = 50) -> List[ExecutionRecord]:
        items = list(self._records.values())
        return items[-limit:][::-1]  # newest first

    def update_status(
        self,
        exec_id: str,
        status: ExecutionStatus,
        result: Optional[dict] = None,
        error: Optional[str] = None,
        foco: Optional[str] = None,
        initiative_id: Optional[str] = None,
        action: Optional[str] = None,
    ) -> None:
        rec = self._records.get(exec_id)
        if rec is None:
            return
        rec.status = status
        if result is not None:
            rec.result = result
        if error is not None:
            rec.error = error
        if foco is not None:
            rec.foco = foco
        if initiative_id is not None:
            rec.initiative_id = initiative_id
        if action is not None:
            rec.action = action
        if status in (ExecutionStatus.APPROVED, ExecutionStatus.REJECTED, ExecutionStatus.ERROR):
            rec.finished_at = datetime.utcnow()

    def append_step(self, exec_id: str, step: AgentStepEvent) -> None:
        rec = self._records.get(exec_id)
        if rec:
            rec.steps.append(step)

    # ------------------------------------------------------------------ PubSub

    def subscribe(self, exec_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._queues.setdefault(exec_id, set()).add(q)
        return q

    def unsubscribe(self, exec_id: str, q: asyncio.Queue) -> None:
        qs = self._queues.get(exec_id, set())
        qs.discard(q)

    async def publish(self, exec_id: str, event: AgentStepEvent) -> None:
        """Broadcast an event to all WebSocket subscribers for this execution."""
        self.append_step(exec_id, event)
        for q in list(self._queues.get(exec_id, [])):
            try:
                q.put_nowait(event.model_dump_json())
            except asyncio.QueueFull:
                pass  # slow consumer — drop event (non-blocking)

    async def publish_done(self, exec_id: str) -> None:
        """Send a terminal sentinel so WebSocket handlers know to close."""
        for q in list(self._queues.get(exec_id, [])):
            try:
                q.put_nowait("__DONE__")
            except asyncio.QueueFull:
                pass
        self._queues.pop(exec_id, None)


# Singleton instance shared across the app
store = ExecutionStore()
