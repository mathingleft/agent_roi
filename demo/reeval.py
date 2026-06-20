"""
Recompute composite_roi_score for all existing ROI reports using the
current formula, without re-running the agents.

Usage:
    python demo/reeval.py demo/results_humaneval
    python demo/reeval.py demo/results          # synthetic demo too
"""
from __future__ import annotations
import json
import sys
from pathlib import Path


_TOKEN_BASELINE = 5000


def formula_roi(metrics: dict, waste_events: list[dict]) -> float:
    target_passed = metrics["target_test_passed"] or metrics["full_suite_passed"]
    if not target_passed:
        return 0.0

    tok_eff = min(_TOKEN_BASELINE / max(metrics["tokens_total"], 1), 2.0)
    critical_waste = sum(1 for w in waste_events if w.get("severity") == "critical")
    waste_factor = 1.0 - min(critical_waste * 0.15, 0.6)
    patch_factor = 1.1 if (0 < metrics["patch_diff_lines"] <= 20) else 1.0
    cheat_factor = 0.5 if metrics["test_files_edited"] else 1.0

    return round(min(tok_eff * waste_factor * patch_factor * cheat_factor, 2.0), 3)


def composite_roi(formula: float, judge_overall: float) -> float:
    return formula


def reeval(results_dir: Path):
    reports = sorted(results_dir.glob("*_roi_report.json"))
    if not reports:
        print(f"No reports found in {results_dir}")
        return

    updated = 0
    for path in reports:
        report = json.loads(path.read_text())
        old_score = report["composite_roi_score"]

        froi = formula_roi(report["metrics"], report["waste_events"])
        new_score = composite_roi(froi, report.get("judge_verdict", {}).get("overall_roi", 0))

        if new_score != old_score:
            report["composite_roi_score"] = new_score
            path.write_text(json.dumps(report, indent=2))
            print(f"  {path.name[:50]:50s}  {old_score:.3f} → {new_score:.3f}")
            updated += 1
        else:
            print(f"  {path.name[:50]:50s}  {old_score:.3f}  (unchanged)")

    print(f"\n{updated}/{len(reports)} reports updated.")


if __name__ == "__main__":
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo/results_humaneval")
    reeval(d)
