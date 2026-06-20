# AgentROI

**Self-improving agent swarm profiler.** Runs Claude Code SDK agents against a buggy repo, measures ROI, detects waste, and writes memory so every next run is better and cheaper.

> *"Run 1: 3,500 tokens, 4 waste events, ROI 0.446. Run 2: same task — 45% fewer tokens, 50% less waste, ROI 0.550. No human intervention."*

---

## How it works

```
agentroi run ./your-repo --task "..." --trajectory my-bug
       │
       ├─ load memory from previous runs on this trajectory
       ├─ inject learned prompt patches into each agent
       │
       ▼
SwarmOrchestrator  (real Claude Code SDK agents)
  reproducer   → confirms the bug exists
  patch_agent  → fixes the bug
  verifier     → runs the full test suite
       │
       ▼
ROI Analyzer
  waste detectors  → duplicate reads, bad routing, premature test runs
  LLM judge        → scores investigation quality, coordination, patch quality
  formula ROI      → success/cost ratio with waste penalties
       │
       ▼
Memory write-back
  prompt_patches   → injected into agents next run
  waste_patterns   → shown as warnings
  routing_rules    → reorder/gate agents
  episodic_record  → full run history
```

---

## Quick start

```bash
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...

# Single run
agentroi run ./my-repo \
  --task "describe the bug and stack trace here" \
  --source pytest --error-type AssertionError --service myservice \
  --trajectory my-bug-v1

# Inspect memory after the run
agentroi memory --trajectory my-bug-v1

# View the report
agentroi report
```

---

## Full demo (5 bugs × 2 runs)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
./demo/run_all.sh

# Dashboard
./dashboard/start.sh
# → http://localhost:5174
```

**What the demo shows:**
- 5 isolated sandboxed bug repos (calc, auth, api, parser, pipeline)
- Run 1: baseline (5 agents, no memory)
- Run 2: memory-loaded (3 agents, prompt patches from run 1 injected)
- ROI trends up, token cost trends down, waste events halve

**Estimated cost:** ~$5–6 total for all 10 runs

---

## Architecture

```
src/agentroi/
├── cli.py              CLI — agentroi run / memory / report
├── loop.py             AgentROILoop — orchestrates one improvement iteration
├── swarm.py            SwarmOrchestrator + AgentRunner (Claude Code SDK)
├── tracer.py           SwarmTracer — records every tool call to JSONL
├── roi_analyzer.py     Waste detectors, formula ROI, LLM judge, retrospective
├── memory.py           MemoryManager facade
├── memory_backends.py  JSONMemoryBackend, ACEPlaybookBackend
├── memory_consumers.py PromptInjector, RoutingDecider, ActionBlocklist, EvidenceSeeder
├── memory_protocol.py  MemoryBackend / MemoryConsumer protocols
├── waste_detectors.py  duplicate_file_read, bad_routing, premature_full_suite, ...
└── schemas.py          All dataclasses (TraceEvent, RunMetrics, ROIReport, ...)

demo/
├── repos/              5 sandboxed bug repos (each isolated, own memory)
├── results/            ROI report JSONs from all runs
├── memory/             Per-bug memory files
├── run_all.sh          One-command demo runner
├── reset_bugs.py       Restore bugs / apply fixes
└── summarize.py        Print summary table + write summary.json

dashboard/              React + Recharts web dashboard
├── src/App.jsx         ROI trend, token cost, waste charts + run table
└── start.sh            Build + serve (avoids inotify limits)
```

---

## CLI reference

```bash
agentroi run CWD --task TEXT [OPTIONS]

Options:
  --task, -t          Task description (or path to .txt file)
  --source            Error source: pytest, github_ci, ...  [default: pytest]
  --error-type        Error class: AssertionError, TypeError, ...
  --service           Module/service name (for memory scoping)
  --trajectory, -j    Trajectory ID — isolates memory per bug  [default: default]
  --memory            Memory file path  [default: memory/agentroi.json]
  --output            Output directory for traces + reports  [default: runs/]
  --agents            Comma-separated agent subset, e.g. reproducer,patch_agent,verifier
  --iterations, -n    Number of loop iterations  [default: 1]
  --api-key           Anthropic API key (or ANTHROPIC_API_KEY env var)
  --backend           Memory backend: ace or json  [default: ace]
```

---

## Sandbox safety

Agents are restricted to the `CWD` you pass — any file read/write outside that directory is blocked and recorded as a `BLOCKED_ACTION` waste event. Memory files live outside the sandbox and are never visible to agents.
