"""
Shared test/demo helpers — countdown, path setup, canvas cleaning.

Consolidates boilerplate duplicated across test_auto, test_manual,
demo_integration, and test_collect_icons.
"""

from __future__ import annotations

import os
import sys
import time

# ---------------------------------------------------------------------------
# Path setup — call once at the top of scripts that aren't installed as
# packages.  Ensures ``import core`` resolves to the project root.
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def setup_path() -> None:
    """Add the project root to ``sys.path`` (idempotent)."""
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Countdown — gives the user time to switch to draw.io
# ---------------------------------------------------------------------------

def countdown(seconds: int | None = None) -> None:
    """Print a countdown. *seconds* defaults to config.countdown_seconds()."""
    if seconds is None:
        from core import config
        seconds = config.countdown_seconds()
    for i in range(seconds, 0, -1):
        print(f"  {i}s …")
        time.sleep(1)
    print("  GO!\n")
