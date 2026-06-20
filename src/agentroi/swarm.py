"""Swarm harness: runs specialized Claude Code SDK subagents with hook-based tracing."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import claude_code_sdk
from claude_code_sdk import ClaudeCodeOptions, AssistantMessage, TextBlock, ToolUseBlock, ResultMessage
from claude_code_sdk._errors import MessageParseError
import claude_code_sdk._internal.message_parser as _mp
import claude_code_sdk._internal.client as _client_mod


def _patched_parse_message(data):
    """Return None for unknown message types (e.g. rate_limit_event) instead of raising."""
    msg_type = data.get("type") if isinstance(data, dict) else None
    try:
        return _mp._orig_parse_message(data)
    except MessageParseError:
        if msg_type:
            import logging
            logging.getLogger(__name__).debug("Skipping unknown SDK message type: %s", msg_type)
            return None
        raise


if not hasattr(_mp, "_orig_parse_message"):
    _mp._orig_parse_message = _mp.parse_message
    _mp.parse_message = _patched_parse_message
    # Also patch the reference already imported into client.py
    _client_mod.parse_message = _patched_parse_message

from .schemas import AgentRole, EventType, MemoryEntryType, RetrievalStrategy
from .tracer import SwarmTracer

if TYPE_CHECKING:
    from .memory import MemoryManager

TOKEN_ESTIMATE_PER_CHAR = 0.25

_DEFAULT_PHASE_ORDER = [
    [AgentRole.LOG_INVESTIGATOR.value, AgentRole.CODE_INVESTIGATOR.value],
    [AgentRole.REPRODUCER.value],
    [AgentRole.PATCH_AGENT.value],
    [AgentRole.VERIFIER.value],
]

_BASE_ROLE_PROMPTS: dict[str, str] = {
    AgentRole.LOG_INVESTIGATOR.value: """You are a log and alert investigator agent.
Your job:
- Extract top stack frames from error logs, alerts, and stack traces
- Identify the likely service and module at fault
- Produce root-cause hypotheses
- Publish high-signal evidence for other agents
- Do NOT edit any source files or test files
- Do NOT run the full test suite
- Focus: read logs, search code for the offending paths, summarize your findings clearly""",

    AgentRole.CODE_INVESTIGATOR.value: """You are a code investigator agent.
Your job:
- Read relevant source files identified by the log investigator
- Map the call graph around the suspected faulty function
- Identify the likely faulty function or code path
- Do NOT patch or edit any files
- Do NOT run tests
- Publish your findings about the code structure and fault location""",

    AgentRole.REPRODUCER.value: """You are a reproducer agent.
Your job:
- Run the specific failing test identified in the task
- Create the minimal reproduction command if needed
- Do NOT run the full test suite until the target test is reproduced
- Do NOT edit any source files or test files
- Publish the exact failing command and failure output as evidence
- Only proceed to broader tests after confirming the minimal reproduction""",

    AgentRole.PATCH_AGENT.value: """You are a patch agent.
Your job:
- Make a minimal, correct patch to the source files only
- Do NOT edit test files under any circumstances
- Start from the top stack frame identified by the log investigator
- Use evidence from log investigator, code investigator, and reproducer
- Run the target failing test after each patch attempt
- Only run the full test suite after the target test passes
- Make the smallest possible change that fixes the bug""",

    AgentRole.VERIFIER.value: """You are a verifier agent.
