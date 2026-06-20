"""Deterministic waste detectors that analyze a run's trace events."""
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from .schemas import AgentRole, EventType, WasteEvent, WasteType

if TYPE_CHECKING:
    from .tracer import SwarmTracer

LATE_EVIDENCE_THRESHOLD_SEC = 120.0
IDLE_THRESHOLD_SEC = 60.0


def detect_duplicate_file_reads(events: list) -> list[WasteEvent]:
    """Same file read by multiple agents before any evidence was produced."""
    waste: list[WasteEvent] = []
    reads: dict[str, list] = defaultdict(list)

    for evt in events:
        if evt.event == EventType.FILE_READ:
            reads[evt.artifact].append(evt)

    for filepath, read_events in reads.items():
        if len(read_events) < 2:
            continue
        agents = [e.agent for e in read_events]
        unique_agents = list(dict.fromkeys(agents))
        if len(unique_agents) > 1:
            waste.append(
                WasteEvent(
                    waste_type=WasteType.DUPLICATE_FILE_READ,
                    description=(
                        f"File '{filepath}' read by {len(unique_agents)} different agents "
                        f"({', '.join(unique_agents)}) — potential duplicated investigation."
                    ),
                    agents_involved=unique_agents,
                    timestamp_start=read_events[0].timestamp,
                    timestamp_end=read_events[-1].timestamp,
                    estimated_cost=sum(e.tokens_est for e in read_events[1:]),
                    artifacts=[filepath],
                    severity="high" if len(unique_agents) >= 3 else "medium",
                )
            )
    return waste


def detect_premature_full_suite(events: list) -> list[WasteEvent]:
    """Full suite ran before target test passed."""
    waste: list[WasteEvent] = []
    target_pass_time: float | None = None
    full_suite_runs: list = []

    for evt in events:
        if evt.event == EventType.TEST_RUN:
            if evt.metadata.get("test_scope") == "target" and evt.metadata.get("passed"):
                if target_pass_time is None:
                    target_pass_time = evt.timestamp
            if evt.metadata.get("test_scope") == "full_suite":
                full_suite_runs.append(evt)

    for run in full_suite_runs:
        if target_pass_time is None or run.timestamp < target_pass_time:
            waste.append(
                WasteEvent(
                    waste_type=WasteType.PREMATURE_FULL_SUITE,
                    description=(
                        f"Full test suite run at T={run.timestamp:.1f}s by '{run.agent}' "
                        f"before target test confirmed passing "
                        f"({'never' if target_pass_time is None else f'T={target_pass_time:.1f}s'})."
                    ),
                    agents_involved=[run.agent],
                    timestamp_start=run.timestamp,
                    timestamp_end=run.timestamp,
                    estimated_cost=run.tokens_est,
                    artifacts=[run.artifact],
                    severity="high",
                )
            )
    return waste


def detect_late_evidence_propagation(events: list) -> list[WasteEvent]:
    """High-signal evidence published but not used by patch agent for >N seconds."""
    waste: list[WasteEvent] = []
    evidence_events = [e for e in events if e.event == EventType.EVIDENCE_PUBLISH]
    patch_memory_reads = [
        e for e in events
        if e.agent == AgentRole.PATCH_AGENT.value and e.event == EventType.MEMORY_READ
    ]
    patch_start_events = [
        e for e in events
        if e.agent == AgentRole.PATCH_AGENT.value and e.event == EventType.AGENT_START
    ]
    patch_start_time = patch_start_events[0].timestamp if patch_start_events else None

    for evidence in evidence_events:
        if evidence.agent == AgentRole.PATCH_AGENT.value:
            continue
        used = any(
            r.timestamp >= evidence.timestamp and evidence.artifact in r.artifact
            for r in patch_memory_reads
        )
        if not used and patch_start_time is not None:
            delay = patch_start_time - evidence.timestamp
            if delay > LATE_EVIDENCE_THRESHOLD_SEC:
                waste.append(
                    WasteEvent(
                        waste_type=WasteType.LATE_EVIDENCE_PROPAGATION,
                        description=(
                            f"'{evidence.agent}' published evidence '{evidence.artifact}' "
                            f"at T={evidence.timestamp:.1f}s, but patch agent started "
                            f"T={patch_start_time:.1f}s ({delay:.0f}s later) without reading it."
                        ),
                        agents_involved=[evidence.agent, AgentRole.PATCH_AGENT.value],
                        timestamp_start=evidence.timestamp,
                        timestamp_end=patch_start_time,
                        estimated_cost=delay * 10,
                        artifacts=[evidence.artifact],
                        severity="high",
                    )
                )
    return waste


