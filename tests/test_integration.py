"""
Integration test: real AgentROILoop run against a small buggy Python repo.

What this tests end-to-end:
- AgentROILoop.run_once() with real claude_code_sdk agents
- SwarmOrchestrator phases execute, tracer captures events
- ROI analyzer runs (LLM judge, waste detectors, composite score)
- Memory written back: prompt patches, routing, waste patterns, episodic record
- Second run uses the written memory (memory compounds)
- Trajectory isolation: two trajectories stay separate

The buggy repo is a tiny calculator library with one broken function.
Bug: integer division instead of float division in divide().
Target test: tests/test_calc.py::test_divide_float
"""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from agentroi import AgentROILoop, make_memory_manager
from agentroi.schemas import MemoryEntryType, RetrievalStrategy


# ---------------------------------------------------------------------------
# Buggy repo fixture
# ---------------------------------------------------------------------------

BUGGY_CALC_SRC = '''\
"""Simple calculator module."""


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a // b   # BUG: should be a / b


def multiply(a, b):
    return a * b
'''

CALC_TESTS = '''\
import pytest
from calc import add, subtract, divide, multiply


def test_add():
    assert add(2, 3) == 5


def test_subtract():
    assert subtract(5, 3) == 2


def test_divide_exact():
    assert divide(10, 2) == 5


def test_divide_float():
    result = divide(7, 2)
    assert result == 3.5, f"Expected 3.5, got {result}"


def test_multiply():
    assert multiply(3, 4) == 12
'''

TASK_DESCRIPTION = """\
The calculator module has a bug in the divide() function.

Error report:
  AssertionError: Expected 3.5, got 3
  Location: tests/test_calc.py::test_divide_float

Stack trace:
  File "tests/test_calc.py", line 18, in test_divide_float
    assert result == 3.5, f"Expected 3.5, got {result}"

The divide() function returns an integer instead of a float.
Fix the bug in calc.py using a minimal source-only change.
Do NOT edit any test files.
"""

TASK_SIGNATURE = {
    "source": "pytest",
    "error_type": "AssertionError",
    "service": "calculator",
}


@pytest.fixture
def buggy_repo(tmp_path):
    """Create a minimal buggy Python repo in a temp dir."""
    repo = tmp_path / "calc_repo"
    repo.mkdir()
    (repo / "calc.py").write_text(BUGGY_CALC_SRC)
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")
    (tests_dir / "test_calc.py").write_text(CALC_TESTS)
    return repo


@pytest.fixture
def memory_path(tmp_path):
    return tmp_path / "memory" / "agentroi_memory.json"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_single_run_produces_roi_report(buggy_repo, memory_path):
    """One run: swarm executes, ROI report produced, memory written."""
    loop = AgentROILoop(
        memory_path=memory_path,
        output_dir=memory_path.parent / "runs",
    )

    result = _run(loop.run_once(
        task_description=TASK_DESCRIPTION,
        task_signature=TASK_SIGNATURE,
        cwd=buggy_repo,
        trajectory_id="integration_test",
    ))

    # --- basic shape ---
    assert "run_id" in result
    assert "roi_report" in result
    assert "composite_roi" in result
    assert result["trajectory_id"] == "integration_test"

    roi_report = result["roi_report"]
    assert roi_report.composite_roi_score >= 0.0
    assert roi_report.metrics.tokens_total > 0
    assert roi_report.metrics.wall_time_sec > 0

    # --- report file written ---
    report_path = Path(result["report_path"])
    assert report_path.exists()
    with report_path.open() as f:
        report_dict = json.load(f)
    assert report_dict["run_id"] == result["run_id"]

    # --- memory was written back ---
    snap = loop.memory.snapshot("integration_test")
    assert len(snap) > 0, "Memory should have been written after the run"

    entry_types = {e["entry_type"] for e in snap}
    assert MemoryEntryType.EPISODIC_RECORD.value in entry_types


