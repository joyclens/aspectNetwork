from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(label: str, args: list[str]) -> int:
    print(f"==> {label}")
    completed = subprocess.run(args, cwd=ROOT, check=False)
    if completed.returncode != 0:
        print(f"FAILED: {label} ({completed.returncode})")
    return completed.returncode


def main() -> int:
    python = sys.executable
    steps = [
        ("ruff format --check", [python, "-m", "ruff", "format", "--check", "."]),
        ("ruff check", [python, "-m", "ruff", "check", "."]),
        ("mypy", [python, "-m", "mypy"]),
        ("pytest", [python, "-m", "pytest", "-q"]),
    ]
    code = 0
    for label, args in steps:
        code = run(label, args) or code
    return code


if __name__ == "__main__":
    raise SystemExit(main())
