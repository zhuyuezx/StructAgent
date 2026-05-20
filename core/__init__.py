"""StructAgent core — domain-agnostic framework.

Logging Architecture
────────────────────
Configured automatically on first ``import core``.  Three handlers:

  1. **Console** (stderr) — INFO level, compact, coloured by level.
  2. **Main log file** (``logs/agent.log``) — DEBUG level, timestamped,
     rotated at 5 MB with 3 backups (→ max ~20 MB on disk).
  3. **Error log file** (``logs/errors.log``) — WARNING+ only, same
     rotation policy.  Quick triage file for failures.

Subsystem filtering
~~~~~~~~~~~~~~~~~~~
Every module uses ``logging.getLogger(__name__)``, so you can raise /
lower individual subsystems at runtime::

    logging.getLogger("core.agents.executor").setLevel(logging.DEBUG)
    logging.getLogger("core.perception.label").setLevel(logging.WARNING)

Re-configuration
~~~~~~~~~~~~~~~~
Call ``core.setup_logging(level=..., log_dir=...)`` to override defaults
(e.g. from a notebook that wants verbose console output).
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")

# Rotation policy
_MAX_BYTES = 5 * 1024 * 1024   # 5 MB per file
_BACKUP_COUNT = 3              # keep 3 old rotated files

_initialised = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_logging(
    *,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    log_dir: Optional[str] = None,
    force: bool = False,
) -> None:
    """Configure the root logger with console + file handlers.

    Parameters
    ----------
    console_level : int
        Minimum level for the stderr console handler (default ``INFO``).
        Pass ``logging.DEBUG`` for verbose console output.
    file_level : int
        Minimum level for the rotating file handler (default ``DEBUG``).
    log_dir : str | None
        Directory for log files.  Defaults to ``<project_root>/logs/``.
    force : bool
        If True, tear down existing handlers and re-configure.

    This function is **idempotent** — calling it multiple times without
    ``force=True`` is a no-op after the first call.
    """
    global _initialised
    if _initialised and not force:
        return
    _initialised = True

    log_dir = log_dir or _DEFAULT_LOG_DIR
    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()

    # Tear down any prior handlers when force-reconfiguring.
    if force:
        for h in root.handlers[:]:
            h.close()
            root.removeHandler(h)

    # Avoid duplicate handlers if someone already configured the root.
    if root.handlers:
        return

    root.setLevel(logging.DEBUG)

    # ── 1. Console handler (stderr) ───────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter(
        "%(levelname)-5s  %(name)s: %(message)s",
    ))
    root.addHandler(console)

    # ── 2. Main log file (DEBUG+, rotating) ───────────────────────────
    main_log = os.path.join(log_dir, "agent.log")
    file_handler = RotatingFileHandler(
        main_log,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-5s  [%(name)s]  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(file_handler)

    # ── 3. Error log file (WARNING+, rotating) ────────────────────────
    error_log = os.path.join(log_dir, "errors.log")
    error_handler = RotatingFileHandler(
        error_log,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-5s  [%(name)s]  %(funcName)s:%(lineno)d  "
        "%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(error_handler)

    logging.getLogger(__name__).debug(
        "Logging initialised — console=%s  file=%s  dir=%s",
        logging.getLevelName(console_level),
        logging.getLevelName(file_level),
        log_dir,
    )


# Auto-configure on first import (idempotent).
setup_logging()
