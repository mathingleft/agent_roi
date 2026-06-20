#!/usr/bin/env bash
# AgentROI — HumanEvalFix 3-tier generalization experiment
#
# TIER 1: Same-bug repeat       — op_get_positive run 3 times, same memory
# TIER 2: Same-domain           — Group A (operator misuse) sequential, shared memory
# TIER 3: Cross-domain          — Groups A→B→C sequential, fully shared memory
#
# Usage: ANTHROPIC_API_KEY=sk-ant-... ./demo/run_humaneval.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
HE="$SCRIPT_DIR/humaneval"
RESULTS="$SCRIPT_DIR/results_humaneval"
LOGS="$SCRIPT_DIR/logs_humaneval"

mkdir -p "$RESULTS" "$LOGS"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: ANTHROPIC_API_KEY not set."
  exit 1
fi

AGENTS_SLIM="reproducer,patch_agent,verifier"

# Shared memory file — all tiers use the same one so learning compounds
SHARED_MEM="$SCRIPT_DIR/memory/humaneval_shared.json"
mkdir -p "$(dirname "$SHARED_MEM")"

one_run() {
  local name="$1" traj="$2" agents="${3:-}"
  local repo="$HE/$name"
  local log="$LOGS/${traj}.log"
  local extra=""
  [ -n "$agents" ] && extra="--agents $agents"

  # read task info from meta.json
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
    --memory "$SHARED_MEM" \
    --output "$RESULTS" \
    --backend ace \
    $extra \
    > "$log" 2>&1
  echo "  ✓ [$name] $traj done"
}

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   AgentROI — HumanEvalFix Generalization Experiment         ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Tier 1: Same-bug repeat  (op_get_positive × 3)             ║"
echo "║  Tier 2: Same-domain      (A: operator misuse × 3)          ║"
echo "║  Tier 3: Cross-domain     (A→B→C, 3+3+3 bugs)               ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo "Shared memory: $SHARED_MEM"
echo ""

# ── TIER 1: Same-bug repeat ─────────────────────────────────────────
echo "━━━━ TIER 1: Same-bug repeat (op_get_positive × 3 runs) ━━━━━━"
one_run "op_get_positive" "t1_op_getpos_run1"
one_run "op_get_positive" "t1_op_getpos_run2" "$AGENTS_SLIM"
one_run "op_get_positive" "t1_op_getpos_run3" "$AGENTS_SLIM"
echo "✓ Tier 1 complete."
echo ""

# ── TIER 2: Same-domain (Group A — all operator misuse) ─────────────
echo "━━━━ TIER 2: Same-domain (Group A: operator misuse) ━━━━━━━━━━"
# run1 baseline for each, then run2 with memory — sequential within group
one_run "op_rescale"      "t2_op_rescale_run1"
one_run "op_rescale"      "t2_op_rescale_run2" "$AGENTS_SLIM"
one_run "op_solve"        "t2_op_solve_run1"
one_run "op_solve"        "t2_op_solve_run2"   "$AGENTS_SLIM"
echo "✓ Tier 2 complete."
echo ""

# ── TIER 3: Cross-domain (A→B→C, memory bleeds across bug types) ────
echo "━━━━ TIER 3: Cross-domain (B: value misuse, then C: variable) ━"
# Group B (value misuse) — memory from A should help
one_run "val_incr_list"   "t3_val_incr_run1"
one_run "val_incr_list"   "t3_val_incr_run2"   "$AGENTS_SLIM"
one_run "val_triangle"    "t3_val_tri_run1"
one_run "val_triangle"    "t3_val_tri_run2"     "$AGENTS_SLIM"
one_run "val_sum_to_n"    "t3_val_sum_run1"
one_run "val_sum_to_n"    "t3_val_sum_run2"     "$AGENTS_SLIM"

# Group C (variable misuse) — memory from A+B should help even more
one_run "var_mad"         "t3_var_mad_run1"
one_run "var_mad"         "t3_var_mad_run2"     "$AGENTS_SLIM"
one_run "var_gcd"         "t3_var_gcd_run1"
one_run "var_gcd"         "t3_var_gcd_run2"     "$AGENTS_SLIM"
one_run "var_decode"      "t3_var_dec_run1"
one_run "var_decode"      "t3_var_dec_run2"     "$AGENTS_SLIM"
echo "✓ Tier 3 complete."
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
