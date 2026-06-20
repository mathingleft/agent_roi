"""
Memory facade: wires a MemoryBackend + MemoryConsumer together.

The loop and swarm only interact with MemoryManager — they never
import a specific backend or consumer directly. Swap either by
passing different implementations to MemoryManager.__init__().
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .memory_backends import ACEPlaybookBackend, JSONMemoryBackend
from .memory_consumers import CompositeConsumer, default_consumer
from .memory_protocol import MemoryBackend, MemoryConsumer
from .schemas import (
    ConsumerContext,
    ConsumerOutput,
    MemoryEntry,
    MemoryEntryType,
    RetrievalQuery,
    RetrievalStrategy,
)


class MemoryManager:
    """
    High-level memory interface used by the loop and swarm.

    Accepts any MemoryBackend and any MemoryConsumer — completely
    agnostic to implementation details of either.

    Usage:
        manager = MemoryManager.from_path(path)            # default (ACE backend)
        manager = MemoryManager.from_path(path, backend="json")  # JSON backend
        manager = MemoryManager(backend=MyBackend(), consumer=MyConsumer())
    """

    def __init__(
        self,
        backend: MemoryBackend,
        consumer: MemoryConsumer | None = None,
    ):
        self.backend = backend
        self.consumer = consumer or default_consumer()

    @classmethod
    def from_path(
        cls,
        path: Path,
        backend: str = "ace",
        consumer: MemoryConsumer | None = None,
    ) -> "MemoryManager":
        """Convenience constructor — picks backend by name."""
        if backend == "json":
            b: MemoryBackend = JSONMemoryBackend(path)
        else:
            b = ACEPlaybookBackend(path)
        return cls(backend=b, consumer=consumer)

    # ------------------------------------------------------------------
    # Core API used by the loop
    # ------------------------------------------------------------------

    def retrieve_and_consume(
        self,
        task_signature: dict[str, Any],
        trajectory_id: str,
        agent_role: str = "",
        strategy: RetrievalStrategy = RetrievalStrategy.EXACT,
        entry_types: list[MemoryEntryType] | None = None,
        free_text: str = "",
        task_description: str = "",
        run_id: str = "",
    ) -> ConsumerOutput:
        """
        Single call that retrieves relevant entries and applies the consumer.
        This is the primary read path — loop + swarm both call this.
        """
        query = RetrievalQuery(
            task_signature=task_signature,
            trajectory_id=trajectory_id,
            entry_types=entry_types or [],
            agent_role=agent_role,
            strategy=strategy,
            free_text=free_text,
        )
        entries = self.backend.retrieve(query)

        ctx = ConsumerContext(
            task_description=task_description,
            task_signature=task_signature,
            trajectory_id=trajectory_id,
            agent_role=agent_role,
            run_id=run_id,
        )
        return self.consumer.consume(entries, ctx)

    def store_roi_results(
        self,
        task_signature: dict[str, Any],
        trajectory_id: str,
        roi_report_dict: dict[str, Any],
    ) -> None:
        """
        After a run completes, persist all learnings as typed MemoryEntries.
        This is the primary write path.
        """
        sig_key = _sig_key(task_signature)

        prompt_patches: dict[str, list[str]] = roi_report_dict.get("prompt_patches", {})
        for role, patches in prompt_patches.items():
            for patch_text in patches:
                self.backend.store(MemoryEntry(
                    entry_type=MemoryEntryType.PROMPT_PATCH,
                    content=patch_text,
                    trajectory_id=trajectory_id,
                    task_signature_key=sig_key,
                    agent_role=role,
                ))

        routing = roi_report_dict.get("routing_update", {})
        if routing:
            self.backend.store(MemoryEntry(
                entry_type=MemoryEntryType.ROUTING_RULE,
                content=routing,
                trajectory_id=trajectory_id,
                task_signature_key=sig_key,
            ))

        waste_events = roi_report_dict.get("waste_events", [])
        for w in waste_events:
            self.backend.store(MemoryEntry(
                entry_type=MemoryEntryType.WASTE_PATTERN,
                content=w.get("description", ""),
                trajectory_id=trajectory_id,
                task_signature_key=sig_key,
                metadata={"waste_type": w.get("waste_type", ""), "severity": w.get("severity", "")},
            ))

        verdict = roi_report_dict.get("judge_verdict", {})
        insight = verdict.get("key_insight", "")
        if insight:
            self.backend.store(MemoryEntry(
                entry_type=MemoryEntryType.HIGH_ROI_CONTEXT,
                content=f"Judge insight: {insight}",
                trajectory_id=trajectory_id,
                task_signature_key=sig_key,
            ))

        metrics = roi_report_dict.get("metrics", {})
        self.backend.store(MemoryEntry(
            entry_type=MemoryEntryType.EPISODIC_RECORD,
            content={
                "run_id": roi_report_dict.get("run_id", ""),
                "roi_score": roi_report_dict.get("composite_roi_score", 0.0),
                "wall_time_sec": metrics.get("wall_time_sec", 0),
                "tokens": metrics.get("tokens_total", 0),
                "target_pass": metrics.get("target_test_passed", False),
                "retrospective_snippet": roi_report_dict.get("retrospective", "")[:300],
            },
            trajectory_id=trajectory_id,
            task_signature_key=sig_key,
            helpful_count=1 if metrics.get("target_test_passed") else 0,
        ))

    def create_trajectory(self, trajectory_id: str, description: str = "") -> None:
        if hasattr(self.backend, "create_trajectory"):
            self.backend.create_trajectory(trajectory_id, description)

    def list_trajectories(self) -> list[str]:
        return self.backend.list_trajectories()

    def snapshot(self, trajectory_id: str) -> list[dict[str, Any]]:
        return self.backend.snapshot(trajectory_id)

    def prune(self, trajectory_id: str | None = None, min_net_score: int = -2) -> int:
        return self.backend.prune(trajectory_id=trajectory_id, min_net_score=min_net_score)


def _sig_key(signature: dict[str, Any]) -> str:
    parts = [
        signature.get("source", ""),
        signature.get("error_type", ""),
        signature.get("service", ""),
    ]
    return "|".join(p.lower() for p in parts if p)


# ---------------------------------------------------------------------------
# Convenience factory used by tests / CLI when no custom setup is needed
# ---------------------------------------------------------------------------

def make_memory_manager(
    path: Path,
    backend: str = "ace",
    consumer: MemoryConsumer | None = None,
) -> MemoryManager:
    return MemoryManager.from_path(path, backend=backend, consumer=consumer)
