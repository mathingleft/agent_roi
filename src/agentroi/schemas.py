"""Core data schemas for AgentROI."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal


class AgentRole(str, Enum):
    LOG_INVESTIGATOR = "log_investigator"
    CODE_INVESTIGATOR = "code_investigator"
    REPRODUCER = "reproducer"
    PATCH_AGENT = "patch_agent"
    VERIFIER = "verifier"


class EventType(str, Enum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    FILE_READ = "file_read"
    FILE_EDIT = "file_edit"
    BASH_COMMAND = "bash_command"
    TEST_RUN = "test_run"
    GREP_SEARCH = "grep_search"
    EVIDENCE_PUBLISH = "evidence_publish"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE = "memory_write"
    PATCH_ATTEMPT = "patch_attempt"
    TOOL_CALL = "tool_call"
    BLOCKED_ACTION = "blocked_action"


class WasteType(str, Enum):
    DUPLICATE_FILE_READ = "duplicate_file_read"
    PREMATURE_FULL_SUITE = "premature_full_suite"
    LATE_EVIDENCE_PROPAGATION = "late_evidence_propagation"
    BAD_ROUTING = "bad_routing"
    IRRELEVANT_SEARCH = "irrelevant_search"
    TEST_EDIT_CHEAT = "test_edit_cheat"
    AGENT_IDLE = "agent_idle"
    STALE_MEMORY = "stale_memory"


@dataclass
class TraceEvent:
    timestamp: float
    run_id: str
    agent: str
    event: EventType
    artifact: str = ""
    tokens_est: int = 0
    result_summary: str = ""
    parent_task: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "agent": self.agent,
            "event": self.event.value if isinstance(self.event, EventType) else self.event,
            "artifact": self.artifact,
            "tokens_est": self.tokens_est,
            "result_summary": self.result_summary,
            "parent_task": self.parent_task,
            "metadata": self.metadata,
        }


@dataclass
class WasteEvent:
    waste_type: WasteType
    description: str
    agents_involved: list[str]
    timestamp_start: float
    timestamp_end: float
    estimated_cost: float
    artifacts: list[str] = field(default_factory=list)
    severity: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "waste_type": self.waste_type.value,
            "description": self.description,
            "agents_involved": self.agents_involved,
            "timestamp_start": self.timestamp_start,
            "timestamp_end": self.timestamp_end,
            "estimated_cost": self.estimated_cost,
            "artifacts": self.artifacts,
            "severity": self.severity,
        }


@dataclass
class RunMetrics:
    run_id: str
    wall_time_sec: float
    tokens_total: int
    file_reads: int
    duplicate_file_reads: int
    test_runs: int
    file_edits: int
    bash_commands: int
    evidence_published: int
    blocked_actions: int
    target_test_passed: bool
    full_suite_passed: bool
    patch_diff_lines: int
    test_files_edited: bool

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class JudgeVerdict:
    investigation_quality: float
    evidence_utilization: float
    patch_quality: float
    coordination_score: float
    overall_roi: float
    key_insight: str
    top_waste: str
    confidence: str
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class ROIReport:
    run_id: str
    task_signature: dict[str, Any]
    metrics: RunMetrics
    waste_events: list[WasteEvent]
    judge_verdict: JudgeVerdict
    composite_roi_score: float
    retrospective: str
    prompt_patches: dict[str, list[str]]
    routing_update: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_signature": self.task_signature,
            "metrics": self.metrics.to_dict(),
            "waste_events": [w.to_dict() for w in self.waste_events],
            "judge_verdict": self.judge_verdict.to_dict(),
            "composite_roi_score": self.composite_roi_score,
            "retrospective": self.retrospective,
            "prompt_patches": self.prompt_patches,
            "routing_update": self.routing_update,
        }


@dataclass
class TaskMemory:
    task_signature: dict[str, Any]
    learned_routing: dict[str, Any]
    known_high_roi_context: list[str]
    known_waste_patterns: list[str]
    prompt_patches: dict[str, list[str]]
    blocked_actions: dict[str, list[str]]
    eval_history: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_signature": self.task_signature,
            "learned_routing": self.learned_routing,
            "known_high_roi_context": self.known_high_roi_context,
            "known_waste_patterns": self.known_waste_patterns,
            "prompt_patches": self.prompt_patches,
            "blocked_actions": self.blocked_actions,
            "eval_history": self.eval_history,
        }


# ---------------------------------------------------------------------------
# Memory abstraction layer types
# ---------------------------------------------------------------------------

class MemoryEntryType(str, Enum):
    ROUTING_RULE = "routing_rule"
    PROMPT_PATCH = "prompt_patch"
    WASTE_PATTERN = "waste_pattern"
    EPISODIC_RECORD = "episodic_record"
    HIGH_ROI_CONTEXT = "high_roi_context"


class RetrievalStrategy(str, Enum):
    EXACT = "exact"          # key/signature match only
    COSINE = "cosine"        # vector similarity (requires embeddings)
    LLM_GUIDED = "llm"      # LLM reasons about what to retrieve


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MemoryEntry:
    """
    Atomic, typed unit of memory. Backend-agnostic.
    Every piece of learned knowledge is a MemoryEntry regardless of
    how/where it is stored.
    """
    entry_type: MemoryEntryType
    content: str | dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    trajectory_id: str = "default"
    task_signature_key: str = ""
    agent_role: str = ""
    helpful_count: int = 0
    harmful_count: int = 0
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def vote_helpful(self) -> None:
        self.helpful_count += 1
        self.updated_at = _now_iso()

    def vote_harmful(self) -> None:
        self.harmful_count += 1
        self.updated_at = _now_iso()

    @property
    def net_score(self) -> int:
        return self.helpful_count - self.harmful_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entry_type": self.entry_type.value,
            "content": self.content,
            "trajectory_id": self.trajectory_id,
            "task_signature_key": self.task_signature_key,
            "agent_role": self.agent_role,
            "helpful_count": self.helpful_count,
            "harmful_count": self.harmful_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MemoryEntry":
        return cls(
            id=d["id"],
            entry_type=MemoryEntryType(d["entry_type"]),
            content=d["content"],
            trajectory_id=d.get("trajectory_id", "default"),
            task_signature_key=d.get("task_signature_key", ""),
            agent_role=d.get("agent_role", ""),
            helpful_count=d.get("helpful_count", 0),
            harmful_count=d.get("harmful_count", 0),
            created_at=d.get("created_at", _now_iso()),
            updated_at=d.get("updated_at", _now_iso()),
            metadata=d.get("metadata", {}),
        )


@dataclass
class RetrievalQuery:
    """
    Decoupled query object — backends and consumers share this interface.
    Callers declare what they want; the backend decides how to find it.
    """
    task_signature: dict[str, Any]
    trajectory_id: str = "default"
    entry_types: list[MemoryEntryType] = field(default_factory=list)
    agent_role: str = ""
    strategy: RetrievalStrategy = RetrievalStrategy.EXACT
    top_k: int = 20
    min_net_score: int = -999
    free_text: str = ""

    def signature_key(self) -> str:
        parts = [
            self.task_signature.get("source", ""),
            self.task_signature.get("error_type", ""),
            self.task_signature.get("service", ""),
        ]
        return "|".join(p.lower() for p in parts if p)


@dataclass
class ConsumerContext:
    """Context passed to every MemoryConsumer alongside retrieved entries."""
    task_description: str
    task_signature: dict[str, Any]
    trajectory_id: str
    agent_role: str = ""
    run_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConsumerOutput:
    """
    Typed output from a MemoryConsumer.
    Consumers that don't produce a particular field leave it as default.
    """
    prompt_additions: str = ""
    agent_order: list[str] = field(default_factory=list)
    blocked_tools: set[str] = field(default_factory=set)
    evidence_context: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
