"""ROI Analyzer: metrics layer + LLM-as-Judge + composite scoring + retrospective."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import anthropic

from .schemas import (
    AgentRole,
    EventType,
    JudgeVerdict,
    MemoryEntryType,
    ROIReport,
    RunMetrics,
    RetrievalStrategy,
    WasteEvent,
    WasteType,
)
if TYPE_CHECKING:
    from .memory import MemoryManager
from .tracer import SwarmTracer
from .waste_detectors import run_all_detectors


_JUDGE_SYSTEM_PROMPT = """You are an expert agent-swarm performance evaluator. You analyze traces from 
coding-agent swarms and produce holistic ROI assessments. You look beyond raw numbers to understand:
- Whether agents genuinely collaborated or worked in silos
- Whether the evidence chain was coherent and used effectively
- Whether the investigation was targeted or scattered
- Whether the patch was minimal and correct or bloated and lucky
- Whether the swarm routing made sense for the task class

You output structured JSON only. No prose outside the JSON object."""

_JUDGE_USER_TEMPLATE = """Evaluate this agent-swarm run and return a JSON verdict.

TASK:
{task_description}

TASK SIGNATURE:
{task_signature}

RUN METRICS:
{metrics}

WASTE EVENTS DETECTED:
{waste_events}

TRACE SUMMARY (chronological key events):
{trace_summary}

FINAL PATCH DESCRIPTION:
{patch_description}

