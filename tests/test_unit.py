"""
Unit tests for AgentROI — no API calls, no claude_code_sdk invocations.

Covers:
- Memory backends (JSON + ACE): store, retrieve, trajectory isolation, dedup, voting, pruning
- Memory consumers: PromptInjector, RoutingDecider, ActionBlocklist, EvidenceSeeder, CompositeConsumer
- MemoryManager facade: retrieve_and_consume, store_roi_results round-trip
- Waste detectors: each detector on synthetic trace data
- ROI formula computation
"""
from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

import pytest

from agentroi.memory_backends import ACEPlaybookBackend, JSONMemoryBackend
from agentroi.memory_consumers import (
    ActionBlocklist,
    CompositeConsumer,
    EvidenceSeeder,
    PromptInjector,
    RoutingDecider,
    default_consumer,
)
from agentroi.memory_protocol import compose_outputs
from agentroi.schemas import (
    AgentRole,
    ConsumerContext,
    ConsumerOutput,
    EventType,
    MemoryEntry,
    MemoryEntryType,
    RetrievalQuery,
    RetrievalStrategy,
    RunMetrics,
    TraceEvent,
    WasteEvent,
    WasteType,
)
from agentroi.memory import MemoryManager, make_memory_manager
from agentroi.waste_detectors import (
    detect_bad_routing,
    detect_duplicate_file_reads,
    detect_premature_full_suite,
    detect_test_edit_cheat,
    run_all_detectors,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SIG = {"source": "pytest", "error_type": "ValueError", "service": "auth"}
_SIG_KEY = "pytest|valueerror|auth"


def _entry(
    entry_type: MemoryEntryType,
    content: str | dict,
    trajectory_id: str = "t1",
    agent_role: str = "",
    helpful: int = 0,
    harmful: int = 0,
) -> MemoryEntry:
    e = MemoryEntry(
        entry_type=entry_type,
        content=content,
        trajectory_id=trajectory_id,
        task_signature_key=_SIG_KEY,
        agent_role=agent_role,
        helpful_count=helpful,
        harmful_count=harmful,
    )
    return e


def _ctx(agent_role: str = "", trajectory_id: str = "t1") -> ConsumerContext:
    return ConsumerContext(
        task_description="Fix the auth ValueError",
        task_signature=_SIG,
        trajectory_id=trajectory_id,
        agent_role=agent_role,
        run_id="run001",
    )


def _event(
    agent: str,
    event: EventType,
    artifact: str = "",
    timestamp: float = 0.0,
    metadata: dict | None = None,
) -> TraceEvent:
    return TraceEvent(
        timestamp=timestamp,
        run_id="run001",
        agent=agent,
        event=event,
        artifact=artifact,
        tokens_est=10,
        result_summary="",
        parent_task="run001",
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# JSON Backend
# ---------------------------------------------------------------------------

class TestJSONMemoryBackend:
    def test_store_and_retrieve(self, tmp_path):
        b = JSONMemoryBackend(tmp_path / "mem.json")
        e = _entry(MemoryEntryType.PROMPT_PATCH, "Do not edit tests", agent_role="patch_agent")
        eid = b.store(e)
        assert eid == e.id

        q = RetrievalQuery(task_signature=_SIG, trajectory_id="t1",
                           entry_types=[MemoryEntryType.PROMPT_PATCH])
        results = b.retrieve(q)
        assert len(results) == 1
        assert results[0].content == "Do not edit tests"

    def test_trajectory_isolation(self, tmp_path):
        b = JSONMemoryBackend(tmp_path / "mem.json")
        b.store(_entry(MemoryEntryType.PROMPT_PATCH, "t1 patch", trajectory_id="t1"))
        b.store(_entry(MemoryEntryType.PROMPT_PATCH, "t2 patch", trajectory_id="t2"))

        q1 = RetrievalQuery(task_signature=_SIG, trajectory_id="t1",
                            entry_types=[MemoryEntryType.PROMPT_PATCH])
        q2 = RetrievalQuery(task_signature=_SIG, trajectory_id="t2",
                            entry_types=[MemoryEntryType.PROMPT_PATCH])
        r1 = b.retrieve(q1)
        r2 = b.retrieve(q2)
        assert len(r1) == 1 and r1[0].content == "t1 patch"
        assert len(r2) == 1 and r2[0].content == "t2 patch"

    def test_vote_and_prune(self, tmp_path):
        b = JSONMemoryBackend(tmp_path / "mem.json")
        e = _entry(MemoryEntryType.WASTE_PATTERN, "bad pattern")
        b.store(e)
        b.vote(e.id, helpful=False)
        b.vote(e.id, helpful=False)
        b.vote(e.id, helpful=False)
        assert b._entries[e.id].net_score == -3
        pruned = b.prune(min_net_score=-2)
        assert pruned == 1
        assert e.id not in b._entries

    def test_update(self, tmp_path):
        b = JSONMemoryBackend(tmp_path / "mem.json")
        e = _entry(MemoryEntryType.HIGH_ROI_CONTEXT, "old content")
        b.store(e)
        b.update(e.id, {"content": "updated content"})
        q = RetrievalQuery(task_signature=_SIG, trajectory_id="t1")
        results = b.retrieve(q)
        assert results[0].content == "updated content"

    def test_persists_to_disk(self, tmp_path):
        p = tmp_path / "mem.json"
        b1 = JSONMemoryBackend(p)
        b1.store(_entry(MemoryEntryType.ROUTING_RULE, {"agent_order": ["a", "b"]}))
        b2 = JSONMemoryBackend(p)
        q = RetrievalQuery(task_signature=_SIG, trajectory_id="t1",
                           entry_types=[MemoryEntryType.ROUTING_RULE])
        results = b2.retrieve(q)
        assert len(results) == 1

    def test_list_trajectories(self, tmp_path):
        b = JSONMemoryBackend(tmp_path / "mem.json")
        b.store(_entry(MemoryEntryType.PROMPT_PATCH, "x", trajectory_id="t1"))
        b.store(_entry(MemoryEntryType.PROMPT_PATCH, "y", trajectory_id="t2"))
        trajs = b.list_trajectories()
        assert set(trajs) == {"t1", "t2"}


# ---------------------------------------------------------------------------
# ACE Playbook Backend
# ---------------------------------------------------------------------------

class TestACEPlaybookBackend:
    def test_store_and_retrieve_routing(self, tmp_path):
        b = ACEPlaybookBackend(tmp_path / "pb.json")
        e = _entry(MemoryEntryType.ROUTING_RULE,
                   {"agent_order": ["log_investigator", "patch_agent"]})
        b.store(e)
        q = RetrievalQuery(task_signature=_SIG, trajectory_id="t1",
                           entry_types=[MemoryEntryType.ROUTING_RULE])
        results = b.retrieve(q)
        assert len(results) == 1
        assert results[0].content["agent_order"][0] == "log_investigator"

    def test_deduplication(self, tmp_path):
        b = ACEPlaybookBackend(tmp_path / "pb.json")
        e1 = _entry(MemoryEntryType.WASTE_PATTERN, "do not run full suite early")
        e2 = _entry(MemoryEntryType.WASTE_PATTERN, "do not run full suite early")
        b.store(e1)
        b.store(e2)
        q = RetrievalQuery(task_signature=_SIG, trajectory_id="t1",
                           entry_types=[MemoryEntryType.WASTE_PATTERN])
        results = b.retrieve(q)
        assert len(results) == 1
        assert results[0].helpful_count >= 1

    def test_trajectory_isolation(self, tmp_path):
        b = ACEPlaybookBackend(tmp_path / "pb.json")
        b.store(_entry(MemoryEntryType.PROMPT_PATCH, "tA secret", trajectory_id="tA"))
        b.store(_entry(MemoryEntryType.PROMPT_PATCH, "tB secret", trajectory_id="tB"))

        qA = RetrievalQuery(task_signature=_SIG, trajectory_id="tA",
                            entry_types=[MemoryEntryType.PROMPT_PATCH])
        qB = RetrievalQuery(task_signature=_SIG, trajectory_id="tB",
                            entry_types=[MemoryEntryType.PROMPT_PATCH])
        assert b.retrieve(qA)[0].content == "tA secret"
        assert b.retrieve(qB)[0].content == "tB secret"

    def test_prompt_patch_per_role(self, tmp_path):
        b = ACEPlaybookBackend(tmp_path / "pb.json")
        b.store(_entry(MemoryEntryType.PROMPT_PATCH, "patch rule", agent_role="patch_agent"))
        b.store(_entry(MemoryEntryType.PROMPT_PATCH, "repro rule", agent_role="reproducer"))

        q_patch = RetrievalQuery(task_signature=_SIG, trajectory_id="t1",
                                 entry_types=[MemoryEntryType.PROMPT_PATCH],
                                 agent_role="patch_agent")
        q_repro = RetrievalQuery(task_signature=_SIG, trajectory_id="t1",
                                 entry_types=[MemoryEntryType.PROMPT_PATCH],
                                 agent_role="reproducer")
        assert len(b.retrieve(q_patch)) == 1
        assert b.retrieve(q_patch)[0].content == "patch rule"
        assert len(b.retrieve(q_repro)) == 1
        assert b.retrieve(q_repro)[0].content == "repro rule"

    def test_global_share(self, tmp_path):
        b = ACEPlaybookBackend(tmp_path / "pb.json", share_global=True)
        b.store(_entry(MemoryEntryType.WASTE_PATTERN, "shared waste", trajectory_id="tA"))
        assert "waste_patterns" in b._data.get("global_playbook", {})
        global_entries = b._data["global_playbook"]["waste_patterns"]
        assert any(e["content"] == "shared waste" for e in global_entries)

    def test_prune(self, tmp_path):
        b = ACEPlaybookBackend(tmp_path / "pb.json")
        e = _entry(MemoryEntryType.WASTE_PATTERN, "bad one", harmful=5)
        b.store(e)
        pruned = b.prune(min_net_score=-2)
        assert pruned == 1
        q = RetrievalQuery(task_signature=_SIG, trajectory_id="t1")
        assert b.retrieve(q) == []

    def test_create_trajectory_metadata(self, tmp_path):
        b = ACEPlaybookBackend(tmp_path / "pb.json")
        b.create_trajectory("exp1", "my experiment")
        meta = b.get_trajectory_meta("exp1")
        assert meta["description"] == "my experiment"
        assert meta["entry_count"] == 0

    def test_snapshot(self, tmp_path):
        b = ACEPlaybookBackend(tmp_path / "pb.json")
        b.store(_entry(MemoryEntryType.PROMPT_PATCH, "p1"))
        b.store(_entry(MemoryEntryType.WASTE_PATTERN, "w1"))
        snap = b.snapshot("t1")
        assert len(snap) == 2


# ---------------------------------------------------------------------------
# Memory Consumers
# ---------------------------------------------------------------------------

class TestPromptInjector:
    def test_injects_patches_and_waste(self):
        inj = PromptInjector()
        entries = [
            _entry(MemoryEntryType.PROMPT_PATCH, "no test edits", agent_role="patch_agent"),
            _entry(MemoryEntryType.WASTE_PATTERN, "duplicate reads"),
        ]
        out = inj.consume(entries, _ctx("patch_agent"))
        assert "no test edits" in out.prompt_additions
        assert "duplicate reads" in out.prompt_additions
        assert "LEARNED INSTRUCTIONS" in out.prompt_additions
        assert "WASTE PATTERNS" in out.prompt_additions

    def test_role_filter(self):
        inj = PromptInjector()
        entries = [
            _entry(MemoryEntryType.PROMPT_PATCH, "for patch", agent_role="patch_agent"),
            _entry(MemoryEntryType.PROMPT_PATCH, "for repro", agent_role="reproducer"),
        ]
        out = inj.consume(entries, _ctx("patch_agent"))
        assert "for patch" in out.prompt_additions
        assert "for repro" not in out.prompt_additions

    def test_no_entries_returns_empty(self):
        inj = PromptInjector()
        out = inj.consume([], _ctx())
        assert out.prompt_additions == ""


class TestRoutingDecider:
    def test_uses_best_routing_rule(self):
        rd = RoutingDecider()
        entries = [
            _entry(MemoryEntryType.ROUTING_RULE,
                   {"agent_order": ["log_investigator", "patch_agent"]},
                   helpful=3),
            _entry(MemoryEntryType.ROUTING_RULE,
                   {"agent_order": ["reproducer", "verifier"]},
                   helpful=1),
        ]
        out = rd.consume(entries, _ctx())
        assert out.agent_order[0] == "log_investigator"

    def test_default_when_no_rules(self):
        rd = RoutingDecider()
        out = rd.consume([], _ctx())
        assert "log_investigator" in out.agent_order
        assert len(out.agent_order) == 5

    def test_raw_contains_routing_meta(self):
        rd = RoutingDecider()
        entries = [
            _entry(MemoryEntryType.ROUTING_RULE,
                   {"agent_order": ["a", "b"], "patch_agent_start_condition": "repro_confirmed"})
        ]
        out = rd.consume(entries, _ctx())
        assert out.raw.get("patch_agent_start_condition") == "repro_confirmed"


class TestActionBlocklist:
    def test_default_blocks_for_patch_agent(self):
        bl = ActionBlocklist()
        out = bl.consume([], _ctx("patch_agent"))
        assert "edit_test_files" in out.blocked_tools

    def test_default_blocks_file_edit_for_log_investigator(self):
        bl = ActionBlocklist()
        out = bl.consume([], _ctx("log_investigator"))
        assert "file_edit" in out.blocked_tools

    def test_learned_blocked_action(self):
        bl = ActionBlocklist()
        e = _entry(MemoryEntryType.PROMPT_PATCH, "block Bash",
                   agent_role="patch_agent")
        e.metadata = {"blocked": True, "blocked_action": "Bash"}
        out = bl.consume([e], _ctx("patch_agent"))
        assert "Bash" in out.blocked_tools


class TestEvidenceSeeder:
    def test_injects_high_roi_context(self):
        es = EvidenceSeeder()
        entries = [
            _entry(MemoryEntryType.HIGH_ROI_CONTEXT, "always check auth middleware first"),
            _entry(MemoryEntryType.HIGH_ROI_CONTEXT, "top stack frame is always signal"),
        ]
        out = es.consume(entries, _ctx())
        assert "auth middleware" in out.evidence_context
        assert "HIGH-SIGNAL CONTEXT" in out.evidence_context

    def test_injects_episodic_record(self):
        es = EvidenceSeeder()
        entries = [
            _entry(MemoryEntryType.EPISODIC_RECORD, {
                "run_id": "run001",
                "roi_score": 0.85,
                "retrospective_snippet": "Minimal patch, fast resolve",
            }),
        ]
        out = es.consume(entries, _ctx())
        assert "0.85" in out.evidence_context
        assert "Minimal patch" in out.evidence_context

    def test_no_entries_returns_empty(self):
        es = EvidenceSeeder()
        out = es.consume([], _ctx())
        assert out.evidence_context == ""


class TestCompositeConsumer:
    def test_all_consumers_fire(self):
        cc = default_consumer()
        entries = [
            _entry(MemoryEntryType.PROMPT_PATCH, "learned rule", agent_role="patch_agent"),
            _entry(MemoryEntryType.ROUTING_RULE, {"agent_order": ["log_investigator", "patch_agent"]}),
            _entry(MemoryEntryType.HIGH_ROI_CONTEXT, "check middleware"),
            _entry(MemoryEntryType.WASTE_PATTERN, "full suite too early"),
        ]
        out = cc.consume(entries, _ctx("patch_agent"))
        assert "learned rule" in out.prompt_additions
        assert out.agent_order[0] == "log_investigator"
        assert "edit_test_files" in out.blocked_tools
        assert "middleware" in out.evidence_context

    def test_compose_outputs_merges(self):
        o1 = ConsumerOutput(prompt_additions="A", agent_order=["x"], blocked_tools={"t1"})
        o2 = ConsumerOutput(prompt_additions="B", blocked_tools={"t2"}, evidence_context="E")
        merged = compose_outputs(o1, o2)
        assert "A" in merged.prompt_additions and "B" in merged.prompt_additions
        assert merged.agent_order == ["x"]
        assert {"t1", "t2"} <= merged.blocked_tools
        assert merged.evidence_context == "E"


# ---------------------------------------------------------------------------
# MemoryManager facade
# ---------------------------------------------------------------------------

class TestMemoryManager:
    def _make(self, tmp_path, backend="ace") -> MemoryManager:
        return make_memory_manager(tmp_path / "mem.json", backend=backend)

    def test_store_roi_results_round_trip(self, tmp_path):
        mgr = self._make(tmp_path)
        report = {
            "run_id": "run001",
            "composite_roi_score": 0.75,
            "prompt_patches": {"patch_agent": ["no test edits"]},
            "routing_update": {"agent_order": ["log_investigator", "patch_agent"]},
            "waste_events": [{"description": "dup read", "waste_type": "duplicate_file_read", "severity": "medium"}],
            "judge_verdict": {"key_insight": "check middleware first"},
            "metrics": {"wall_time_sec": 30, "tokens_total": 800, "target_test_passed": True},
            "retrospective": "Good run.",
        }
        mgr.store_roi_results(task_signature=_SIG, trajectory_id="t1", roi_report_dict=report)

        out = mgr.retrieve_and_consume(
            task_signature=_SIG,
            trajectory_id="t1",
            agent_role="patch_agent",
            task_description="Fix auth",
        )
        assert "no test edits" in out.prompt_additions
        assert "dup read" in out.prompt_additions
        assert out.agent_order == ["log_investigator", "patch_agent"]
        assert "middleware" in out.evidence_context

    def test_json_backend_round_trip(self, tmp_path):
        mgr = self._make(tmp_path, backend="json")
        report = {
            "run_id": "r1",
            "composite_roi_score": 0.5,
            "prompt_patches": {"reproducer": ["run target test first"]},
            "routing_update": {},
            "waste_events": [],
            "judge_verdict": {"key_insight": ""},
            "metrics": {"wall_time_sec": 10, "tokens_total": 200, "target_test_passed": False},
            "retrospective": "",
        }
        mgr.store_roi_results(task_signature=_SIG, trajectory_id="t1", roi_report_dict=report)
        out = mgr.retrieve_and_consume(
            task_signature=_SIG, trajectory_id="t1", agent_role="reproducer",
            task_description="Fix auth",
        )
        assert "run target test first" in out.prompt_additions

    def test_trajectory_isolation_across_runs(self, tmp_path):
        mgr = self._make(tmp_path)
        mgr.create_trajectory("exp_A", "experiment A")
        mgr.create_trajectory("exp_B", "experiment B")

        report_a = {
            "run_id": "rA", "composite_roi_score": 0.8,
            "prompt_patches": {"patch_agent": ["A instruction"]},
            "routing_update": {}, "waste_events": [],
            "judge_verdict": {"key_insight": ""},
            "metrics": {"wall_time_sec": 5, "tokens_total": 100, "target_test_passed": True},
            "retrospective": "",
        }
        report_b = {
            "run_id": "rB", "composite_roi_score": 0.4,
            "prompt_patches": {"patch_agent": ["B instruction"]},
            "routing_update": {}, "waste_events": [],
            "judge_verdict": {"key_insight": ""},
            "metrics": {"wall_time_sec": 5, "tokens_total": 100, "target_test_passed": False},
            "retrospective": "",
        }
        mgr.store_roi_results(_SIG, "exp_A", report_a)
        mgr.store_roi_results(_SIG, "exp_B", report_b)

        out_a = mgr.retrieve_and_consume(_SIG, "exp_A", agent_role="patch_agent", task_description="x")
        out_b = mgr.retrieve_and_consume(_SIG, "exp_B", agent_role="patch_agent", task_description="x")

        assert "A instruction" in out_a.prompt_additions
        assert "B instruction" not in out_a.prompt_additions
        assert "B instruction" in out_b.prompt_additions
        assert "A instruction" not in out_b.prompt_additions

    def test_list_and_snapshot(self, tmp_path):
        mgr = self._make(tmp_path)
        mgr.create_trajectory("t1")
        mgr.store_roi_results(_SIG, "t1", {
            "run_id": "r1", "composite_roi_score": 0.6,
            "prompt_patches": {}, "routing_update": {}, "waste_events": [],
            "judge_verdict": {"key_insight": "abc"},
            "metrics": {"wall_time_sec": 1, "tokens_total": 50, "target_test_passed": True},
            "retrospective": "ok",
        })
        assert "t1" in mgr.list_trajectories()
        snap = mgr.snapshot("t1")
        assert len(snap) >= 1

    def test_prune_via_manager(self, tmp_path):
        mgr = self._make(tmp_path)
        e = MemoryEntry(
            entry_type=MemoryEntryType.WASTE_PATTERN,
            content="bad",
            trajectory_id="t1",
            task_signature_key=_SIG_KEY,
            harmful_count=10,
        )
        mgr.backend.store(e)
        pruned = mgr.prune(trajectory_id="t1", min_net_score=-2)
        assert pruned == 1


# ---------------------------------------------------------------------------
# Waste Detectors
# ---------------------------------------------------------------------------

class TestWasteDetectors:
    def test_duplicate_file_reads(self):
        events = [
            _event("log_investigator", EventType.FILE_READ, "src/auth.py", 1.0),
            _event("code_investigator", EventType.FILE_READ, "src/auth.py", 2.0),
        ]
        waste = detect_duplicate_file_reads(events)
        assert len(waste) == 1
        assert waste[0].waste_type == WasteType.DUPLICATE_FILE_READ
        assert "log_investigator" in waste[0].agents_involved
        assert "code_investigator" in waste[0].agents_involved

    def test_no_duplicate_single_agent(self):
        events = [
            _event("log_investigator", EventType.FILE_READ, "src/auth.py", 1.0),
            _event("log_investigator", EventType.FILE_READ, "src/auth.py", 1.5),
        ]
        waste = detect_duplicate_file_reads(events)
        assert waste == []

    def test_premature_full_suite(self):
        events = [
            _event("reproducer", EventType.TEST_RUN, "pytest tests/", 5.0,
                   {"test_scope": "full_suite"}),
        ]
        waste = detect_premature_full_suite(events)
        assert len(waste) == 1
        assert waste[0].waste_type == WasteType.PREMATURE_FULL_SUITE

    def test_no_premature_after_target_pass(self):
        events = [
            _event("reproducer", EventType.TEST_RUN, "pytest tests/test_auth.py::test_login",
                   3.0, {"test_scope": "target", "passed": True}),
            _event("patch_agent", EventType.TEST_RUN, "pytest tests/", 10.0,
                   {"test_scope": "full_suite"}),
        ]
        waste = detect_premature_full_suite(events)
        assert waste == []

    def test_test_edit_cheat(self):
        events = [
            _event("patch_agent", EventType.FILE_EDIT, "tests/test_auth.py", 5.0),
        ]
        waste = detect_test_edit_cheat(events)
        assert len(waste) == 1
        assert waste[0].waste_type == WasteType.TEST_EDIT_CHEAT

    def test_no_test_edit_cheat_for_verifier(self):
        events = [
            _event("verifier", EventType.FILE_EDIT, "tests/test_auth.py", 5.0),
        ]
        waste = detect_test_edit_cheat(events)
        assert waste == []

    def test_bad_routing(self):
        # patch_agent AGENT_START with no prior reproducer EVIDENCE_PUBLISH with 'repro' artifact
        events = [
            _event("patch_agent", EventType.AGENT_START, "task001", 1.0),
        ]
        waste = detect_bad_routing(events)
        assert len(waste) == 1
        assert waste[0].waste_type == WasteType.BAD_ROUTING

    def test_run_all_returns_list(self):
        events = [
            _event("log_investigator", EventType.FILE_READ, "src/auth.py", 0.5),
            _event("code_investigator", EventType.FILE_READ, "src/auth.py", 1.5),
            _event("patch_agent", EventType.FILE_EDIT, "tests/test_auth.py", 5.0),
        ]
        waste = run_all_detectors(events, _SIG)
        types = {w.waste_type for w in waste}
        assert WasteType.DUPLICATE_FILE_READ in types
        assert WasteType.TEST_EDIT_CHEAT in types


# ---------------------------------------------------------------------------
# ROI formula (deterministic, no LLM)
# ---------------------------------------------------------------------------

class TestROIFormula:
    def _metrics(self, **overrides) -> RunMetrics:
        base = RunMetrics(
            run_id="r1",
            wall_time_sec=60.0,
            tokens_total=1000,
            file_reads=10,
            duplicate_file_reads=0,
            test_runs=3,
            file_edits=2,
            bash_commands=5,
            evidence_published=3,
            blocked_actions=0,
            target_test_passed=True,
            full_suite_passed=True,
            patch_diff_lines=8,
            test_files_edited=False,
        )
        for k, v in overrides.items():
            setattr(base, k, v)
        return base

    def test_formula_imports_and_runs(self):
        from agentroi.roi_analyzer import _compute_formula_roi
        m = self._metrics()
        score = _compute_formula_roi(m, [])
        # formula is success/cost ratio — not bounded to [0,1]; positive for passing runs
        assert score > 0.0
        assert isinstance(score, float)

    def test_formula_penalizes_failure(self):
        from agentroi.roi_analyzer import _compute_formula_roi
        m_pass = self._metrics(target_test_passed=True)
        m_fail = self._metrics(target_test_passed=False, full_suite_passed=False)
        assert _compute_formula_roi(m_pass, []) > _compute_formula_roi(m_fail, [])

    def test_formula_penalizes_waste(self):
        from agentroi.roi_analyzer import _compute_formula_roi
        m = self._metrics()
        # only 'critical' severity waste deducts from success score
        waste_critical = [
            WasteEvent(
                waste_type=WasteType.DUPLICATE_FILE_READ,
                description="dup",
                agents_involved=["a"],
                timestamp_start=0.0,
                timestamp_end=1.0,
                estimated_cost=100,
                severity="critical",
            )
        ] * 5
        score_no_waste = _compute_formula_roi(m, [])
        score_with_waste = _compute_formula_roi(m, waste_critical)
        assert score_no_waste > score_with_waste

    def test_formula_test_edit_cheat_penalizes(self):
        from agentroi.roi_analyzer import _compute_formula_roi
        # test_files_edited=True deducts 50 from success
        m_clean = self._metrics(test_files_edited=False)
        m_cheat = self._metrics(test_files_edited=True)
        assert _compute_formula_roi(m_clean, []) > _compute_formula_roi(m_cheat, [])
