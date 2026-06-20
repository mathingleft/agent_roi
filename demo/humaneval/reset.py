"""Reset humaneval repos back to buggy state."""
import sys
from pathlib import Path

BASE = Path(__file__).parent

def reset(only=None):
    for repo in sorted(BASE.iterdir()):
        if not repo.is_dir(): continue
        if only and repo.name != only: continue
        buggy = repo / "solution.py"
        fixed = repo / "solution_fixed.py"
        if not buggy.exists() or not fixed.exists(): continue
        # restore buggy content from fixed backup if already patched
        # (we detect by checking if fixed content != buggy content)
        # Just always copy back from solution_fixed baseline — agent writes solution.py
        # We store original buggy in solution_buggy.py as the ground truth
        buggy_orig = repo / "solution_buggy.py"
        if buggy_orig.exists():
            buggy.write_text(buggy_orig.read_text())
            print(f"  reset {repo.name}")
        else:
            # First time — save current solution.py as the canonical buggy
            buggy_orig.write_text(buggy.read_text())
            print(f"  saved buggy baseline for {repo.name}")

if __name__ == "__main__":
    only = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--only" and i+1 < len(args):
            only = args[i+1]; i += 1
        i += 1
    reset(only)
