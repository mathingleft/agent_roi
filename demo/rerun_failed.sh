#!/usr/bin/env bash
# Reruns only the 4 failed trajectories using existing memory files.
# Safe to run after fixing the sandbox path resolution bug.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
HE="$SCRIPT_DIR/humaneval"
RESULTS="$SCRIPT_DIR/results_humaneval"
LOGS="$SCRIPT_DIR/logs_humaneval"
MEMORY="$SCRIPT_DIR/memory"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: ANTHROPIC_API_KEY not set."; exit 1
fi

AGENTS_SLIM="reproducer,patch_agent,verifier"

one_run() {
  local name="$1" traj="$2" mem="$3" agents="${4:-}"
  local repo="$HE/$name"
  local log="$LOGS/${traj}.log"
  local extra=""
  [ -n "$agents" ] && extra="--agents $agents"

  local bug_desc entry_point
  bug_desc=$(python3 -c "import json; d=json.load(open('$repo/meta.json')); print(d['bug_desc'])")
  entry_point=$(python3 -c "import json; d=json.load(open('$repo/meta.json')); print(d['entry_point'])")

  echo "  ▶ [$name] $traj ..."
  python "$HE/reset.py" --only "$name" > /dev/null 2>&1
  agentroi run "$repo" \
    --task "$bug_desc Fix the bug in solution.py. The function is $entry_point(). Do NOT edit test files." \
    --source pytest \
    --error-type "AssertionError" \
    --service "$name" \
    --trajectory "$traj" \
    --memory "$mem" \
    --output "$RESULTS" \
    --backend ace \
    $extra \
    > "$log" 2>&1
  echo "  ✓ [$name] $traj done"
}

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  AgentROI — Rerunning 4 failed trajectories                  ║"
echo "║  (sandbox path fix applied — relative paths now allowed)     ║"
echo "╚══════════════════════════════════════════════════════════════╝"

# t1a_run2: op_get_positive chain A run 2 (uses existing t1a memory)
one_run "op_get_positive" "t1a_run2" "$MEMORY/humaneval_t1a.json" "$AGENTS_SLIM" &
P1=$!

# T3 failures run sequentially to preserve memory chain ordering
(
  # val_incr_list run2 — needs run1 memory already in t3
  one_run "val_incr_list"   "t3_val_incr_run2"  "$MEMORY/humaneval_t3.json" "$AGENTS_SLIM"
  # val_triangle T3 run2
  one_run "val_triangle"    "t3_val_tri_run2"   "$MEMORY/humaneval_t3.json" "$AGENTS_SLIM"
  # var_rolling_max: run1 failed so rerun both to rebuild the memory chain
  one_run "var_rolling_max" "t3_var_roll_run1"  "$MEMORY/humaneval_t3.json"
  one_run "var_rolling_max" "t3_var_roll_run2"  "$MEMORY/humaneval_t3.json" "$AGENTS_SLIM"
) &
P2=$!

wait $P1 $P2

echo ""
echo "Reruns complete. Regenerating summary..."
python "$SCRIPT_DIR/summarize.py" "$RESULTS" --output "$RESULTS/summary_humaneval.json"
cp "$RESULTS/summary_humaneval.json" "$REPO_ROOT/dashboard/public/summary_humaneval.json"
echo "Dashboard updated → $REPO_ROOT/dashboard/public/summary_humaneval.json"
