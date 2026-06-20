"""
Concrete MemoryConsumer implementations.

PromptInjector   — turns PromptPatch + WastePattern entries into system prompt additions
RoutingDecider   — turns RoutingRule entries into an ordered agent list
ActionBlocklist  — turns PromptPatch entries flagged blocked=True into a set of blocked tools
EvidenceSeeder   — turns HighROIContext + EpisodicRecord entries into an evidence context string

All four implement the MemoryConsumer protocol from memory_protocol.py.
They are composable via memory_protocol.compose_outputs().
"""
from __future__ import annotations

from typing import Any

from .schemas import (
    AgentRole,
    ConsumerContext,
    ConsumerOutput,
    MemoryEntry,
    MemoryEntryType,
)

_DEFAULT_AGENT_ORDER = [
    AgentRole.LOG_INVESTIGATOR.value,
    AgentRole.CODE_INVESTIGATOR.value,
    AgentRole.REPRODUCER.value,
    AgentRole.PATCH_AGENT.value,
    AgentRole.VERIFIER.value,
]

_DEFAULT_BLOCKED: dict[str, set[str]] = {
    AgentRole.LOG_INVESTIGATOR.value: {"file_edit"},
    AgentRole.CODE_INVESTIGATOR.value: {"file_edit"},
    AgentRole.REPRODUCER.value: {"file_edit"},
    AgentRole.PATCH_AGENT.value: {"edit_test_files"},
    AgentRole.VERIFIER.value: {"file_edit"},
}


class PromptInjector:
    """
    Converts PromptPatch and WastePattern entries into text additions
    that get prepended to an agent's system prompt.

    Consumer is role-aware: if context.agent_role is set, only patches
    for that role (plus global patches with no role) are included.
    """

    name = "prompt_injector"

    def consume(
        self,
        entries: list[MemoryEntry],
        context: ConsumerContext,
    ) -> ConsumerOutput:
        patches: list[str] = []
        waste_avoid: list[str] = []

        for entry in entries:
            if entry.entry_type == MemoryEntryType.PROMPT_PATCH:
                if context.agent_role and entry.agent_role and entry.agent_role != context.agent_role:
                    continue
                content = entry.content if isinstance(entry.content, str) else str(entry.content)
                patches.append(content)

            elif entry.entry_type == MemoryEntryType.WASTE_PATTERN:
                content = entry.content if isinstance(entry.content, str) else str(entry.content)
                waste_avoid.append(content)

        parts: list[str] = []
        if patches:
            parts.append("LEARNED INSTRUCTIONS FROM PREVIOUS RUNS:")
            for p in patches:
                parts.append(f"- {p}")
        if waste_avoid:
            parts.append("\nKNOWN WASTE PATTERNS TO AVOID:")
            for w in waste_avoid:
                parts.append(f"- Avoid: {w}")

        return ConsumerOutput(
            prompt_additions="\n".join(parts) if parts else "",
        )


class RoutingDecider:
    """
    Converts RoutingRule entries into an ordered agent list.

    Falls back to default ordering if no routing rules exist.
    If multiple routing rules exist, uses the one with the highest net_score.
    """

    name = "routing_decider"

    def consume(
        self,
        entries: list[MemoryEntry],
        context: ConsumerContext,
    ) -> ConsumerOutput:
        routing_entries = [
            e for e in entries
            if e.entry_type == MemoryEntryType.ROUTING_RULE
        ]

        if not routing_entries:
            return ConsumerOutput(agent_order=_DEFAULT_AGENT_ORDER.copy())

        best = max(routing_entries, key=lambda e: e.net_score)
        content = best.content

        if isinstance(content, dict):
            order = content.get("agent_order", _DEFAULT_AGENT_ORDER)
        elif isinstance(content, str):
            order = [r.strip() for r in content.split(",") if r.strip()]
            if not order:
                order = _DEFAULT_AGENT_ORDER.copy()
        else:
            order = _DEFAULT_AGENT_ORDER.copy()

        return ConsumerOutput(
            agent_order=order,
            raw={
                "routing_rule_id": best.id,
                "routing_rule_score": best.net_score,
                "patch_agent_start_condition": (
                    content.get("patch_agent_start_condition", "target_repro_confirmed")
                    if isinstance(content, dict) else "target_repro_confirmed"
                ),
                "full_suite_condition": (
                    content.get("full_suite_condition", "target_test_passed")
                    if isinstance(content, dict) else "target_test_passed"
                ),
            },
        )


