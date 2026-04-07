"""Shared runtime helpers for local worker scripts."""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import WorkerConfig, initialize_config
from app.worker_logging import log_worker_startup, setup_worker_logging
from _default_paths import _default_paths

def load_local_worker_config(*, context: str) -> WorkerConfig:
    """Load the default local worker config and initialize logging."""
    setup_worker_logging()
    config = initialize_config(_default_paths(PROJECT_ROOT))
    setup_worker_logging(config.paths.log_path)
    log_worker_startup(config, context=context)
    return config

