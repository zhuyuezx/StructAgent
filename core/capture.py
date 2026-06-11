"""
Capture — Screenshot capture module.

Single responsibility: take a screenshot and save it to disk.
"""

from __future__ import annotations

import logging
import os

from core import config
from core.target import manager as target_manager

logger = logging.getLogger(__name__)


def screenshot(filename: str = "state.png") -> str:
    """
    Capture the current screen and save to the screenshots directory.

    Args:
        filename: Image filename (saved inside ``config.screenshots_dir()``).

    Returns:
        Absolute path of the saved screenshot.
    """
    save_dir = config.screenshots_dir()
    path = os.path.join(save_dir, filename)
    target_manager.screenshot(path)
    abs_path = os.path.abspath(path)
    logger.info("Screenshot → %s", abs_path)
    return abs_path
