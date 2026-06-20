"""Print a summary table of all ROI reports in the results directory.
Also writes demo/results/summary.json for the dashboard to consume.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import rich
from rich.table import Table
from rich import box
from rich.console import Console

console = Console()


def load_reports(results_dir: Path) -> list[dict]:
    reports = []
    for f in sorted(results_dir.glob("*_roi_report.json")):
        try:
            d = json.loads(f.read_text())
            d["_file"] = f.name
            reports.append(d)
        except Exception:
            pass
    return reports


def extract_row(r: dict) -> dict:
    m = r.get("metrics", {})
    sig = r.get("task_signature", {})
    return {
        "run_id": r.get("run_id", "?")[-20:],
        "service": sig.get("service", "?"),
        "roi": r.get("composite_roi_score", 0),
        "tokens": m.get("tokens_total", 0),
        "file_reads": m.get("file_reads", 0),
        "dup_reads": m.get("duplicate_file_reads", 0),
        "waste": len(r.get("waste_events", [])),
        "target_pass": m.get("target_test_passed", False),
        "suite_pass": m.get("full_suite_passed", False),
        "wall_time": m.get("wall_time_sec", 0),
        "file": r.get("_file", ""),
    }


def main(results_dir: Path):
    reports = load_reports(results_dir)
    if not reports:
        console.print("[red]No reports found in[/] " + str(results_dir))
        return

    rows = [extract_row(r) for r in reports]

    t = Table(title="AgentROI Demo — All Runs", box=box.ROUNDED, show_header=True, header_style="bold cyan")
    t.add_column("Service", style="bold")
    t.add_column("ROI", justify="right")
    t.add_column("Tokens", justify="right")
    t.add_column("Reads", justify="right")
    t.add_column("Dups", justify="right")
    t.add_column("Waste", justify="right")
    t.add_column("Wall(s)", justify="right")
    t.add_column("Target✓", justify="center")
    t.add_column("Suite✓", justify="center")

    for row in rows:
        score = row["roi"]
        colour = "green" if score >= 0.6 else ("yellow" if score >= 0.35 else "red")
        t.add_row(
            row["service"],
            f"[{colour}]{score:.3f}[/]",
            str(row["tokens"]),
            str(row["file_reads"]),
            str(row["dup_reads"]),
            str(row["waste"]),
            f"{row['wall_time']:.0f}",
            "[green]✓[/]" if row["target_pass"] else "[red]✗[/]",
            "[green]✓[/]" if row["suite_pass"] else "[red]✗[/]",
        )

    console.print(t)

    # Group by service for trend
    by_service: dict[str, list[dict]] = {}
    for row in rows:
        by_service.setdefault(row["service"], []).append(row)

    console.print("\n[bold]ROI trend per bug:[/]")
    for svc, svc_rows in by_service.items():
        scores = [r["roi"] for r in svc_rows]
        tokens = [r["tokens"] for r in svc_rows]
        if len(scores) >= 2:
            roi_delta = scores[-1] - scores[0]
            tok_delta = tokens[-1] - tokens[0]
            roi_sym = "↑" if roi_delta > 0 else "↓"
            tok_sym = "↓" if tok_delta < 0 else "↑"
            console.print(
                f"  [bold]{svc:10s}[/]  ROI {scores[0]:.3f} → {scores[-1]:.3f} "
                f"[green]{roi_sym}{abs(roi_delta):.3f}[/]  |  "
                f"Tokens {tokens[0]} → {tokens[-1]} "
                f"[{'green' if tok_delta < 0 else 'red'}]{tok_sym}{abs(tok_delta)}[/]"
            )
        else:
            console.print(f"  [bold]{svc:10s}[/]  ROI {scores[0]:.3f}  (single run)")

    # Write summary.json for dashboard
    summary = {
        "runs": [extract_row(r) for r in reports],
        "by_service": {
            svc: [extract_row(r) for r in reports if r.get("task_signature", {}).get("service") == svc]
            for svc in set(r.get("task_signature", {}).get("service", "") for r in reports)
        },
    }
    summary_path = results_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    console.print(f"\n[dim]Summary written → {summary_path}[/]")


if __name__ == "__main__":
    results_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo/results")
    main(results_dir)
