#!/usr/bin/env python3
"""PAMOs repository safety gate. Checks tracked paths only, not the user's local datasets."""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
REQUIRED = (
    "README.md", "AGENTS.md", "CODEX_START.md", "LICENSE",
    ".gitignore", "CHANGELOG.md", "docs/32_VERSION_CONTROL_POLICY.md",
)
BLOCKED_DIRS = (
    "datasets/", "data/", "media/", "audio/", "raw_charts/", "chart_assets/",
    "checkpoints/", "runs/", "training_cache/", "model_registry/",
    "models/registry/", "node_modules/", ".venv/", "venv/",
    ".pamos/", ".pamos_state/",
    ".tools/", ".runtime/", ".cache/", ".downloads/", ".local/",
)
BLOCKED_EXTENSIONS = {
    ".mp3", ".flac", ".ogg", ".wav", ".pez", ".pt", ".pth", ".ckpt",
    ".safetensors", ".onnx", ".sqlite", ".sqlite3", ".db", ".pem", ".key",
}
MAX_TRACKED_BYTES = 5 * 1024 * 1024  # Regular source files only; large binaries require review.
TEXT_EXTENSIONS = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".mjs", ".js", ".ts", ".tsx", ".vue", ".sh"}
SECRET_RE = re.compile(
    rb"(?:gh[pousr]_[A-Za-z0-9_]{36,}|github_pat_[A-Za-z0-9_]{60,}"
    rb"|AKIA[0-9A-Z]{16}|glpat-[A-Za-z0-9_-]{20,}"
    rb"|sk-(?:proj-)?[A-Za-z0-9_-]{30,})"
)


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    )
    return [part.decode("utf-8", errors="replace") for part in result.stdout.split(b"\x00") if part]


def validate() -> list[str]:
    errors: list[str] = []
    files = tracked_files()
    tracked = set(files)
    for required in REQUIRED:
        if required not in tracked:
            errors.append(f"Required tracked file missing: {required}")

    for path in files:
        lower = path.lower()
        parts = pathlib.PurePosixPath(path).parts
        file = ROOT / path
        if not file.is_file():
            errors.append(f"Tracked path not found in worktree: {path}")
            continue
        if any(lower.startswith(prefix) for prefix in BLOCKED_DIRS):
            errors.append(f"Private data or generated directory tracked: {path}")
        if "__pycache__" in parts or lower.endswith(".pyc"):
            errors.append(f"Compiled Python file tracked: {path}")
        if any(name == ".env" or name.startswith(".env.") and name != ".env.example" for name in parts):
            errors.append(f"Environment file tracked: {path}")
        if pathlib.PurePosixPath(path).suffix.lower() in BLOCKED_EXTENSIONS:
            errors.append(f"Prohibited binary/media extension tracked: {path}")
        size = file.stat().st_size
        if size > MAX_TRACKED_BYTES:
            errors.append(f"File requires large-object review ({size} B): {path}")
        if size <= MAX_TRACKED_BYTES and file.suffix.lower() in TEXT_EXTENSIONS:
            try:
                data = file.read_bytes()
            except OSError as err:
                errors.append(f"Unable to inspect {path}: {err}")
                continue
            if SECRET_RE.search(data):
                errors.append(f"Potential credential literal found in: {path}")
    return errors


if __name__ == "__main__":
    failures = validate()
    for failure in failures:
        print(f"ERROR: {failure}", file=sys.stderr)
    if failures:
        sys.exit(1)
    print("PAMOs repository guard: PASS (tracked files only; not a substitute for license review).")
