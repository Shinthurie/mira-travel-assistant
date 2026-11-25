"""The one documented command: ``python scripts/dev.py`` starts the whole system.

Works on Windows, macOS and Linux (no make, no Docker, no shell scripts).
1. First run: creates ``.venv`` and installs the pinned backend packages, then re-runs itself there.
2. Loads the dataset once (fails fast if the data can't be read).
3. Starts the FastAPI backend (uvicorn) on BACKEND_PORT (default 8123).
4. Starts the Next.js frontend on FRONTEND_PORT (default 3000), installing npm packages on first run.
Ctrl+C stops everything.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
VENV = ROOT / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_backend_packages() -> None:
    """Re-run inside .venv (creating it on first run) if the backend packages aren't importable."""
    try:
        import fastapi  # noqa: F401
        import langgraph  # noqa: F401
        import copilotkit  # noqa: F401
        return
    except ImportError:
        pass
    if Path(sys.executable).resolve() == VENV_PY.resolve():
        print("Installing backend packages into .venv ...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")], check=True)
        return
    if not VENV_PY.exists():
        print("First run: creating .venv (Python 3.11) ...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        subprocess.run([str(VENV_PY), "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")], check=True)
    raise SystemExit(subprocess.call([str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]]))


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


def start_backend() -> subprocess.Popen:
    port = os.environ.get("BACKEND_PORT", "8123")
    print(f"Backend:  http://localhost:{port}  (health: /health)")
    return subprocess.Popen([sys.executable, "-m", "uvicorn", "mira.api:app", "--port", port], cwd=ROOT)


def wait_for_backend(timeout: float = 90) -> None:
    port = os.environ.get("BACKEND_PORT", "8123")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    print("Backend ready.")
                    return
        except OSError:
            time.sleep(1)
    print("Warning: backend did not answer /health yet; starting the frontend anyway.")


def start_frontend() -> subprocess.Popen:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm not found. Install Node.js 18+ (LTS) from nodejs.org and reopen the terminal.")
    if not (FRONTEND / "node_modules").exists():
        print("Frontend: installing npm packages (first run only, a few minutes) ...")
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=FRONTEND, check=True)
    port = os.environ.get("FRONTEND_PORT", "3000")
    print(f"Frontend: http://localhost:{port}   Staff page: http://localhost:{port}/staff")
    # No usage telemetry to CopilotKit or Next.js: nothing leaves the machine except the LLM and Langfuse calls.
    env = dict(os.environ, COPILOTKIT_TELEMETRY_DISABLED="true", NEXT_TELEMETRY_DISABLED="1")
    return subprocess.Popen([npm, "run", "dev", "--", "--port", port], cwd=FRONTEND, env=env)


def main() -> int:
    ensure_backend_packages()
    check_python()
    sys.path.insert(0, str(ROOT))
    from mira import config  # noqa: F401  (loads .env so the ports and keys below are visible)
    check_data()
    processes = [start_backend()]
    wait_for_backend()
    processes.append(start_frontend())
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
