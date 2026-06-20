"""AgentROI CLI — run the improvement loop against any buggy repo."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import anthropic
import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.text import Text

from .loop import AgentROILoop

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sig_from_opts(source: str, error_type: str, service: str) -> dict[str, Any]:
    return {"source": source, "error_type": error_type, "service": service}


def _print_roi_summary(result: dict[str, Any]) -> None:
    report = result["roi_report"]
    m = report.metrics

    score = report.composite_roi_score
    colour = "green" if score >= 0.6 else ("yellow" if score >= 0.3 else "red")

    console.print()
    console.print(Panel(
        f"[bold {colour}]Composite ROI: {score:.3f}[/]  "
        f"  run_id=[dim]{result['run_id']}[/]  "
        f"  trajectory=[dim]{result['trajectory_id']}[/]",
        title="[bold]AgentROI Result[/]",
        border_style=colour,
    ))

    # Metrics table
    t = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    t.add_column("Metric", style="dim")
    t.add_column("Value", justify="right")
    t.add_row("Wall time", f"{m.wall_time_sec:.1f}s")
    t.add_row("Tokens (est)", str(m.tokens_total))
    t.add_row("File reads", str(m.file_reads))
    t.add_row("Duplicate reads", str(m.duplicate_file_reads))
    t.add_row("Test runs", str(m.test_runs))
    t.add_row("Evidence published", str(m.evidence_published))
    t.add_row("Target test passed", "[green]✓[/]" if m.target_test_passed else "[red]✗[/]")
    t.add_row("Full suite passed", "[green]✓[/]" if m.full_suite_passed else "[red]✗[/]")
    t.add_row("Test files edited", "[red]✗ CHEAT[/]" if m.test_files_edited else "[green]clean[/]")
    console.print(t)

    # Waste events
    if report.waste_events:
        console.print(f"[yellow]Waste events detected ({len(report.waste_events)}):[/]")
        for w in report.waste_events:
            console.print(f"  [red]•[/] [{w.severity}] {w.waste_type.value}: {w.description[:100]}")
    else:
        console.print("[green]No waste events detected[/]")

    # Judge insight
    if report.judge_verdict and report.judge_verdict.key_insight:
        console.print(f"\n[bold]Judge insight:[/] {report.judge_verdict.key_insight}")

    # Retrospective (first 300 chars)
    if report.retrospective:
        console.print(f"\n[bold]Retrospective:[/] {report.retrospective[:300]}")

    # Memory entries written
    console.print(f"\n[dim]Report written → {result['report_path']}[/]")


def _print_loop_summary(history: list[dict[str, Any]]) -> None:
    console.print()
    t = Table(title="Loop Summary", box=box.ROUNDED, show_header=True, header_style="bold")
    t.add_column("Run #", justify="center")
    t.add_column("Run ID", style="dim", max_width=28)
    t.add_column("ROI Score", justify="right")
    t.add_column("Tokens", justify="right")
    t.add_column("Target ✓", justify="center")
    t.add_column("Waste", justify="right")

    for i, r in enumerate(history, 1):
        rpt = r["roi_report"]
        score = rpt.composite_roi_score
        colour = "green" if score >= 0.6 else ("yellow" if score >= 0.3 else "red")
        t.add_row(
            str(i),
            r["run_id"][-28:],
            f"[{colour}]{score:.3f}[/]",
            str(rpt.metrics.tokens_total),
            "[green]✓[/]" if rpt.metrics.target_test_passed else "[red]✗[/]",
            str(len(rpt.waste_events)),
        )
    console.print(t)

    scores = [r["roi_report"].composite_roi_score for r in history]
    trend = "↑" if len(scores) > 1 and scores[-1] > scores[0] else ("↓" if len(scores) > 1 and scores[-1] < scores[0] else "→")
    console.print(f"\n[bold]ROI trend across {len(history)} iterations: {trend}[/]  "
                  f"first={scores[0]:.3f}  last={scores[-1]:.3f}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """AgentROI: self-improving agent-swarm profiler."""


@cli.command("run")
@click.argument("cwd", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--task", "-t", required=True, help="Task description or path to a .txt file containing it")
@click.option("--source", default="pytest", show_default=True, help="Error source (pytest, github_ci, ...)")
@click.option("--error-type", default="Error", show_default=True, help="Error type class")
@click.option("--service", default="unknown", show_default=True, help="Service/module name")
@click.option("--trajectory", "-j", default="default", show_default=True, help="Trajectory ID (for isolation)")
@click.option("--memory", "memory_path", type=click.Path(path_type=Path),
              default=Path("memory/agentroi.json"), show_default=True, help="Memory file path")
@click.option("--output", "output_dir", type=click.Path(path_type=Path),
              default=Path("runs"), show_default=True, help="Directory for traces and reports")
@click.option("--backend", type=click.Choice(["ace", "json"]), default="ace", show_default=True)
@click.option("--agents", default=None,
              help="Comma-separated agent subset, e.g. reproducer,patch_agent,verifier (default: all 5)")
@click.option("--iterations", "-n", default=1, show_default=True, help="Number of loop iterations")
@click.option("--json-out", is_flag=True, default=False, help="Print final result as JSON instead of rich output")
@click.option("--api-key", envvar="ANTHROPIC_API_KEY", default=None,
              help="Anthropic API key (or set ANTHROPIC_API_KEY env var). Used for LLM judge + retrospective.")
def run_cmd(
    cwd: Path,
    task: str,
    source: str,
    error_type: str,
    service: str,
    trajectory: str,
    memory_path: Path,
    output_dir: Path,
    backend: str,
    agents: str | None,
    iterations: int,
    json_out: bool,
    api_key: str | None,
):
    """Run the AgentROI improvement loop on a buggy repo.

    CWD is the working directory passed to the Claude agents (your repo root).

    Examples:

    \b
      # Single run against a repo
      agentroi run ./my_repo --task "Fix the divide bug" --service calculator

    \b
      # Task description from a file, 3 iterations
      agentroi run ./my_repo --task ./task.txt --iterations 3 --trajectory exp1

    \b
      # JSON output for piping
      agentroi run ./my_repo --task "Fix auth bug" --json-out | jq .composite_roi
    """
    # Allow --task to be a file path
    task_path = Path(task)
    if task_path.exists() and task_path.is_file():
        task_description = task_path.read_text().strip()
    else:
        task_description = task

    task_signature = _sig_from_opts(source, error_type, service)

    if api_key:
        anthropic_client = anthropic.AsyncAnthropic(api_key=api_key)
    else:
        anthropic_client = None
        console.print("[yellow]Note:[/] No ANTHROPIC_API_KEY — running formula-only ROI (no LLM judge/retrospective).")

    agent_order = [a.strip() for a in agents.split(",")] if agents else None

    loop = AgentROILoop(
        memory_path=memory_path,
        output_dir=output_dir,
        memory_backend=backend,
        anthropic_client=anthropic_client,
        agent_order=agent_order,
    )

    console.print(Panel(
        f"[bold]Task:[/] {task_description[:200]}\n"
        f"[bold]Trajectory:[/] {trajectory}  [bold]Iterations:[/] {iterations}\n"
        f"[bold]CWD:[/] {cwd}  [bold]Backend:[/] {backend}",
        title="[bold cyan]AgentROI[/]",
        border_style="cyan",
    ))

    if iterations == 1:
        result = asyncio.run(loop.run_once(
            task_description=task_description,
            task_signature=task_signature,
            cwd=cwd,
            trajectory_id=trajectory,
        ))
        if json_out:
            out = {
                "run_id": result["run_id"],
                "trajectory_id": result["trajectory_id"],
                "composite_roi": result["composite_roi"],
                "report_path": result["report_path"],
            }
            click.echo(json.dumps(out, indent=2))
        else:
            _print_roi_summary(result)
    else:
        history = asyncio.run(loop.run_loop(
            task_description=task_description,
            task_signature=task_signature,
            cwd=cwd,
            trajectory_id=trajectory,
            num_iterations=iterations,
        ))
        if json_out:
            out = [
                {
                    "run_id": r["run_id"],
                    "composite_roi": r["composite_roi"],
                    "report_path": r["report_path"],
                }
                for r in history
            ]
            click.echo(json.dumps(out, indent=2))
        else:
            for r in history:
                _print_roi_summary(r)
            _print_loop_summary(history)


@cli.command("memory")
@click.option("--memory", "memory_path", type=click.Path(path_type=Path),
              default=Path("memory/agentroi.json"), show_default=True)
@click.option("--trajectory", "-j", default=None, help="Filter to one trajectory")
@click.option("--backend", type=click.Choice(["ace", "json"]), default="ace", show_default=True)
def memory_cmd(memory_path: Path, trajectory: str | None, backend: str):
    """Inspect stored memory entries."""
    from .memory import make_memory_manager
    if not memory_path.exists():
        console.print("[red]Memory file not found.[/]")
        sys.exit(1)

    mgr = make_memory_manager(memory_path, backend=backend)
    trajs = mgr.list_trajectories()

    if not trajs:
        console.print("[yellow]No trajectories found in memory.[/]")
        return

    targets = [trajectory] if trajectory else trajs
    for traj in targets:
        snap = mgr.snapshot(traj)
        t = Table(title=f"Trajectory: [bold]{traj}[/]  ({len(snap)} entries)",
                  box=box.SIMPLE, show_header=True, header_style="bold cyan")
        t.add_column("Type", style="dim", max_width=20)
        t.add_column("Role", style="dim", max_width=16)
        t.add_column("Content", max_width=60)
        t.add_column("+/-", justify="right")
        for e in snap:
            content = e.get("content", "")
            if isinstance(content, dict):
                content = json.dumps(content)[:60]
            else:
                content = str(content)[:60]
            votes = f"+{e.get('helpful_count', 0)}/-{e.get('harmful_count', 0)}"
            t.add_row(e.get("entry_type", ""), e.get("agent_role", ""), content, votes)
        console.print(t)


@cli.command("report")
@click.argument("report_path", type=click.Path(exists=True, path_type=Path))
def report_cmd(report_path: Path):
    """Pretty-print a saved ROI report JSON file."""
    with report_path.open() as f:
        data = json.load(f)

    console.print(Panel(
        f"[bold]Run ID:[/] {data.get('run_id')}\n"
        f"[bold]Composite ROI:[/] {data.get('composite_roi_score', '?')}\n"
        f"[bold]Task:[/] {str(data.get('task_signature', ''))[:120]}",
        title="ROI Report",
        border_style="cyan",
    ))

    metrics = data.get("metrics", {})
    if metrics:
        t = Table(box=box.SIMPLE, show_header=False)
        t.add_column("k", style="dim")
        t.add_column("v")
        for k, v in metrics.items():
            t.add_row(k, str(v))
        console.print(t)

    waste = data.get("waste_events", [])
    if waste:
        console.print(f"\n[yellow]Waste events ({len(waste)}):[/]")
        for w in waste:
            console.print(f"  • [{w.get('severity','?')}] {w.get('waste_type','?')}: {w.get('description','')[:100]}")

    retro = data.get("retrospective", "")
    if retro:
        console.print(f"\n[bold]Retrospective:[/]\n{retro}")


def main():
    cli()


if __name__ == "__main__":
    main()
