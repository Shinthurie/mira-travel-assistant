"""The one documented command: ``python scripts/dev.py`` starts the whole system.

Works on Windows, macOS and Linux (no make, no Docker, no shell scripts).
1. Checks Python 3.11 and loads the dataset (fails fast if the data can't be read).
2. Starts the FastAPI backend (uvicorn), once ``mira/api.py`` exists (Phase 2.5).
3. Starts the Next.js frontend, once ``frontend/package.json`` exists (Phase 2.5).
Ctrl+C stops everything.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"


def check_python() -> None:
    if sys.version_info[:2] != (3, 11):
        print(f"Warning: Python 3.11 expected, running {sys.version.split()[0]}.")


def check_data() -> None:
    """Load the dataset once so problems show up before any server starts."""
    result = subprocess.run([sys.executable, "-m", "mira.data"], cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8")
    if result.returncode != 0:
        print(result.stdout, result.stderr)
        raise SystemExit("Dataset failed to load. See the error above.")
    print("\n".join(result.stdout.splitlines()[:8]))


def start_backend() -> subprocess.Popen | None:
    if not (ROOT / "mira" / "api.py").exists():
        print("Backend: not built yet (Phase 2.5).")
        return None
    port = os.environ.get("BACKEND_PORT", "8123")
    print(f"Backend: http://localhost:{port}")
    return subprocess.Popen([sys.executable, "-m", "uvicorn", "mira.api:app", "--port", port, "--reload"], cwd=ROOT)


def start_frontend() -> subprocess.Popen | None:
    if not (FRONTEND / "package.json").exists():
        print("Frontend: not built yet (Phase 2.5).")
        return None
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm not found. Install Node.js 18+ (LTS) from nodejs.org and reopen the terminal.")
    if not (FRONTEND / "node_modules").exists():
        print("Frontend: installing dependencies (first run only)...")
        subprocess.run([npm, "ci"], cwd=FRONTEND, check=True)
    port = os.environ.get("FRONTEND_PORT", "3000")
    print(f"Frontend: http://localhost:{port}")
    return subprocess.Popen([npm, "run", "dev", "--", "--port", port], cwd=FRONTEND)


def main() -> int:
    check_python()
    check_data()
    processes = [p for p in (start_backend(), start_frontend()) if p is not None]
    if not processes:
        print("Nothing to start yet. Data loaded fine.")
        return 0
    try:
        while all(p.poll() is None for p in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
        for p in processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
