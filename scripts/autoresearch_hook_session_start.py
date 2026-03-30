#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


MARKER_FILES = (
    "autoresearch-launch.json",
    "autoresearch-runtime.json",
    "autoresearch-state.json",
)
SKILL_ROOT_RELATIVE_CANDIDATES = (
    Path(".agents/skills/codex-autoresearch"),
    Path(".codex/skills/codex-autoresearch"),
)
CHECKLIST_LINES = (
    "- If this is a fresh run, baseline first, then initialize results/state artifacts.",
    "- Record every completed experiment before starting the next one.",
    "- Use helper scripts for authoritative TSV/state updates.",
    "- Do not rerun the wizard after launch is already confirmed.",
)


def load_input() -> dict[str, object]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def manifest_path() -> Path:
    return Path(__file__).resolve().with_name("manifest.json")


def load_manifest() -> dict[str, object]:
    path = manifest_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_git_repo(cwd: Path) -> Path | None:
    completed = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    repo = Path(completed.stdout.strip())
    return repo if repo.exists() else None


def find_artifact_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if any((candidate / name).exists() for name in MARKER_FILES):
            return candidate
    return None


def resolve_repo(cwd: Path) -> Path:
    repo = resolve_git_repo(cwd)
    if repo is not None:
        return repo
    artifact_root = find_artifact_root(cwd)
    if artifact_root is not None:
        return artifact_root
    return cwd


def is_active_autoresearch_repo(repo: Path) -> bool:
    if any((repo / name).exists() for name in MARKER_FILES):
        return True
    results_path = repo / "research-results.tsv"
    if not results_path.exists():
        return False
    try:
        first_line = results_path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return False
    return first_line.startswith("iteration\tcommit\tmetric\t")


def valid_skill_root(path: Path | None) -> Path | None:
    if path is None:
        return None
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        return None
    if not (resolved / "SKILL.md").exists():
        return None
    scripts_dir = resolved / "scripts"
    if not (scripts_dir / "autoresearch_supervisor_status.py").exists():
        return None
    return resolved


def resolve_skill_root(cwd: Path, manifest: dict[str, object]) -> Path | None:
    for base in (cwd, *cwd.parents):
        for relative in SKILL_ROOT_RELATIVE_CANDIDATES:
            candidate = valid_skill_root(base / relative)
            if candidate is not None:
                return candidate

    home = Path.home()
    for relative in (
        Path(".agents/skills/codex-autoresearch"),
        Path(".codex/skills/codex-autoresearch"),
    ):
        candidate = valid_skill_root(home / relative)
        if candidate is not None:
            return candidate

    fallback = manifest.get("skill_root_fallback")
    if isinstance(fallback, str):
        return valid_skill_root(Path(fallback))
    return None


def emit_additional_context(text: str) -> None:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }
    print(json.dumps(payload), end="")


def main() -> int:
    payload = load_input()
    cwd_value = payload.get("cwd")
    if not isinstance(cwd_value, str) or not cwd_value:
        return 0

    cwd = Path(cwd_value).expanduser().resolve()
    manifest = load_manifest()
    repo = resolve_repo(cwd)
    if not is_active_autoresearch_repo(repo):
        return 0

    if resolve_skill_root(cwd, manifest) is None:
        return 0

    emit_additional_context("\n".join(CHECKLIST_LINES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
