#!/usr/bin/env python3
"""M6 acceptance gate — runs the full backend suite serial + parallel,
compileall, and git diff --check as subprocesses.

Run standalone:
    export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres
    python scripts/verify_m6_gate.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], timeout: int = 900, **kw) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    if result.returncode != 0:
        print(f"FAILED: {' '.join(cmd)}", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    print(f"  OK: {' '.join(cmd)}")
    return result


def main() -> None:
    backend = Path(__file__).resolve().parent.parent

    print("=== M6 meta-gate verification ===")
    _run([sys.executable, "-m", "pytest", "-n0", "--tb=short", "-q"],
         cwd=backend, timeout=900)
    _run([sys.executable, "-m", "pytest", "--tb=short", "-q"],
         cwd=backend, timeout=900)
    _run([sys.executable, "-m", "compileall", "-q", str(backend / "app")],
         cwd=backend)
    _run(["git", "diff", "--check"],
         cwd=backend.parent)

    print("\nAll gates green.")


if __name__ == "__main__":
    main()