Return a JSON object with exactly these fields:
{{
  "investigation_quality": <0.0-1.0, how well agents investigated the right things>,
  "evidence_utilization": <0.0-1.0, how well evidence from one agent was used by others>,
  "patch_quality": <0.0-1.0, correctness and minimality of the patch>,
  "coordination_score": <0.0-1.0, how well agents coordinated vs worked in silos>,
  "overall_roi": <0.0-1.0, holistic value delivered relative to resources spent>,
  "key_insight": <one sentence describing the most important observation about this run>,
  "top_waste": <string naming the single most impactful waste pattern>,
  "confidence": <"high"|"medium"|"low">,
  "reasoning": <2-4 sentences explaining your overall_roi score>
}}"""


def _compute_raw_metrics(tracer: SwarmTracer, run_id: str) -> RunMetrics:
    events = tracer._events

    file_reads = [e for e in events if e.event == EventType.FILE_READ]
    file_edits = [e for e in events if e.event == EventType.FILE_EDIT]
    test_runs = [e for e in events if e.event == EventType.TEST_RUN]
    bash_cmds = [e for e in events if e.event == EventType.BASH_COMMAND]
    evidence = [e for e in events if e.event == EventType.EVIDENCE_PUBLISH]
    blocked = [e for e in events if e.event == EventType.BLOCKED_ACTION]

    tokens_total = sum(e.tokens_est for e in events)

    seen_files: dict[str, str] = {}
    dup_reads = 0
    for e in file_reads:
        key = e.artifact
        if key in seen_files and seen_files[key] != e.agent:
            dup_reads += 1
        seen_files[key] = e.agent

    target_passed = any(
        e.event == EventType.TEST_RUN
        and e.metadata.get("test_scope") == "target"
        and e.metadata.get("passed")
        for e in events
    )
    suite_passed = any(
        e.event == EventType.TEST_RUN
        and e.metadata.get("test_scope") == "full_suite"
        and e.metadata.get("passed")
        for e in events
    )

    patch_diff_lines = 0
    test_files_edited = False
    for e in file_edits:
        patch_diff_lines += e.metadata.get("lines_changed", 0)
        artifact_lower = e.artifact.lower()
        if any(k in artifact_lower for k in ["test_", "_test", "/tests/", "spec"]):
            test_files_edited = True

    return RunMetrics(
        run_id=run_id,
        wall_time_sec=tracer.elapsed(),
        tokens_total=tokens_total,
        file_reads=len(file_reads),
        duplicate_file_reads=dup_reads,
        test_runs=len(test_runs),
        file_edits=len(file_edits),
        bash_commands=len(bash_cmds),
        evidence_published=len(evidence),
        blocked_actions=len(blocked),
        target_test_passed=target_passed,
        full_suite_passed=suite_passed,
        patch_diff_lines=patch_diff_lines,
        test_files_edited=test_files_edited,
    )


def _compute_formula_roi(metrics: RunMetrics, waste_events: list[WasteEvent]) -> float:
    """Reference formula — transparent and configurable."""
    success = 0.0
    if metrics.target_test_passed:
        success += 100
    if metrics.full_suite_passed:
        success += 50
    if 0 < metrics.patch_diff_lines <= 20:
        success += 20
    if metrics.test_files_edited:
        success -= 50
    critical_waste = sum(1 for w in waste_events if w.severity == "critical")
    success -= critical_waste * 30

    cost = (
        0.001 * metrics.tokens_total
        + 5 * metrics.test_runs
        + 2 * metrics.file_reads
        + 10 * (metrics.wall_time_sec / 60)
        + 4 * metrics.duplicate_file_reads
    )
    cost = max(cost, 1.0)
    return round(success / cost, 3)


def _build_trace_summary(tracer: SwarmTracer, max_events: int = 30) -> str:
    events = tracer._events
    key_types = {
        EventType.AGENT_START,
        EventType.AGENT_END,
        EventType.EVIDENCE_PUBLISH,
        EventType.TEST_RUN,
        EventType.PATCH_ATTEMPT,
        EventType.BLOCKED_ACTION,
    }
    key_events = [e for e in events if e.event in key_types]
    sample = key_events[:max_events]
    lines = []
    for e in sample:
        lines.append(
            f"  T={e.timestamp:6.1f}s [{e.agent:20s}] {e.event.value:25s} {e.artifact[:60]}"
        )
    return "\n".join(lines) if lines else "(no key events)"


def _formula_only_judge(metrics: RunMetrics, waste_events: list[WasteEvent]) -> JudgeVerdict:
    """Heuristic judge verdict derived from metrics alone (no LLM call)."""
    score = 0.5
    if metrics.target_test_passed:
        score += 0.2
    if metrics.full_suite_passed:
        score += 0.1
    if metrics.test_files_edited:
        score -= 0.3
    score -= min(len(waste_events) * 0.05, 0.3)
    score = round(max(0.0, min(1.0, score)), 3)
    top = waste_events[0].waste_type.value if waste_events else ""
    return JudgeVerdict(
        investigation_quality=score,
        evidence_utilization=score,
        patch_quality=score,
        coordination_score=score,
        overall_roi=score,
        key_insight="(formula-only: no LLM judge)",
        top_waste=top,
        confidence="low",
        reasoning="LLM judge skipped — client not provided.",
    )


async def call_llm_judge(
    client: anthropic.AsyncAnthropic | None,
    tracer: SwarmTracer,
    metrics: RunMetrics,
    waste_events: list[WasteEvent],
    task_signature: dict[str, Any],
    task_description: str,
    patch_description: str = "",
) -> JudgeVerdict:
    if client is None:
        return _formula_only_judge(metrics, waste_events)

    trace_summary = _build_trace_summary(tracer)
    waste_summary = json.dumps(
        [w.to_dict() for w in waste_events], indent=2
    ) if waste_events else "None detected"

    user_msg = _JUDGE_USER_TEMPLATE.format(
        task_description=task_description,
        task_signature=json.dumps(task_signature, indent=2),
        metrics=json.dumps(metrics.to_dict(), indent=2),
        waste_events=waste_summary,
        trace_summary=trace_summary,
        patch_description=patch_description or "(not available)",
    )

    response = await client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        system=_JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw)

    return JudgeVerdict(
        investigation_quality=float(data.get("investigation_quality", 0.5)),
        evidence_utilization=float(data.get("evidence_utilization", 0.5)),
        patch_quality=float(data.get("patch_quality", 0.5)),
        coordination_score=float(data.get("coordination_score", 0.5)),
        overall_roi=float(data.get("overall_roi", 0.5)),
        key_insight=data.get("key_insight", ""),
        top_waste=data.get("top_waste", ""),
        confidence=data.get("confidence", "medium"),
        reasoning=data.get("reasoning", ""),
    )


def _compute_composite_roi(formula_roi: float, judge_verdict: JudgeVerdict) -> float:
    """
    Blend formula ROI (normalized) with judge ROI.
    Formula captures hard objective costs; judge captures qualitative coherence.
    Weights are intentionally transparent and configurable.
    """
    formula_normalized = min(formula_roi / 2.0, 1.0)
    composite = 0.4 * formula_normalized + 0.6 * judge_verdict.overall_roi
    return round(composite, 3)


_RETROSPECTIVE_SYSTEM = """You are an expert in agent-swarm optimization. You write concise, 
actionable retrospectives for engineering teams. Be specific, cite timing and agent names, 
and focus on what should change in the next run."""

_RETROSPECTIVE_TEMPLATE = """Write a retrospective for this agent-swarm run.

