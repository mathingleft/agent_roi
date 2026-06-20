"""
Abstract protocols for memory backends and consumers.

MemoryBackend  — how entries are stored and retrieved (swappable storage)
MemoryConsumer — how retrieved entries are used (swappable application logic)

Neither protocol knows about the other. The loop wires them together.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .schemas import ConsumerContext, ConsumerOutput, MemoryEntry, RetrievalQuery


@runtime_checkable
class MemoryBackend(Protocol):
    """
    Storage-agnostic interface. Implement this to plug in any backend:
    JSON file, SQLite, vector DB, graph DB, remote API, etc.

    Trajectory isolation is the backend's responsibility — the
    RetrievalQuery carries trajectory_id and the backend must respect it.
    """

    def store(self, entry: MemoryEntry) -> str:
        """Persist a new entry. Returns its id."""
        ...

    def retrieve(self, query: RetrievalQuery) -> list[MemoryEntry]:
        """
        Return entries matching the query, ordered by relevance.
        Strategy (exact / cosine / llm) is a hint — backends may
        fall back to exact if they don't support the requested strategy.
        """
        ...

    def update(self, entry_id: str, delta: dict[str, Any]) -> MemoryEntry | None:
        """
        Apply a delta dict to an existing entry in place.
        Returns the updated entry, or None if not found.
        """
        ...

    def vote(self, entry_id: str, helpful: bool) -> None:
        """Increment helpful_count or harmful_count on an entry."""
        ...

    def prune(self, trajectory_id: str | None = None, min_net_score: int = -2) -> int:
        """
        Remove entries with net_score below threshold.
        Returns number of entries pruned.
        """
        ...

    def list_trajectories(self) -> list[str]:
        """Return all known trajectory IDs."""
        ...

    def snapshot(self, trajectory_id: str) -> list[dict[str, Any]]:
        """Export all entries for a trajectory as raw dicts (for inspection/debug)."""
        ...


@runtime_checkable
class MemoryConsumer(Protocol):
    """
    Usage-agnostic interface. Implement this to define how retrieved
    memory entries affect agent behaviour.

    A consumer receives retrieved entries + context and produces a
    ConsumerOutput. Consumers can be composed — run several over the
    same entry list and merge their outputs.
    """

    def consume(
        self,
        entries: list[MemoryEntry],
        context: ConsumerContext,
    ) -> ConsumerOutput:
        """
        Transform a list of memory entries into usable output.
        Must not mutate entries.
        """
        ...

    @property
    def name(self) -> str:
        """Human-readable identifier for logging."""
        ...


def compose_outputs(*outputs: ConsumerOutput) -> ConsumerOutput:
    """
    Merge multiple ConsumerOutputs into one.
    prompt_additions are concatenated, sets are unioned,
    lists are concatenated (last non-empty wins for agent_order).
    """
    prompt_parts: list[str] = []
    agent_order: list[str] = []
    blocked_tools: set[str] = set()
    evidence_parts: list[str] = []
    raw: dict[str, Any] = {}

    for out in outputs:
        if out.prompt_additions:
            prompt_parts.append(out.prompt_additions)
        if out.agent_order:
            agent_order = out.agent_order
        blocked_tools |= out.blocked_tools
        if out.evidence_context:
            evidence_parts.append(out.evidence_context)
        raw.update(out.raw)

    return ConsumerOutput(
        prompt_additions="\n".join(prompt_parts),
        agent_order=agent_order,
        blocked_tools=blocked_tools,
        evidence_context="\n".join(evidence_parts),
        raw=raw,
    )
