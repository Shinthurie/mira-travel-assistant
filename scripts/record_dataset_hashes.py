"""Record the SHA-256 of every dataset file into ``tests/dataset_sha256.json``.

Run once, right after extracting the dataset:  ``python scripts/record_dataset_hashes.py``
If the original zip (``GenAI-Intern-Take-Home-Assignment.zip``) is in the repo root, every
file is also checked byte-for-byte against the zip, proving the extracted copy is unchanged.
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = REPO_ROOT / "data" / "ceylon-compass-dataset"
HASH_FILE = REPO_ROOT / "tests" / "dataset_sha256.json"
ZIP_PATH = REPO_ROOT / "GenAI-Intern-Take-Home-Assignment.zip"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def current_hashes() -> dict[str, str]:
    """Map of 'relative/path' -> sha256 for every file in the dataset folder."""
    return {
        p.relative_to(DATASET_DIR).as_posix(): sha256(p.read_bytes())
        for p in sorted(DATASET_DIR.rglob("*")) if p.is_file()
    }


def main() -> int:
    hashes = current_hashes()
    if ZIP_PATH.exists():
        with zipfile.ZipFile(ZIP_PATH) as zf:
            original = {
                info.filename.removeprefix("ceylon-compass-dataset/"): sha256(zf.read(info))
                for info in zf.infolist()
                if info.filename.startswith("ceylon-compass-dataset/") and not info.is_dir()
            }
        if original != hashes:
            print("ERROR: dataset folder differs from the original zip:")
            for path in sorted(set(original) | set(hashes)):
                if original.get(path) != hashes.get(path):
                    print(f"  {path}")
            return 1
        print(f"All {len(hashes)} files match the original zip.")
    HASH_FILE.write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {HASH_FILE.relative_to(REPO_ROOT)} ({len(hashes)} files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
