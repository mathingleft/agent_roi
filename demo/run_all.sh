#!/usr/bin/env bash
# AgentROI full demo run — 5 bugs × 2 iterations each
# Usage: ANTHROPIC_API_KEY=sk-ant-... ./demo/run_all.sh
#
# Results land in demo/results/  Memory in demo/memory/
# Run the dashboard after: cd dashboard && npm run dev

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
REPOS="$SCRIPT_DIR/repos"
RESULTS="$SCRIPT_DIR/results"
MEMORY="$SCRIPT_DIR/memory"
LOGS="$SCRIPT_DIR/logs"

mkdir -p "$RESULTS" "$MEMORY" "$LOGS"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: ANTHROPIC_API_KEY not set. Export it before running."
  exit 1
fi

AGENTS_SLIM="reproducer,patch_agent,verifier"

# Run one agentroi pass — logs to $LOGS/$name_runN.log
one_run() {
  local name="$1" task="$2" error_type="$3" traj="$4" agents="${5:-}"
  local mem="$MEMORY/${name}.json"
  local log="$LOGS/${name}_${traj}.log"
  local extra=""
  [ -n "$agents" ] && extra="--agents $agents"
  echo "  ▶ [$name] $traj starting..."
  python "$SCRIPT_DIR/reset_bugs.py" bug --only "$name" > /dev/null 2>&1 || true
  agentroi run "$REPOS/$name" \
    --task "$task" \
    --source pytest \
    --error-type "$error_type" \
    --service "$name" \
    --trajectory "$traj" \
    --memory "$mem" \
    --output "$RESULTS" \
    --backend ace \
    $extra \
    > "$log" 2>&1
  echo "  ✓ [$name] $traj done (see logs/${name}_${traj}.log)"
}

# Bug definitions: name|task|error_type
declare -A TASKS ERROR_TYPES
TASKS[calc]="The divide() function returns integer division instead of float. Stack trace: tests/test_calc.py::test_divide_float — AssertionError: Expected 3.5, got 3. Fix: change 'a // b' to 'a / b' in calc.py. Do NOT edit test files."
TASKS[auth]="validate_age() rejects users who are exactly 18 years old. Stack trace: tests/test_auth.py::test_validate_age_exactly_18 — AssertionError: 18-year-olds should be allowed. Fix: change 'age > 18' to 'age >= 18' in auth.py. Do NOT edit test files."
TASKS[api]="get_user() returns a coroutine object instead of a dict because it is missing an await. Stack trace: tests/test_api.py::test_get_user_returns_dict — AssertionError: Expected dict, got coroutine. Fix: add 'await' before db.fetch_user() in api.py. Do NOT edit test files."
TASKS[parser]="parse_user() raises KeyError because it reads raw['name'] but the API payload uses 'username' as the key. Stack trace: tests/test_parser.py::test_parse_user_username — KeyError: 'name'. Fix: change raw['name'] to raw['username'] in parser.py. Do NOT edit test files."
TASKS[pipeline]="process_batch() skips the first element because it slices items[1:n] instead of items[0:n]. Stack trace: tests/test_pipeline.py::test_process_batch_includes_first_element — AssertionError: Expected 'hello'. Fix: change items[1:n] to items[0:n] in pipeline.py. Do NOT edit test files."

ERROR_TYPES[calc]=AssertionError
ERROR_TYPES[auth]=AssertionError
ERROR_TYPES[api]=TypeError
ERROR_TYPES[parser]=KeyError
ERROR_TYPES[pipeline]=AssertionError

BUGS=(calc auth api parser pipeline)

echo "╔══════════════════════════════════════════════════════════╗"
echo "║     AgentROI Demo — 5 Bugs × 2 Runs (parallel)          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo "Results → $RESULTS  |  Logs → $LOGS"
echo ""

# ── Round 1: all 5 bugs baseline, in parallel ──────────────────
echo "━━ Round 1: baseline (5 agents each, all bugs in parallel) ━━"
PIDS=()
for name in "${BUGS[@]}"; do
  one_run "$name" "${TASKS[$name]}" "${ERROR_TYPES[$name]}" "${name}_run1" "" &
  PIDS+=($!)
done
for pid in "${PIDS[@]}"; do wait "$pid" || true; done
echo ""
echo "✓ Round 1 complete."
echo ""

# ── Round 2: all 5 bugs memory-loaded, in parallel ────────────
echo "━━ Round 2: memory-loaded (3 agents each, all bugs in parallel) ━━"
PIDS=()
for name in "${BUGS[@]}"; do
  one_run "$name" "${TASKS[$name]}" "${ERROR_TYPES[$name]}" "${name}_run2" "$AGENTS_SLIM" &
  PIDS+=($!)
done
for pid in "${PIDS[@]}"; do wait "$pid" || true; done
echo ""
echo "✓ Round 2 complete."
echo ""

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  All runs complete. Generating summary...                ║"
echo "╚══════════════════════════════════════════════════════════╝"

python "$SCRIPT_DIR/summarize.py" "$RESULTS"

DASHBOARD_PUBLIC="$REPO_ROOT/dashboard/public/summary.json"
if [ -f "$RESULTS/summary.json" ]; then
  cp "$RESULTS/summary.json" "$DASHBOARD_PUBLIC"
  echo "Dashboard data updated → $DASHBOARD_PUBLIC"
fi
