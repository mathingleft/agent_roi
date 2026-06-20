#!/usr/bin/env bash
# Run the 4 new demo bugs (auth, api, parser, pipeline) — skips calc
# Usage: ANTHROPIC_API_KEY=sk-ant-... ./demo/run_new.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
REPOS="$SCRIPT_DIR/repos"
RESULTS="$SCRIPT_DIR/results"
MEMORY="$SCRIPT_DIR/memory"

mkdir -p "$RESULTS" "$MEMORY"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: ANTHROPIC_API_KEY not set."
  exit 1
fi

AGENTS_SLIM="reproducer,patch_agent,verifier"

run_bug() {
  local name="$1"
  local task="$2"
  local error_type="$3"
  local cwd="$REPOS/$name"
  local mem="$MEMORY/${name}.json"

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  BUG: $name"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  echo "▶ Run 1 (baseline, 5 agents)..."
  python "$SCRIPT_DIR/reset_bugs.py" bug 2>&1 | grep "\[$name\]" || true
  agentroi run "$cwd" \
    --task "$task" \
    --source pytest \
    --error-type "$error_type" \
    --service "$name" \
    --trajectory "${name}_run1" \
    --memory "$mem" \
    --output "$RESULTS" \
    --backend ace \
    2>&1

  echo ""
  echo "▶ Run 2 (memory-loaded, 3 agents)..."
  python "$SCRIPT_DIR/reset_bugs.py" bug 2>&1 | grep "\[$name\]" || true
  agentroi run "$cwd" \
    --task "$task" \
    --source pytest \
    --error-type "$error_type" \
    --service "$name" \
    --trajectory "${name}_run2" \
    --memory "$mem" \
    --output "$RESULTS" \
    --backend ace \
    --agents "$AGENTS_SLIM" \
    2>&1
}

echo "╔══════════════════════════════════════════════════════════╗"
echo "║     AgentROI Demo — 4 New Bugs × 2 Runs                 ║"
echo "╚══════════════════════════════════════════════════════════╝"

run_bug "auth" \
  "validate_age() rejects users who are exactly 18 years old. Stack trace: tests/test_auth.py::test_validate_age_exactly_18 — AssertionError: 18-year-olds should be allowed. Fix: change 'age > 18' to 'age >= 18' in auth.py. Do NOT edit test files." \
  "AssertionError"

run_bug "api" \
  "get_user() returns a coroutine object instead of a dict because it is missing an await. Stack trace: tests/test_api.py::test_get_user_returns_dict — AssertionError: Expected dict, got coroutine. Fix: add 'await' before db.fetch_user() in api.py. Do NOT edit test files." \
  "TypeError"

run_bug "parser" \
  "parse_user() raises KeyError because it reads raw['name'] but the API payload uses 'username' as the key. Stack trace: tests/test_parser.py::test_parse_user_username — KeyError: 'name'. Fix: change raw['name'] to raw['username'] in parser.py. Do NOT edit test files." \
  "KeyError"

run_bug "pipeline" \
  "process_batch() skips the first element because it slices items[1:n] instead of items[0:n]. Stack trace: tests/test_pipeline.py::test_process_batch_includes_first_element — AssertionError: Expected 'hello'. Fix: change items[1:n] to items[0:n] in pipeline.py. Do NOT edit test files." \
  "AssertionError"

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
