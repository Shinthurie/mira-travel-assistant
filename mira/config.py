"""Central configuration: paths and environment variables.

Everything that can change between runs (today's date, the override file) is read here,
so the rest of the code never calls ``os.environ`` directly.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
DATASET_DIR: Path = REPO_ROOT / "data" / "ceylon-compass-dataset"
WORKBOOK_PATH: Path = DATASET_DIR / "rates" / "rate_sheet_2026-27.xlsx"
CONTENT_DIR: Path = DATASET_DIR / "content"
BRAND_PACK_PATH: Path = DATASET_DIR / "brand" / "brand_pack.json"
EVAL_SEED_PATH: Path = DATASET_DIR / "evals" / "eval_seed.jsonl"
DECISIONS_PATH: Path = REPO_ROOT / "config" / "data_decisions.yaml"

DEFAULT_TODAY = "2026-11-19"

# Load .env once, if present. Real environment variables take precedence.
load_dotenv(REPO_ROOT / ".env", override=False)


def today() -> date:
    """Return the configured "today" (env ``TODAY``, default 2026-11-19, which the evals assume)."""
    return date.fromisoformat(os.environ.get("TODAY", DEFAULT_TODAY).strip())


def pricing_overrides_path() -> Path | None:
    """Return the optional pricing override file (env ``PRICING_OVERRIDES_FILE``), or None.

    A relative path is resolved from the repo root.
    """
    raw = os.environ.get("PRICING_OVERRIDES_FILE", "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path