def detect_bad_routing(events: list) -> list[WasteEvent]:
    """Patch agent started before reproducer confirmed failure."""
    waste: list[WasteEvent] = []
    repro_confirmed_time: float | None = None
    patch_start_time: float | None = None

    for evt in events:
        if (
            evt.agent == AgentRole.REPRODUCER.value
            and evt.event == EventType.EVIDENCE_PUBLISH
            and "repro" in evt.artifact.lower()
        ):
            repro_confirmed_time = evt.timestamp

        if evt.agent == AgentRole.PATCH_AGENT.value and evt.event == EventType.AGENT_START:
            patch_start_time = evt.timestamp

    if patch_start_time is not None and (
        repro_confirmed_time is None or patch_start_time < repro_confirmed_time
    ):
        waste.append(
            WasteEvent(
                waste_type=WasteType.BAD_ROUTING,
                description=(
                    f"Patch agent started at T={patch_start_time:.1f}s before "
                    f"reproducer confirmed failure "
                    f"({'never confirmed' if repro_confirmed_time is None else f'T={repro_confirmed_time:.1f}s'})."
                ),
                agents_involved=[AgentRole.PATCH_AGENT.value, AgentRole.REPRODUCER.value],
                timestamp_start=patch_start_time,
                timestamp_end=repro_confirmed_time or patch_start_time,
                estimated_cost=300,
                artifacts=[],
                severity="high",
            )
        )
    return waste


def detect_test_edit_cheat(events: list) -> list[WasteEvent]:
    """Patch agent edited test files."""
    waste: list[WasteEvent] = []
    for evt in events:
        if evt.agent == AgentRole.PATCH_AGENT.value and evt.event == EventType.FILE_EDIT:
            artifact = evt.artifact.lower()
            if any(
                keyword in artifact
                for keyword in ["test_", "_test", "/tests/", "/test/", "spec"]
            ):
                waste.append(
                    WasteEvent(
                        waste_type=WasteType.TEST_EDIT_CHEAT,
                        description=(
                            f"Patch agent edited test file '{evt.artifact}' at T={evt.timestamp:.1f}s. "
                            "Patches should only modify source files."
                        ),
                        agents_involved=[AgentRole.PATCH_AGENT.value],
                        timestamp_start=evt.timestamp,
                        timestamp_end=evt.timestamp,
                        estimated_cost=500,
                        artifacts=[evt.artifact],
                        severity="critical",
                    )
                )
    return waste


def detect_irrelevant_search(events: list, task_signature: dict) -> list[WasteEvent]:
    """Agents searched directories unrelated to the stack trace."""
    waste: list[WasteEvent] = []
    top_file = task_signature.get("top_stack_file", "")
    if not top_file:
        return waste

    top_dir = top_file.split("/")[0] if "/" in top_file else ""
    if not top_dir:
        return waste

    for evt in events:
        if evt.event not in (EventType.GREP_SEARCH, EventType.FILE_READ):
            continue
        if not evt.artifact:
            continue
        artifact_lower = evt.artifact.lower()
        if (
            top_dir.lower() not in artifact_lower
            and "frontend" in artifact_lower
            and "backend" in task_signature.get("service", "").lower()
        ):
            waste.append(
                WasteEvent(
                    waste_type=WasteType.IRRELEVANT_SEARCH,
                    description=(
                        f"'{evt.agent}' searched '{evt.artifact}' which is unrelated "
                        f"to the stack trace (top file: {top_file})."
                    ),
                    agents_involved=[evt.agent],
                    timestamp_start=evt.timestamp,
                    timestamp_end=evt.timestamp,
                    estimated_cost=evt.tokens_est,
                    artifacts=[evt.artifact],
                    severity="low",
                )
            )
    return waste


def detect_agent_idle(events: list) -> list[WasteEvent]:
    """Agent ran low-value tool calls while another had high-confidence evidence ready."""
    waste: list[WasteEvent] = []
    evidence_times: dict[str, float] = {}

    for evt in events:
        if evt.event == EventType.EVIDENCE_PUBLISH:
            evidence_times[evt.agent] = evt.timestamp

    for evt in events:
        if evt.event != EventType.TOOL_CALL:
            continue
        if evt.metadata.get("value", "high") != "low":
            continue
        for publisher, pub_time in evidence_times.items():
            if publisher == evt.agent:
                continue
            if pub_time < evt.timestamp and (evt.timestamp - pub_time) > IDLE_THRESHOLD_SEC:
                waste.append(
                    WasteEvent(
                        waste_type=WasteType.AGENT_IDLE,
                        description=(
                            f"'{evt.agent}' ran low-value tool call at T={evt.timestamp:.1f}s "
                            f"while '{publisher}' had published evidence {evt.timestamp - pub_time:.0f}s earlier."
                        ),
                        agents_involved=[evt.agent, publisher],
                        timestamp_start=pub_time,
                        timestamp_end=evt.timestamp,
                        estimated_cost=evt.tokens_est,
                        artifacts=[],
                        severity="medium",
                    )
                )
                break
    return waste


def run_all_detectors(events: list, task_signature: dict) -> list[WasteEvent]:
    """Run every detector and return combined waste events."""
    detectors = [
        detect_duplicate_file_reads(events),
        detect_premature_full_suite(events),
        detect_late_evidence_propagation(events),
        detect_bad_routing(events),
        detect_test_edit_cheat(events),
        detect_irrelevant_search(events, task_signature),
        detect_agent_idle(events),
    ]
    result = []
    for findings in detectors:
        result.extend(findings)
    return result
