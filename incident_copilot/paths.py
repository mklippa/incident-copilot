"""Filesystem paths shared across incident_copilot scripts.

Computed once here instead of each module independently re-deriving
REPO_ROOT from its own __file__.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"
RUNBOOKS_DIR = REPO_ROOT / "runbooks"
LOGS_DIR = REPO_ROOT / "logs"

DATA_DIR.mkdir(parents=True, exist_ok=True)
