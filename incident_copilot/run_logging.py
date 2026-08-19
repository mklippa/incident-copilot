"""Shared run-logging setup.

Every entry-point script gets console output plus a per-run, per-script
timestamped log file under output/<script_name>/, so a past run can be
found and text-searched afterward (e.g. `grep -r "iteration cap" output/`).

RUN_TIMESTAMP is computed once at import time, so if one script imports
another (coordinator.py imports classify_loop.py), both share a single
timestamp for that process rather than drifting apart by a few seconds.
"""

import logging
from datetime import UTC, datetime

from incident_copilot.paths import OUTPUT_DIR

RUN_TIMESTAMP = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%SZ")


def configure_run_logging(script_name: str) -> logging.Logger:
    log_dir = OUTPUT_DIR / script_name
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / f"{RUN_TIMESTAMP}.log"),
        ],
        force=True,
    )
    return logging.getLogger(script_name)
