"""Structured logging setup for the data-agent baseline.

Two-channel logging:

* **stderr** via :class:`rich.logging.RichHandler` — colourised, human-friendly
  for interactive runs and the KDD Cup evaluation platform's container logs.
* **per-task file** ``<task_output_dir>/agent.log`` (plain text) — one file per
  task so individual failures can be re-examined without sifting a global log.

Configuration via environment variables:

* ``DABENCH_LOG_LEVEL`` — root level for the ``data_agent_baseline`` namespace
  (default ``INFO``). Accepts standard names: ``DEBUG``/``INFO``/``WARNING``/...
* ``DABENCH_LOG_TO_FILE`` — set to ``0``/``false`` to disable per-task file
  logging (still keeps the stderr stream). Default enabled.

Typical usage:

    # CLI entry: install the stderr handler exactly once.
    from data_agent_baseline.logging_setup import init_global_logging
    init_global_logging()

    # Per-task: bind a file handler scoped to one task_output_dir.
    from data_agent_baseline.logging_setup import bind_task_log_file
    with bind_task_log_file(task_output_dir):
        run_single_task(...)

    # Module-level loggers anywhere:
    import logging
    logger = logging.getLogger(__name__)
    logger.info("planner emitted %d nodes", len(dag.nodes))
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from rich.console import Console
from rich.logging import RichHandler

# Logger namespace shared by every module under ``src/data_agent_baseline``.
# We attach handlers to this parent logger so per-module ``getLogger(__name__)``
# calls automatically inherit them.
PROJECT_LOGGER_NAME = "data_agent_baseline"

# Plain-text format for the per-task file handler. Designed to be greppable
# and to surface the call site (module + line) so that grep results can be
# clicked through in editors.
FILE_LOG_FORMAT = (
    "%(asctime)s [%(levelname)-7s] %(name)s:%(lineno)d | %(message)s"
)
FILE_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

# Sentinel attribute we set on handlers we create ourselves, so that repeated
# ``init_global_logging`` calls don't double-attach.
_OWNED_BY_DABENCH_ATTR = "_dabench_owned"


def _resolve_log_level() -> int:
    """Read ``DABENCH_LOG_LEVEL`` env var → ``logging`` integer level."""
    raw = os.environ.get("DABENCH_LOG_LEVEL", "INFO").strip().upper()
    # ``getLevelName`` returns the int if given a name, or the string
    # ``"Level <n>"`` when the name is unknown — guard against that.
    resolved = logging.getLevelName(raw)
    if isinstance(resolved, int):
        return resolved
    return logging.INFO


def _file_logging_enabled() -> bool:
    raw = os.environ.get("DABENCH_LOG_TO_FILE", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def init_global_logging() -> logging.Logger:
    """Attach the stderr ``RichHandler`` to the project logger (idempotent).

    Safe to call multiple times: subsequent calls only re-apply the level
    from the environment and skip handler creation if one we own is already
    attached. Returns the project root logger so callers can stash it.
    """
    project_logger = logging.getLogger(PROJECT_LOGGER_NAME)
    project_logger.setLevel(_resolve_log_level())
    # Don't bubble up to the root logger — avoids duplicate output when the
    # host process (e.g. a test runner) already configured root logging.
    project_logger.propagate = False

    already_attached = any(
        getattr(handler, _OWNED_BY_DABENCH_ATTR, False)
        and isinstance(handler, RichHandler)
        for handler in project_logger.handlers
    )
    if already_attached:
        return project_logger

    # Pin the RichHandler to ``stderr`` so user-facing CLI output (rich tables
    # printed via ``console.print``) on stdout stays uncluttered, and the
    # evaluation platform's stderr capture still receives logs.
    stderr_console = Console(stderr=True)
    rich_handler = RichHandler(
        console=stderr_console,
        show_time=True,
        show_level=True,
        show_path=False,
        markup=False,
        rich_tracebacks=True,
        log_time_format="[%H:%M:%S]",
    )
    rich_handler.setLevel(_resolve_log_level())
    # RichHandler renders level/time itself; only the message goes through
    # the formatter. Keep the format minimal.
    rich_handler.setFormatter(logging.Formatter("%(name)s | %(message)s"))
    setattr(rich_handler, _OWNED_BY_DABENCH_ATTR, True)
    project_logger.addHandler(rich_handler)
    return project_logger


@contextmanager
def bind_task_log_file(task_output_dir: Path) -> Iterator[Path | None]:
    """Attach a per-task file handler for the duration of a ``with`` block.

    The file lives at ``<task_output_dir>/agent.log`` and captures every log
    record at the configured level for the ``data_agent_baseline`` namespace.

    On exit the handler is detached and closed so subsequent tasks' logs do
    not bleed into earlier files.

    Yields the resolved log file path (``None`` when file logging is
    disabled via ``DABENCH_LOG_TO_FILE``) so callers can mention it in
    their own output.
    """
    if not _file_logging_enabled():
        yield None
        return

    project_logger = logging.getLogger(PROJECT_LOGGER_NAME)
    # Make sure the global handler exists; users can still use ``bind_task_log_file``
    # directly in tests without calling ``init_global_logging`` first.
    init_global_logging()

    task_output_dir.mkdir(parents=True, exist_ok=True)
    log_path = task_output_dir / "agent.log"

    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setLevel(_resolve_log_level())
    file_handler.setFormatter(
        logging.Formatter(fmt=FILE_LOG_FORMAT, datefmt=FILE_DATE_FORMAT)
    )
    setattr(file_handler, _OWNED_BY_DABENCH_ATTR, True)
    project_logger.addHandler(file_handler)

    try:
        yield log_path
    finally:
        project_logger.removeHandler(file_handler)
        try:
            file_handler.close()
        except Exception:  # noqa: BLE001
            # Closing must never crash the surrounding task — the records we
            # care about have already been flushed by removeHandler().
            print(
                f"[logging_setup] failed to close file handler for {log_path}",
                file=sys.stderr,
            )


def get_logger(name: str) -> logging.Logger:
    """Convenience wrapper so callers don't need to remember the namespace.

    Equivalent to ``logging.getLogger(name)`` but documents intent: every
    logger created this way inherits handlers from ``PROJECT_LOGGER_NAME``.
    """
    return logging.getLogger(name)