TASK: {task_description}
COMPOSITE ROI SCORE: {roi_score:.2f} / 1.0
FORMULA ROI: {formula_roi:.3f}
JUDGE OVERALL ROI: {judge_overall:.2f}

JUDGE KEY INSIGHT: {key_insight}
JUDGE REASONING: {reasoning}

WASTE EVENTS:
{waste_summary}

METRICS:
{metrics_summary}

Write a retrospective with these sections:
1. What went well
2. Key waste patterns and their impact
3. Root cause of the biggest inefficiency
4. Specific changes for next run (routing, prompts, gating)

Be direct, specific, and under 300 words."""


async def generate_retrospective(
    client: anthropic.AsyncAnthropic | None,
    metrics: RunMetrics,
    waste_events: list[WasteEvent],
    judge_verdict: JudgeVerdict,
    formula_roi: float,
    composite_roi: float,
    task_description: str,
) -> str:
    if client is None:
        waste_lines = "; ".join(f"{w.waste_type.value}" for w in waste_events) or "none"
        return (
            f"Formula ROI: {formula_roi:.3f} | Composite: {composite_roi:.3f} | "
            f"target_pass={metrics.target_test_passed} suite_pass={metrics.full_suite_passed} | "
            f"Waste: {waste_lines}"
        )
    waste_summary = "\n".join(
        f"- [{w.severity.upper()}] {w.waste_type.value}: {w.description}"
        for w in waste_events
    ) or "None"

    metrics_summary = (
        f"wall_time={metrics.wall_time_sec:.1f}s, tokens={metrics.tokens_total}, "
        f"file_reads={metrics.file_reads}, dup_reads={metrics.duplicate_file_reads}, "
        f"test_runs={metrics.test_runs}, target_pass={metrics.target_test_passed}, "
        f"suite_pass={metrics.full_suite_passed}"
    )

    prompt = _RETROSPECTIVE_TEMPLATE.format(
        task_description=task_description,
        roi_score=composite_roi,
        formula_roi=formula_roi,
        judge_overall=judge_verdict.overall_roi,
        key_insight=judge_verdict.key_insight,
        reasoning=judge_verdict.reasoning,
        waste_summary=waste_summary,
        metrics_summary=metrics_summary,
    )

    response = await client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[
            {"role": "user", "content": prompt}
        ],
        system=_RETROSPECTIVE_SYSTEM,
    )
    return response.content[0].text.strip()


_PROMPT_PATCH_SYSTEM = """You generate precise, actionable prompt patches for coding agents.
Each patch is a list of instruction sentences that will be prepended to an agent's system prompt.
Output JSON only."""

_PROMPT_PATCH_TEMPLATE = """Based on this retrospective and waste analysis, generate prompt patches for the agents.

TASK TYPE: {task_description}
WASTE EVENTS: {waste_summary}
JUDGE KEY INSIGHT: {key_insight}
TOP WASTE: {top_waste}

For each agent role that needs improvement, output a JSON object like:
{{
  "<agent_role>": [
    "<instruction sentence 1>",
    "<instruction sentence 2>"
  ]
}}

Agent roles: log_investigator, code_investigator, reproducer, patch_agent, verifier