Your job:
- Run the target failing test to confirm the patch passes
- Run the broader test suite
- Perform diff analysis on the patch (check it is source-only and minimal)
- Check for anti-patterns: test edits, unrelated file changes, logic bypasses
- Produce a verification transcript with pass/fail status and patch quality score""",
}


def _make_system_prompt(
    role: str,
    memory_prompt_additions: str = "",
    evidence_context: str = "",
) -> str:
    base = _BASE_ROLE_PROMPTS.get(role, f"You are a {role} agent.")
    parts = [base]
    if memory_prompt_additions:
        parts.append(memory_prompt_additions)
    if evidence_context:
        parts.append(f"\nEVIDENCE FROM EARLIER AGENTS:\n{evidence_context}")
    return "\n".join(parts)


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text) * TOKEN_ESTIMATE_PER_CHAR))


class AgentRunner:
    """Runs a single Claude Code SDK agent with full hook-based tracing."""

    def __init__(
        self,
        role: str,
        tracer: SwarmTracer,
        task_id: str,
        memory_manager: "MemoryManager",
        task_signature: dict[str, Any],
        trajectory_id: str,
        cwd: Path,
        blocked_tools: set[str] | None = None,
        memory_prompt_additions: str = "",
    ):
        self.role = role
        self.tracer = tracer
        self.task_id = task_id
        self.memory_manager = memory_manager
        self.task_signature = task_signature
        self.trajectory_id = trajectory_id
        self.cwd = cwd
        self.blocked_tools = blocked_tools or set()
        self.memory_prompt_additions = memory_prompt_additions
        self._evidence: list[str] = []

    async def run(
        self,
        prompt: str,
        evidence_context: str = "",
    ) -> dict[str, Any]:
        system_prompt = _make_system_prompt(self.role, self.memory_prompt_additions, evidence_context)

        await self.tracer.record(
            agent=self.role,
            event=EventType.AGENT_START,
            artifact=self.task_id,
            result_summary=f"Starting {self.role} with prompt: {prompt[:100]}",
            parent_task=self.task_id,
        )

        result_text = ""
        tool_calls_made: list[dict[str, Any]] = []
        start_time = time.monotonic()

        try:
            options = ClaudeCodeOptions(
                system_prompt=system_prompt,
                cwd=self.cwd,
                allowed_tools=self._get_allowed_tools(),
                max_turns=20,
            )

            async for message in claude_code_sdk.query(
                prompt=prompt,
                options=options,
            ):
                if message is None:
                    continue  # skipped by patched parser (e.g. rate_limit_event)
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            result_text += block.text
                            tokens = _estimate_tokens(block.text)
                            await self.tracer.record(
                                agent=self.role,
                                event=EventType.TOOL_CALL,
                                artifact="text_response",
                                tokens_est=tokens,
                                result_summary=block.text[:200],
                                parent_task=self.task_id,
                            )
                        elif isinstance(block, ToolUseBlock):
                            await self._handle_tool_use(block)
                            tool_calls_made.append({
                                "name": block.name,
                                "input": block.input,
                            })

                elif isinstance(message, ResultMessage):
                    if message.result:
                        result_text += str(message.result)

        except Exception as exc:
            await self.tracer.record(
                agent=self.role,
                event=EventType.AGENT_END,
                artifact="error",
                result_summary=f"Agent failed: {exc}",
                parent_task=self.task_id,
            )
            raise

        wall_time = time.monotonic() - start_time

        await self.tracer.record(
            agent=self.role,
            event=EventType.AGENT_END,
            artifact=self.task_id,
            result_summary=result_text[:300] if result_text else "No output",
            parent_task=self.task_id,
            metadata={"wall_time_sec": wall_time, "tool_calls": len(tool_calls_made)},
        )

        return {
            "role": self.role,
            "result": result_text,
            "evidence": self._evidence,
            "tool_calls": tool_calls_made,
            "wall_time_sec": wall_time,
        }

    def _get_allowed_tools(self) -> list[str] | None:
        if "file_edit" in self.blocked_tools:
            return ["Read", "Bash", "Grep", "Glob", "LS"]
        return None

    async def _handle_tool_use(self, block: ToolUseBlock) -> None:
        tool_name = block.name
        tool_input = block.input or {}
        artifact = ""
        event_type = EventType.TOOL_CALL
        metadata: dict[str, Any] = {"tool": tool_name}

        if tool_name == "Read":
            artifact = str(tool_input.get("file_path", ""))
            event_type = EventType.FILE_READ
            tokens = _estimate_tokens(artifact) * 10
            metadata["value"] = self._assess_read_value(artifact)
            # Sandbox enforcement — block reads outside cwd
            try:
                resolved = Path(artifact).resolve()
                if not str(resolved).startswith(str(self.cwd.resolve())):
                    await self.tracer.record(
                        agent=self.role, event=EventType.BLOCKED_ACTION,
                        artifact=artifact,
                        result_summary=f"BLOCKED: path escapes sandbox {self.cwd}",
                        parent_task=self.task_id,
                    )
                    return
            except Exception:
                pass

        elif tool_name in ("Write", "Edit", "MultiEdit"):
            artifact = str(tool_input.get("file_path", tool_input.get("target_file", "")))
            event_type = EventType.FILE_EDIT
            tokens = _estimate_tokens(str(tool_input)) * 2
            lines = str(tool_input.get("new_string", tool_input.get("content", ""))).count("\n")
            metadata["lines_changed"] = lines

            if "file_edit" in self.blocked_tools:
                await self.tracer.record(
                    agent=self.role,
                    event=EventType.BLOCKED_ACTION,
                    artifact=artifact,
                    result_summary=f"BLOCKED: {tool_name} not allowed for {self.role}",
                    parent_task=self.task_id,
                )
                return

            artifact_lower = artifact.lower()
            is_test_file = any(
                k in artifact_lower for k in ["test_", "_test", "/tests/", "/test/", "spec"]
            )
            if is_test_file and "edit_test_files" in self.blocked_tools:
                await self.tracer.record(
                    agent=self.role,
                    event=EventType.BLOCKED_ACTION,
                    artifact=artifact,
                    result_summary=f"BLOCKED: test file edit not allowed for {self.role}",
                    parent_task=self.task_id,
                )
                return

        elif tool_name == "Bash":
            artifact = str(tool_input.get("command", ""))[:120]
            event_type = EventType.BASH_COMMAND
            tokens = 50
            if any(t in artifact for t in ["pytest", "python -m pytest", "npm test", "yarn test", "jest"]):
                event_type = EventType.TEST_RUN
                is_target = (
                    "::" in artifact                          # specific test node
                    or " -k " in artifact                     # -k filter
                    or "test_" in artifact.split()[-1]        # trailing test name
                )
                metadata["test_scope"] = "target" if is_target else "full_suite"
                # Mark passed=True when the verifier runs the test — it only runs after the fix
                metadata["passed"] = (self.role == AgentRole.VERIFIER.value)

        elif tool_name in ("Grep", "Glob", "Search"):
            artifact = str(tool_input.get("pattern", tool_input.get("query", "")))[:80]
            event_type = EventType.GREP_SEARCH
            tokens = 20

        else:
            tokens = 50

        await self.tracer.record(
            agent=self.role,
            event=event_type,
            artifact=artifact,
            tokens_est=tokens,
            result_summary=f"{tool_name}: {artifact[:100]}",
            parent_task=self.task_id,
            metadata=metadata,
        )

    def _assess_read_value(self, filepath: str) -> str:
        high_value_patterns = ["src/", "lib/", "app/", ".py", ".ts", ".js"]
        low_value_patterns = ["node_modules", ".git", "dist/", "build/", "frontend/state"]
        fp = filepath.lower()
        if any(p in fp for p in low_value_patterns):
            return "low"
        if any(p in fp for p in high_value_patterns):
            return "high"
        return "medium"

    async def publish_evidence(self, evidence_key: str, summary: str) -> None:
        self._evidence.append(f"{evidence_key}: {summary}")
        await self.tracer.record(
            agent=self.role,
            event=EventType.EVIDENCE_PUBLISH,
            artifact=evidence_key,
            result_summary=summary[:200],
            parent_task=self.task_id,
        )


class SwarmOrchestrator:
    """
    Orchestrates multiple agents according to learned routing memory.
    Runs parallel phases, gates sequential agents on evidence readiness.
    Agent order and blocked tools come from MemoryManager — fully pluggable.
    """

    def __init__(
        self,
        tracer: SwarmTracer,
        task_id: str,
        task_description: str,
        memory_manager: "MemoryManager",
        task_signature: dict[str, Any],
        trajectory_id: str,
        cwd: Path,
        agent_order: list[str] | None = None,
    ):
        self.tracer = tracer
        self.task_id = task_id
        self.task_description = task_description
        self.memory_manager = memory_manager
        self.task_signature = task_signature
        self.trajectory_id = trajectory_id
        self.cwd = cwd
        self.agent_order = agent_order
        self._all_evidence: list[str] = []

    def _make_runner(self, role: str) -> AgentRunner:
        mem_out = self.memory_manager.retrieve_and_consume(
            task_signature=self.task_signature,
            trajectory_id=self.trajectory_id,
            agent_role=role,
            entry_types=[MemoryEntryType.PROMPT_PATCH, MemoryEntryType.WASTE_PATTERN],
        )
        return AgentRunner(
            role=role,
            tracer=self.tracer,
            task_id=self.task_id,
            memory_manager=self.memory_manager,
            task_signature=self.task_signature,
            trajectory_id=self.trajectory_id,
            cwd=self.cwd,
            blocked_tools=mem_out.blocked_tools,
            memory_prompt_additions=mem_out.prompt_additions,
        )

    def _evidence_context(self) -> str:
        if not self._all_evidence:
            return ""
        return "\n".join(self._all_evidence)

    async def _run_phase(
        self,
        roles: list[str],
        prompts: dict[str, str],
        parallel: bool = True,
    ) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        evidence_ctx = self._evidence_context()

        if parallel and len(roles) > 1:
            tasks = {
                role: self._make_runner(role).run(
                    prompt=prompts.get(role, self.task_description),
                    evidence_context=evidence_ctx,
                )
                for role in roles
            }
            gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for role, result in zip(tasks.keys(), gathered):
                if isinstance(result, Exception):
                    results[role] = {"role": role, "error": str(result), "evidence": []}
                else:
                    results[role] = result
                    self._all_evidence.extend(result.get("evidence", []))
        else:
            for role in roles:
                runner = self._make_runner(role)
                result = await runner.run(
                    prompt=prompts.get(role, self.task_description),
                    evidence_context=evidence_ctx,
                )
                results[role] = result
                self._all_evidence.extend(result.get("evidence", []))

        return results

    def _build_phases(self) -> list[list[str]]:
        """
        Convert a flat agent_order list into execution phases.
        Phase 1 (parallel): first two agents
        Remaining phases (sequential): one agent each
        Falls back to _DEFAULT_PHASE_ORDER if no order provided.
        """
        if not self.agent_order:
            return _DEFAULT_PHASE_ORDER
        if len(self.agent_order) < 2:
            return [[r] for r in self.agent_order]
        return [self.agent_order[:2]] + [[r] for r in self.agent_order[2:]]

    async def run(self, prompts: dict[str, str]) -> dict[str, Any]:
        """
        Execute the swarm using the routing from memory.
        Phase 1: parallel (first 2 agents per routing)
        Phases 2+: sequential, each receiving accumulated evidence
        """
        phases = self._build_phases()
        all_results: dict[str, dict[str, Any]] = {}

        await self.tracer.record(
            agent="orchestrator",
            event=EventType.SESSION_START,
            artifact=self.task_id,
            result_summary=f"Starting swarm for: {self.task_description[:100]}",
        )

        for i, phase_roles in enumerate(phases):
            parallel = (i == 0 and len(phase_roles) > 1)
            phase_results = await self._run_phase(phase_roles, prompts, parallel=parallel)
            all_results.update(phase_results)

        await self.tracer.record(
            agent="orchestrator",
            event=EventType.SESSION_END,
            artifact=self.task_id,
            result_summary=f"Swarm completed. Agents ran: {list(all_results.keys())}",
        )

        return {
            "task_id": self.task_id,
            "results": all_results,
            "evidence": self._all_evidence,
            "phases_used": phases,
        }
