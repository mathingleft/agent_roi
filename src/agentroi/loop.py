"""The AgentROI improvement loop: run → trace → analyze → update memory → next run."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import anthropic

from .memory import MemoryManager, make_memory_manager
from .memory_protocol import MemoryBackend, MemoryConsumer
from .roi_analyzer import analyze_run
from .schemas import AgentRole, ConsumerOutput, MemoryEntryType, RetrievalStrategy
from .swarm import SwarmOrchestrator
from .tracer import SwarmTracer

_ROLE_FOCUS: dict[str, str] = {
    AgentRole.LOG_INVESTIGATOR.value: (
        "Focus on: extract top stack frames, identify the service/module, "
        "produce root-cause hypotheses, publish high-signal evidence."
    ),
    AgentRole.CODE_INVESTIGATOR.value: (
        "Focus on: read relevant source files from the stack trace, "
        "map the call graph, identify the faulty function. Do not patch."
    ),
    AgentRole.REPRODUCER.value: (
        "Focus on: run the specific failing test first, create minimal repro, "
        "do not run full suite until target repro is confirmed. Publish exact failure command."
    ),
    AgentRole.PATCH_AGENT.value: (
        "Focus on: make a minimal source-only patch. "
        "Do not edit test files. Start from the top stack frame. "
        "Run target test after each attempt. Full suite only after target passes."
    ),
    AgentRole.VERIFIER.value: (
        "Focus on: confirm target test passes, run full suite, "
        "analyze the diff for minimality, check for test edits or anti-patterns."
    ),
}


class AgentROILoop:
    """
    Runs the full improvement loop:
    1. Retrieve memory for this task/trajectory via MemoryManager
    2. Build role-specific prompts with learned context injected
    3. Run traced swarm (SwarmOrchestrator)
    4. Analyze ROI (metrics + LLM judge + retrospective + patches)
    5. Store results back into memory via MemoryManager
    6. Persist trace + report

    MemoryManager is fully swappable — pass any backend/consumer combo.
    Trajectory isolation: each named trajectory gets its own isolated playbook.
    """

    def __init__(
        self,
        memory_path: Path,
        output_dir: Path,
        anthropic_client: anthropic.AsyncAnthropic | None = None,
        memory_backend: str = "ace",
        memory_manager: MemoryManager | None = None,
        agent_order: list[str] | None = None,
    ):
        self.memory = memory_manager or make_memory_manager(memory_path, backend=memory_backend)
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.client = anthropic_client  # None = formula-only ROI, no API key needed
        self._agent_order_override = agent_order  # CLI --agents flag takes priority

    def _make_run_id(self, task_signature: dict[str, Any], trajectory_id: str, n: int) -> str:
        sig = "_".join(
            v.replace(" ", "_").lower()[:10]
            for v in [task_signature.get("source", ""), task_signature.get("error_type", "")]
            if v
        )
        traj = trajectory_id[:8].replace(" ", "_")
        return f"{traj}_{sig}_run{n:03d}_{uuid.uuid4().hex[:6]}"

    def _build_prompts(
        self,
        task_description: str,
        task_signature: dict[str, Any],
        trajectory_id: str,
        run_id: str,
    ) -> dict[str, str]:
        """
        Build per-role prompts. Each role gets:
        - Task description
        - Role-specific focus instructions
        - Memory-injected context (prompt patches, waste patterns, evidence seeds)
          retrieved independently per role so each gets only what's relevant to it.
        """
        prompts: dict[str, str] = {}
        for role in AgentRole:
            memory_out: ConsumerOutput = self.memory.retrieve_and_consume(
                task_signature=task_signature,
                trajectory_id=trajectory_id,
                agent_role=role.value,
                strategy=RetrievalStrategy.EXACT,
                task_description=task_description,
                run_id=run_id,
            )
            parts = [task_description, "", _ROLE_FOCUS[role.value]]
            if memory_out.prompt_additions:
                parts.append(f"\n{memory_out.prompt_additions}")
            if memory_out.evidence_context:
                parts.append(f"\n{memory_out.evidence_context}")
            prompts[role.value] = "\n".join(parts)
        return prompts

    def _get_routing(
        self,
        task_signature: dict[str, Any],
        trajectory_id: str,
        task_description: str,
        run_id: str,
    ) -> ConsumerOutput:
        return self.memory.retrieve_and_consume(
            task_signature=task_signature,
            trajectory_id=trajectory_id,
            entry_types=[MemoryEntryType.ROUTING_RULE],
            task_description=task_description,
            run_id=run_id,
        )

    async def run_once(
        self,
        task_description: str,
        task_signature: dict[str, Any],
        cwd: Path,
        trajectory_id: str = "default",
        run_id: str | None = None,
        patch_description: str = "",
    ) -> dict[str, Any]:
        """Run one full loop iteration: swarm + analyze + memory update."""
        n = len(self.memory.snapshot(trajectory_id)) + 1
        run_id = run_id or self._make_run_id(task_signature, trajectory_id, n)

        self.memory.create_trajectory(trajectory_id)

        tracer = SwarmTracer(run_id=run_id, output_dir=self.output_dir)

        prompts = self._build_prompts(task_description, task_signature, trajectory_id, run_id)
        routing_out = self._get_routing(task_signature, trajectory_id, task_description, run_id)

        orchestrator = SwarmOrchestrator(
            tracer=tracer,
            task_id=run_id,
            task_description=task_description,
            memory_manager=self.memory,
            task_signature=task_signature,
            trajectory_id=trajectory_id,
            agent_order=self._agent_order_override or routing_out.agent_order or None,
            cwd=cwd,
        )

        swarm_result = await orchestrator.run(prompts)

        roi_report = await analyze_run(
            tracer=tracer,
            task_signature=task_signature,
            task_description=task_description,
            memory_manager=self.memory,
            trajectory_id=trajectory_id,
            client=self.client,
            patch_description=patch_description,
        )

        report_dict = roi_report.to_dict()

        self.memory.store_roi_results(
            task_signature=task_signature,
            trajectory_id=trajectory_id,
            roi_report_dict=report_dict,
        )

        report_path = self.output_dir / f"{run_id}_roi_report.json"
        with report_path.open("w") as f:
            json.dump(report_dict, f, indent=2)

        return {
            "run_id": run_id,
            "trajectory_id": trajectory_id,
            "roi_report": roi_report,
            "report_path": str(report_path),
            "swarm_result": swarm_result,
            "composite_roi": roi_report.composite_roi_score,
        }

    async def run_loop(
        self,
        task_description: str,
        task_signature: dict[str, Any],
        cwd: Path,
        trajectory_id: str = "default",
        num_iterations: int = 3,
    ) -> list[dict[str, Any]]:
        """Run multiple iterations within a trajectory, compounding memory each run."""
        history: list[dict[str, Any]] = []
        for i in range(num_iterations):
            result = await self.run_once(
                task_description=task_description,
                task_signature=task_signature,
                cwd=cwd,
                trajectory_id=trajectory_id,
            )
            history.append(result)
        return history