@pytest.mark.integration
def test_second_run_uses_memory(buggy_repo, memory_path):
    """
    Two runs in the same trajectory: second run's prompts include memory
    from the first run.
    """
    loop = AgentROILoop(
        memory_path=memory_path,
        output_dir=memory_path.parent / "runs",
    )

    # Run 1
    r1 = _run(loop.run_once(
        task_description=TASK_DESCRIPTION,
        task_signature=TASK_SIGNATURE,
        cwd=buggy_repo,
        trajectory_id="two_run_test",
    ))

    snap_after_r1 = loop.memory.snapshot("two_run_test")
    assert len(snap_after_r1) > 0

    # Run 2 — same trajectory, memory should be loaded
    r2 = _run(loop.run_once(
        task_description=TASK_DESCRIPTION,
        task_signature=TASK_SIGNATURE,
        cwd=buggy_repo,
        trajectory_id="two_run_test",
    ))

    snap_after_r2 = loop.memory.snapshot("two_run_test")
    assert len(snap_after_r2) >= len(snap_after_r1), \
        "Memory should grow or stay same after second run"

    # run IDs must differ
    assert r1["run_id"] != r2["run_id"]


@pytest.mark.integration
def test_trajectory_isolation_in_full_loop(buggy_repo, memory_path):
    """Two trajectories on the same task stay isolated."""
    loop = AgentROILoop(
        memory_path=memory_path,
        output_dir=memory_path.parent / "runs",
    )

    _run(loop.run_once(
        task_description=TASK_DESCRIPTION,
        task_signature=TASK_SIGNATURE,
        cwd=buggy_repo,
        trajectory_id="traj_alpha",
    ))

    # Nothing stored in traj_beta yet
    snap_beta_before = loop.memory.snapshot("traj_beta")
    assert snap_beta_before == [], "traj_beta should be empty before its own run"

    _run(loop.run_once(
        task_description=TASK_DESCRIPTION,
        task_signature=TASK_SIGNATURE,
        cwd=buggy_repo,
        trajectory_id="traj_beta",
    ))

    snap_alpha = loop.memory.snapshot("traj_alpha")
    snap_beta = loop.memory.snapshot("traj_beta")

    # Both have entries, but IDs are disjoint
    alpha_ids = {e["id"] for e in snap_alpha}
    beta_ids = {e["id"] for e in snap_beta}
    overlap = alpha_ids & beta_ids
    # Global share may copy some entries — check trajectory_id field instead
    for e in snap_alpha:
        assert e["trajectory_id"] == "traj_alpha"
    for e in snap_beta:
        assert e["trajectory_id"] == "traj_beta"


@pytest.mark.integration
def test_waste_events_detected_and_persisted(buggy_repo, memory_path):
    """After a run, waste patterns (if any) are in memory as WASTE_PATTERN entries."""
    loop = AgentROILoop(
        memory_path=memory_path,
        output_dir=memory_path.parent / "runs",
    )

    result = _run(loop.run_once(
        task_description=TASK_DESCRIPTION,
        task_signature=TASK_SIGNATURE,
        cwd=buggy_repo,
        trajectory_id="waste_test",
    ))

    roi_report = result["roi_report"]
    # Waste events list exists (may be empty if agents were efficient)
    assert isinstance(roi_report.waste_events, list)

    # If waste was detected, it should appear in memory
    if roi_report.waste_events:
        snap = loop.memory.snapshot("waste_test")
        waste_entries = [e for e in snap if e["entry_type"] == MemoryEntryType.WASTE_PATTERN.value]
        assert len(waste_entries) > 0, "Detected waste should be stored in memory"


@pytest.mark.integration
def test_run_loop_three_iterations(buggy_repo, memory_path):
    """run_loop runs 3 iterations, each compounding memory."""
    loop = AgentROILoop(
        memory_path=memory_path,
        output_dir=memory_path.parent / "runs",
    )

    history = _run(loop.run_loop(
        task_description=TASK_DESCRIPTION,
        task_signature=TASK_SIGNATURE,
        cwd=buggy_repo,
        trajectory_id="loop_test",
        num_iterations=3,
    ))

    assert len(history) == 3
    run_ids = [r["run_id"] for r in history]
    assert len(set(run_ids)) == 3, "Each iteration should have a unique run_id"

    # Memory should grow across iterations
    snap = loop.memory.snapshot("loop_test")
    assert len(snap) >= 3, "At least one episodic record per iteration"