class ActionBlocklist:
    """
    Produces a set of blocked tool names for a specific agent role.

    Sources:
    1. Hardcoded defaults (always applied)
    2. PromptPatch entries where metadata["blocked"] == True
    """

    name = "action_blocklist"

    def consume(
        self,
        entries: list[MemoryEntry],
        context: ConsumerContext,
    ) -> ConsumerOutput:
        blocked: set[str] = set(
            _DEFAULT_BLOCKED.get(context.agent_role, set())
        )

        for entry in entries:
            if entry.entry_type != MemoryEntryType.PROMPT_PATCH:
                continue
            if context.agent_role and entry.agent_role and entry.agent_role != context.agent_role:
                continue
            if not entry.metadata.get("blocked"):
                continue
            action = entry.metadata.get("blocked_action", "")
            if action:
                blocked.add(action)

        return ConsumerOutput(blocked_tools=blocked)


class EvidenceSeeder:
    """
    Converts HighROIContext and EpisodicRecord entries into a pre-loaded
    evidence context string that gets injected into agent prompts before
    any tool calls are made.

    Prioritizes by net_score, caps at max_entries to avoid prompt bloat.
    """

    name = "evidence_seeder"

    def __init__(self, max_entries: int = 8):
        self.max_entries = max_entries

    def consume(
        self,
        entries: list[MemoryEntry],
        context: ConsumerContext,
    ) -> ConsumerOutput:
        high_roi: list[MemoryEntry] = []
        episodic: list[MemoryEntry] = []

        for entry in entries:
            if entry.entry_type == MemoryEntryType.HIGH_ROI_CONTEXT:
                high_roi.append(entry)
            elif entry.entry_type == MemoryEntryType.EPISODIC_RECORD:
                episodic.append(entry)

        high_roi.sort(key=lambda e: e.net_score, reverse=True)
        episodic.sort(key=lambda e: e.net_score, reverse=True)

        parts: list[str] = []

        if high_roi:
            parts.append("HIGH-SIGNAL CONTEXT FROM PREVIOUS SIMILAR RUNS:")
            for e in high_roi[: self.max_entries]:
                content = e.content if isinstance(e.content, str) else str(e.content)
                parts.append(f"- {content}")

        if episodic:
            parts.append("\nRELEVANT PAST RUN SUMMARY:")
            best_ep = episodic[0]
            content = best_ep.content
            if isinstance(content, dict):
                roi = content.get("roi_score", "?")
                retro = content.get("retrospective_snippet", "")
                parts.append(f"  Best similar run ROI: {roi}")
                if retro:
                    parts.append(f"  Key lesson: {retro}")
            else:
                parts.append(f"  {str(content)[:300]}")

        return ConsumerOutput(
            evidence_context="\n".join(parts) if parts else "",
        )


class CompositeConsumer:
    """
    Runs multiple consumers over the same entry list and merges outputs.
    This is the default consumer used by the loop.
    """

    name = "composite"

    def __init__(self, consumers: list[Any]):
        self.consumers = consumers

    def consume(
        self,
        entries: list[MemoryEntry],
        context: ConsumerContext,
    ) -> ConsumerOutput:
        from .memory_protocol import compose_outputs
        outputs = [c.consume(entries, context) for c in self.consumers]
        return compose_outputs(*outputs)


def default_consumer() -> CompositeConsumer:
    """The default consumer stack used when none is specified."""
    return CompositeConsumer([
        PromptInjector(),
        RoutingDecider(),
        ActionBlocklist(),
        EvidenceSeeder(),
    ])
