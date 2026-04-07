"""Shared worker logging setup for file + console operational logs."""

import logging
import sys
from pathlib import Path

from app.config import WorkerConfig


# ---------------------------------------------------- CONSTANTS ----
LOGGER_NAME = "job_search_engine"
LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
HANDLER_KIND_ATTR = "_job_search_engine_handler_kind"
FILE_PATH_ATTR = "_job_search_engine_file_path"


# ---------------------------------------------------- ENTRYPOINTS ----
def setup_worker_logging(log_path: Path | None = None) -> logging.Logger:
    """Configure the shared worker logger for console and optional file output."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    _ensure_console_handler(logger, formatter)
    if log_path is not None:
        _ensure_file_handler(logger, formatter, log_path.expanduser().resolve())

    return logger


def get_logger(component: str | None = None) -> logging.Logger:
    """Return the shared worker logger or a named child logger."""
    if not component:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{component}")


def log_worker_startup(config: WorkerConfig, *, context: str = "worker") -> None:
    """Emit a one-line worker startup summary after config loads."""
    enabled_queries = sum(1 for query in config.queries if query.enabled)
    get_logger("bootstrap").info(
        "Worker startup (%s): db=%s report_dir=%s log=%s scoring_version=%s enabled_queries=%s",
        context,
        config.paths.db_path,
        config.paths.report_export_dir,
        config.paths.log_path,
        config.scoring_config.version,
        enabled_queries,
    )


# ---------------------------------------------------- HELPERS ----
def _ensure_console_handler(
    logger: logging.Logger,
    formatter: logging.Formatter,
) -> None:
    """Attach one stdout console handler when missing."""
    for handler in logger.handlers:
        if getattr(handler, HANDLER_KIND_ATTR, None) == "console":
            handler.setFormatter(formatter)
            return

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(formatter)
    setattr(handler, HANDLER_KIND_ATTR, "console")
    logger.addHandler(handler)


def _ensure_file_handler(
    logger: logging.Logger,
    formatter: logging.Formatter,
    resolved_log_path: Path,
) -> None:
    """Attach one append-mode file handler for the configured worker log path."""
    matching_handler: logging.Handler | None = None
    stale_handlers: list[logging.Handler] = []

    for handler in logger.handlers:
        if getattr(handler, HANDLER_KIND_ATTR, None) != "file":
            continue
        if getattr(handler, FILE_PATH_ATTR, None) == str(resolved_log_path):
            matching_handler = handler
        else:
            stale_handlers.append(handler)

    for handler in stale_handlers:
        logger.removeHandler(handler)
        handler.close()

    if matching_handler is not None:
        matching_handler.setFormatter(formatter)
        return

    resolved_log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(resolved_log_path, mode="a", encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(formatter)
    setattr(handler, HANDLER_KIND_ATTR, "file")
    setattr(handler, FILE_PATH_ATTR, str(resolved_log_path))
    logger.addHandler(handler)
