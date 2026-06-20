"""Reset all demo repos to their buggy state."""
from pathlib import Path

DEMO = Path(__file__).parent
REPOS = DEMO / "repos"

BUGS = {
    "calc": {
        "file": REPOS / "calc/calc.py",
        "find": "return a / b",
        "replace": "return a // b  # BUG: should be a / b",
    },
    "auth": {
        "file": REPOS / "auth/auth.py",
        "find": "return age >= 18",
        "replace": "return age > 18  # BUG: should be age >= 18, rejects exactly-18-year-olds",
    },
    "api": {
        "file": REPOS / "api/api.py",
        "find": "return await db.fetch_user(user_id)",
        "replace": "return db.fetch_user(user_id)  # BUG: missing await — returns coroutine, not dict",
    },
    "parser": {
        "file": REPOS / "parser/parser.py",
        "find": '"username": raw["username"]',
        "replace": '"username": raw["name"],  # BUG: API uses "username" key, not "name"',
    },
    "pipeline": {
        "file": REPOS / "pipeline/pipeline.py",
        "find": "batch = items[0:n]",
        "replace": "batch = items[1:n]  # BUG: should be items[0:n], skips the first element",
    },
}

FIXES = {
    "calc": {
        "file": REPOS / "calc/calc.py",
        "find": "return a // b  # BUG: should be a / b",
        "replace": "return a / b",
    },
    "auth": {
        "file": REPOS / "auth/auth.py",
        "find": "return age > 18  # BUG: should be age >= 18, rejects exactly-18-year-olds",
        "replace": "return age >= 18",
    },
    "api": {
        "file": REPOS / "api/api.py",
        "find": "return db.fetch_user(user_id)  # BUG: missing await — returns coroutine, not dict",
        "replace": "return await db.fetch_user(user_id)",
    },
    "parser": {
        "file": REPOS / "parser/parser.py",
        "find": '"username": raw["name"],  # BUG: API uses "username" key, not "name"',
        "replace": '"username": raw["username"]',
    },
    "pipeline": {
        "file": REPOS / "pipeline/pipeline.py",
        "find": "batch = items[1:n]  # BUG: should be items[0:n], skips the first element",
        "replace": "batch = items[0:n]",
    },
}


def apply(mapping: dict, label: str):
    for repo, info in mapping.items():
        path = info["file"]
        content = path.read_text()
        if info["find"] in content:
            path.write_text(content.replace(info["find"], info["replace"], 1))
            print(f"  [{label}] {repo}: applied")
        elif info["replace"] in content:
            print(f"  [skip] {repo}: already in {label} state")
        else:
            print(f"  [WARN] {repo}: neither string found in {path.name}")


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "bug"
    if mode == "fix":
        print("Applying fixes...")
        apply(FIXES, "fix")
    else:
        print("Restoring bugs...")
        apply(BUGS, "bug")
