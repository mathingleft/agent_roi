#!/usr/bin/env bash
# AgentROI — HumanEvalFix 3-tier generalization experiment
#
# TIER 1: Same-bug repeat  — op_get_positive × 3, own memory
# TIER 2: Same-domain      — operator misuse chain (op_get_positive→op_rescale→op_solve→op_fizzbuzz), own memory
# TIER 3: Cross-domain     — value misuse then variable misuse (incl. harder var_rolling_max), own memory
#
# All 3 tiers run IN PARALLEL (separate memory files = no race conditions).
# Within each tier the runs are sequential (memory must accumulate).
#
# Usage: ANTHROPIC_API_KEY=sk-ant-... ./demo/run_humaneval.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
HE="$SCRIPT_DIR/humaneval"
RESULTS="$SCRIPT_DIR/results_humaneval"
LOGS="$SCRIPT_DIR/logs_humaneval"
MEMORY="$SCRIPT_DIR/memory"

mkdir -p "$RESULTS" "$LOGS" "$MEMORY"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: ANTHROPIC_API_KEY not set."
  exit 1
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

# ── Tier functions (each runs sequentially internally) ──────────────

tier1() {
  # 3 problems each repeated 3 times — chains run in parallel, each has own sub-memory
  # Shows: memory compounds on identical reruns regardless of problem type
  local mem_a="$MEMORY/humaneval_t1a.json"
  local mem_b="$MEMORY/humaneval_t1b.json"
  local mem_c="$MEMORY/humaneval_t1c.json"
  echo "━━ TIER 1: Same-bug repeat (3 problems × 3 runs, parallel chains) ━━"

  ( one_run "op_get_positive" "t1a_run1" "$mem_a"
    one_run "op_get_positive" "t1a_run2" "$mem_a" "$AGENTS_SLIM"
    one_run "op_get_positive" "t1a_run3" "$mem_a" "$AGENTS_SLIM" ) &
  ( one_run "val_triangle"    "t1b_run1" "$mem_b"
    one_run "val_triangle"    "t1b_run2" "$mem_b" "$AGENTS_SLIM"
    one_run "val_triangle"    "t1b_run3" "$mem_b" "$AGENTS_SLIM" ) &
  ( one_run "var_gcd"         "t1c_run1" "$mem_c"
    one_run "var_gcd"         "t1c_run2" "$mem_c" "$AGENTS_SLIM"
    one_run "var_gcd"         "t1c_run3" "$mem_c" "$AGENTS_SLIM" ) &
  wait
  echo "✓ Tier 1 done"
}

tier2() {
  local mem="$MEMORY/humaneval_t2.json"
  echo "━━ TIER 2: Same-domain (4 operator misuse bugs, sequential) ━━"
  # Progressive: each bug benefits more from memory as domain knowledge accumulates
  one_run "op_get_positive" "t2_op_getpos_run1"  "$mem"
  one_run "op_get_positive" "t2_op_getpos_run2"  "$mem" "$AGENTS_SLIM"
  one_run "op_rescale"      "t2_op_rescale_run1" "$mem"
  one_run "op_rescale"      "t2_op_rescale_run2" "$mem" "$AGENTS_SLIM"
  one_run "op_solve"        "t2_op_solve_run1"   "$mem"
  one_run "op_solve"        "t2_op_solve_run2"   "$mem" "$AGENTS_SLIM"
  one_run "op_fizzbuzz"     "t2_op_fizz_run1"    "$mem"
  one_run "op_fizzbuzz"     "t2_op_fizz_run2"    "$mem" "$AGENTS_SLIM"
  echo "✓ Tier 2 done"
}

tier3() {
  local mem="$MEMORY/humaneval_t3.json"
  echo "━━ TIER 3: Cross-domain (value misuse → variable misuse) ━━"
  # value misuse group
  one_run "val_incr_list"   "t3_val_incr_run1"   "$mem"
  one_run "val_incr_list"   "t3_val_incr_run2"   "$mem" "$AGENTS_SLIM"
  one_run "val_triangle"    "t3_val_tri_run1"     "$mem"
  one_run "val_triangle"    "t3_val_tri_run2"     "$mem" "$AGENTS_SLIM"
  # variable misuse group — memory from value bugs should generalize
  one_run "var_gcd"         "t3_var_gcd_run1"     "$mem"
  one_run "var_gcd"         "t3_var_gcd_run2"     "$mem" "$AGENTS_SLIM"
  one_run "var_rolling_max" "t3_var_roll_run1"    "$mem"   # harder: max(numbers)→max(running_max,n)
  one_run "var_rolling_max" "t3_var_roll_run2"    "$mem" "$AGENTS_SLIM"
  echo "✓ Tier 3 done"
}

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   AgentROI — HumanEvalFix Generalization Experiment         ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Tier 1: Same-bug repeat   op_get_positive × 3              ║"
echo "║  Tier 2: Same-domain       operator misuse × 3 bugs         ║"
echo "║  Tier 3: Cross-domain      value→variable misuse × 4 bugs   ║"
echo "║  All tiers run IN PARALLEL (separate memory files)          ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo "Results → $RESULTS  |  Logs → $LOGS"
echo ""

# Launch all 3 tiers in parallel
tier1 > "$LOGS/tier1.log" 2>&1 &
PID1=$!
tier2 > "$LOGS/tier2.log" 2>&1 &
PID2=$!
tier3 > "$LOGS/tier3.log" 2>&1 &
PID3=$!

# Progress monitor
while kill -0 $PID1 2>/dev/null || kill -0 $PID2 2>/dev/null || kill -0 $PID3 2>/dev/null; do
  T1_DONE=$(kill -0 $PID1 2>/dev/null && echo "running" || echo "done")
  T2_DONE=$(kill -0 $PID2 2>/dev/null && echo "running" || echo "done")
  T3_DONE=$(kill -0 $PID3 2>/dev/null && echo "running" || echo "done")
  NRESULTS=$(ls "$RESULTS"/*_roi_report.json 2>/dev/null | wc -l)
  echo "  [T1=$T1_DONE T2=$T2_DONE T3=$T3_DONE] results so far: $NRESULTS"
  sleep 30
done

wait $PID1 || true
wait $PID2 || true
wait $PID3 || true

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  All tiers complete. Generating summary...                   ║"
echo "╚══════════════════════════════════════════════════════════════╝"

python "$SCRIPT_DIR/summarize.py" "$RESULTS" --output "$RESULTS/summary_humaneval.json"

DASHBOARD_PUBLIC="$REPO_ROOT/dashboard/public/summary_humaneval.json"
if [ -f "$RESULTS/summary_humaneval.json" ]; then
  cp "$RESULTS/summary_humaneval.json" "$DASHBOARD_PUBLIC"
  echo "Dashboard data updated → $DASHBOARD_PUBLIC"
fi