Only include roles that genuinely need new instructions based on the waste events.
Keep each instruction concrete and actionable (not generic).
Maximum 4 instructions per agent."""


async def generate_prompt_patches(
    client: anthropic.AsyncAnthropic | None,
    waste_events: list[WasteEvent],
    judge_verdict: JudgeVerdict,
    task_description: str,
) -> dict[str, list[str]]:
    if client is None:
        return {}
    waste_summary = "\n".join(
        f"- {w.waste_type.value}: {w.description}" for w in waste_events
    ) or "None"

    prompt = _PROMPT_PATCH_TEMPLATE.format(
        task_description=task_description,
        waste_summary=waste_summary,
        key_insight=judge_verdict.key_insight,
        top_waste=judge_verdict.top_waste,
    )

    response = await client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
        system=_PROMPT_PATCH_SYSTEM,
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


_ROUTING_SYSTEM = """You output routing rule updates for agent-swarm schedulers as JSON only."""

_ROUTING_TEMPLATE = """Based on waste events and judge feedback, suggest routing rule updates.

CURRENT ROUTING: {current_routing}
WASTE EVENTS: {waste_summary}
BAD ROUTING DETECTED: {bad_routing_found}
JUDGE COORDINATION SCORE: {coordination_score:.2f}

Output a JSON object with any of these keys that should change:
{{
  "first_agent": "<role>",
  "second_agent": "<role>",
  "patch_agent_start_condition": "<condition string>",
  "full_suite_condition": "<condition string>",
  "agent_order": ["<role1>", "<role2>", ...]
}}

Only include keys that should actually change."""


async def generate_routing_update(
    client: anthropic.AsyncAnthropic | None,
    waste_events: list[WasteEvent],
    judge_verdict: JudgeVerdict,
    current_routing: dict[str, Any],
) -> dict[str, Any]:
    if client is None:
        return {}
    waste_summary = "\n".join(
        f"- {w.waste_type.value}: {w.description}" for w in waste_events
    ) or "None"
    bad_routing = any(w.waste_type == WasteType.BAD_ROUTING for w in waste_events)

    prompt = _ROUTING_TEMPLATE.format(
        current_routing=json.dumps(current_routing, indent=2),
        waste_summary=waste_summary,
        bad_routing_found=bad_routing,
        coordination_score=judge_verdict.coordination_score,
    )

    response = await client.messages.create(
        model="claude-opus-4-5",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
        system=_ROUTING_SYSTEM,
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


async def analyze_run(
    tracer: SwarmTracer,
    task_signature: dict[str, Any],
    task_description: str,
    memory_manager: "MemoryManager",
    trajectory_id: str,
    client: anthropic.AsyncAnthropic | None = None,
    patch_description: str = "",
) -> ROIReport:
    """Full ROI analysis pipeline for a completed run. Pass client=None to skip LLM calls."""
    events = tracer._events

    metrics = _compute_raw_metrics(tracer, tracer.run_id)
    waste_events = run_all_detectors(events, task_signature)
    formula_roi = _compute_formula_roi(metrics, waste_events)

    judge_verdict = await call_llm_judge(
        client=client,
        tracer=tracer,
        metrics=metrics,
        waste_events=waste_events,
        task_signature=task_signature,
        task_description=task_description,
        patch_description=patch_description,
    )

    composite_roi = _compute_composite_roi(formula_roi, judge_verdict)

    retrospective = await generate_retrospective(
        client=client,
        metrics=metrics,
        waste_events=waste_events,
        judge_verdict=judge_verdict,
        formula_roi=formula_roi,
        composite_roi=composite_roi,
        task_description=task_description,
    )

    prompt_patches = await generate_prompt_patches(
        client=client,
        waste_events=waste_events,
        judge_verdict=judge_verdict,
        task_description=task_description,
    )

    routing_update = await generate_routing_update(
        client=client,
        waste_events=waste_events,
        judge_verdict=judge_verdict,
        current_routing=memory_manager.retrieve_and_consume(
            task_signature=task_signature,
            trajectory_id=trajectory_id,
            entry_types=[MemoryEntryType.ROUTING_RULE],
        ).raw or {},
    )

    return ROIReport(
        run_id=tracer.run_id,
        task_signature=task_signature,
        metrics=metrics,
        waste_events=waste_events,
        judge_verdict=judge_verdict,
        composite_roi_score=composite_roi,
        retrospective=retrospective,
        prompt_patches=prompt_patches,
        routing_update=routing_update,
    )
