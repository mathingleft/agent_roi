#!/usr/bin/env bash
# AgentROI full demo run — 5 bugs × 2 iterations each
# Usage: ANTHROPIC_API_KEY=sk-ant-... ./demo/run_all.sh
#
# Results land in demo/results/  Memory in demo/memory/
# Run the dashboard after: cd dashboard && npm run dev

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
REPOS="$SCRIPT_DIR/repos"
RESULTS="$SCRIPT_DIR/results"
MEMORY="$SCRIPT_DIR/memory"

mkdir -p "$RESULTS" "$MEMORY"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: ANTHROPIC_API_KEY not set. Export it before running."
  exit 1
fi

# Agent subset for run 2 (cheaper, 3 agents only)
AGENTS_SLIM="reproducer,patch_agent,verifier"

run_bug() {
  local name="$1"
  local task="$2"
  local error_type="$3"
  local trajectory="$4"
  local cwd="$REPOS/$name"

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  BUG: $name  |  TRAJECTORY: $trajectory"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  local mem="$MEMORY/${name}.json"

  # --- Run 1: baseline, all 5 agents, fresh memory ---
  echo ""
  echo "▶ Run 1 (baseline, 5 agents)..."
  python "$SCRIPT_DIR/reset_bugs.py" bug 2>&1 | grep "\\[$name\\]" || true
  agentroi run "$cwd" \
    --task "$task" \
    --source pytest \
    --error-type "$error_type" \
    --service "$name" \
    --trajectory "${trajectory}_run1" \
    --memory "$mem" \
    --output "$RESULTS" \
    --backend ace \
    2>&1

  # --- Run 2: memory-loaded, 3 agents ---
  echo ""
  echo "▶ Run 2 (memory-loaded, 3 agents)..."
  python "$SCRIPT_DIR/reset_bugs.py" bug 2>&1 | grep "\\[$name\\]" || true
  agentroi run "$cwd" \
    --task "$task" \
    --source pytest \
    --error-type "$error_type" \
    --service "$name" \
    --trajectory "${trajectory}_run2" \
    --memory "$mem" \
    --output "$RESULTS" \
    --backend ace \
    --agents "$AGENTS_SLIM" \
    2>&1
}

echo "╔══════════════════════════════════════════════════════════╗"
echo "║           AgentROI Demo — 5 Bugs × 2 Runs               ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo "Results → $RESULTS"
echo "Memory  → $MEMORY"

run_bug "calc" \
  "The divide() function returns integer division instead of float. Stack trace: tests/test_calc.py::test_divide_float — AssertionError: Expected 3.5, got 3. Fix: change 'a // b' to 'a / b' in calc.py. Do NOT edit test files." \
  "AssertionError" \
  "calc"

run_bug "auth" \
  "validate_age() rejects users who are exactly 18 years old. Stack trace: tests/test_auth.py::test_validate_age_exactly_18 — AssertionError: 18-year-olds should be allowed. Fix: change 'age > 18' to 'age >= 18' in auth.py. Do NOT edit test files." \
  "AssertionError" \
  "auth"

run_bug "api" \
  "get_user() returns a coroutine object instead of a dict because it is missing an await. Stack trace: tests/test_api.py::test_get_user_returns_dict — AssertionError: Expected dict, got coroutine. Fix: add 'await' before db.fetch_user() in api.py. Do NOT edit test files." \
  "TypeError" \
  "api"

run_bug "parser" \
  "parse_user() raises KeyError because it reads raw['name'] but the API payload uses 'username' as the key. Stack trace: tests/test_parser.py::test_parse_user_username — KeyError: 'name'. Fix: change raw['name'] to raw['username'] in parser.py. Do NOT edit test files." \
  "KeyError" \
  "parser"

run_bug "pipeline" \
  "process_batch() skips the first element because it slices items[1:n] instead of items[0:n]. Stack trace: tests/test_pipeline.py::test_process_batch_includes_first_element — AssertionError: Expected 'hello'. Fix: change items[1:n] to items[0:n] in pipeline.py. Do NOT edit test files." \
  "AssertionError" \
  "pipeline"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  All runs complete. Generating summary...                ║"
echo "╚══════════════════════════════════════════════════════════╝"

python "$SCRIPT_DIR/summarize.py" "$RESULTS"

# Copy summary.json to dashboard so it refreshes on next page load
DASHBOARD_PUBLIC="$REPO_ROOT/dashboard/public/summary.json"
if [ -f "$RESULTS/summary.json" ]; then
  cp "$RESULTS/summary.json" "$DASHBOARD_PUBLIC"
  echo "Dashboard data updated → $DASHBOARD_PUBLIC"
  echo "Rebuilding dashboard..."
  bash "$REPO_ROOT/dashboard/start.sh" &
  sleep 4
  echo "Dashboard live at http://localhost:5174"
fi
