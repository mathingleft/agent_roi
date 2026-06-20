"""Event tracer: collects and persists all swarm events."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from .schemas import EventType, TraceEvent


class SwarmTracer:
    """Thread-safe event collector that streams to events.jsonl."""

    def __init__(self, run_id: str, output_dir: Path):
        self.run_id = run_id
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._events: list[TraceEvent] = []
        self._lock = asyncio.Lock()
        self._start_time = time.monotonic()
        self._jsonl_path = output_dir / f"{run_id}_events.jsonl"

    def _elapsed(self) -> float:
        return round(time.monotonic() - self._start_time, 3)

    async def record(
        self,
        agent: str,
        event: EventType,
        artifact: str = "",
        tokens_est: int = 0,
        result_summary: str = "",
        parent_task: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TraceEvent:
        evt = TraceEvent(
            timestamp=self._elapsed(),
            run_id=self.run_id,
            agent=agent,
            event=event,
            artifact=artifact,
            tokens_est=tokens_est,
            result_summary=result_summary,
            parent_task=parent_task,
            metadata=metadata or {},
        )
        async with self._lock:
            self._events.append(evt)
            with self._jsonl_path.open("a") as f:
                f.write(json.dumps(evt.to_dict()) + "\n")
        return evt

    async def get_events(self) -> list[TraceEvent]:
        async with self._lock:
            return list(self._events)

    async def get_events_for_agent(self, agent: str) -> list[TraceEvent]:
        async with self._lock:
            return [e for e in self._events if e.agent == agent]

    async def get_events_of_type(self, event_type: EventType) -> list[TraceEvent]:
        async with self._lock:
            return [e for e in self._events if e.event == event_type]

    async def get_file_reads(self) -> list[TraceEvent]:
        return await self.get_events_of_type(EventType.FILE_READ)

    async def get_evidence_events(self) -> list[TraceEvent]:
        return await self.get_events_of_type(EventType.EVIDENCE_PUBLISH)

    def elapsed(self) -> float:
        return self._elapsed()

    @classmethod
    def load_from_jsonl(cls, path: Path, run_id: str) -> "SwarmTracer":
        """Reconstruct a tracer from a saved jsonl file (for analysis)."""
        tracer = cls.__new__(cls)
        tracer.run_id = run_id
        tracer._events = []
        tracer._lock = asyncio.Lock()
        tracer._start_time = 0.0
        tracer._jsonl_path = path
        tracer.output_dir = path.parent

        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                evt = TraceEvent(
                    timestamp=d["timestamp"],
                    run_id=d["run_id"],
                    agent=d["agent"],
                    event=EventType(d["event"]),
                    artifact=d.get("artifact", ""),
                    tokens_est=d.get("tokens_est", 0),
                    result_summary=d.get("result_summary", ""),
                    parent_task=d.get("parent_task", ""),
                    metadata=d.get("metadata", {}),
                )
                tracer._events.append(evt)
        return tracer
