"""Prove the dataset is exactly as received (project rule 13 (README))."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mira import config

HASH_FILE = Path(__file__).parent / "dataset_sha256.json"


def _current() -> dict[str, str]:
    return {
        p.relative_to(config.DATASET_DIR).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(config.DATASET_DIR.rglob("*")) if p.is_file()
    }


def test_every_dataset_file_matches_recorded_sha256():
    expected = json.loads(HASH_FILE.read_text(encoding="utf-8"))
    current = _current()
    assert sorted(current) == sorted(expected), "files were added to or removed from the dataset"
    changed = [path for path in expected if current[path] != expected[path]]
    assert not changed, f"dataset files were modified: {changed}"


def test_loading_does_not_modify_the_workbook():
    before = hashlib.sha256(config.WORKBOOK_PATH.read_bytes()).hexdigest()
    from mira.data import load_workbook

    load_workbook()
    assert hashlib.sha256(config.WORKBOOK_PATH.read_bytes()).hexdigest() == before


def test_seed_file_has_17_cases():
    """The dataset README says 15, but the file (and the brief) have 17. We use the file."""
    lines = [l for l in config.EVAL_SEED_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    ids = [json.loads(l)["id"] for l in lines]
    assert ids == [f"S{i:02d}" for i in range(1, 18)]


def test_dataset_has_no_images():
    """Requirement 8's 'Ella photos' don't exist: Mira must say so and use a placeholder."""
    image_ext = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif"}
    assert not [p for p in config.DATASET_DIR.rglob("*") if p.suffix.lower() in image_ext]
