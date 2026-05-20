"""
Atoms — raw pyautogui wrappers.

Single-call mouse/keyboard operations with explicit coords/keys/text.
No domain knowledge, no UI-graph awareness, no scene-graph mutations.

These are the building blocks used by:
  - ``core.tools.actions``          (L1 generic actions)
  - ``domains.drawio.operations``   (L1 drawio operands)
  - ``core.tools.primitives``       (L0 registered ToolNodes)
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import pyautogui

from core import config

logger = logging.getLogger(__name__)


# ===========================================================================
# Mouse
# ===========================================================================

def atom_move_to(x: int, y: int) -> None:
    """Move the cursor to (x, y) without clicking."""
    pyautogui.moveTo(x, y)


def atom_click_at(x: int, y: int, clicks: int = 1, hold: float = 0.08) -> None:
    """Click at (x, y) with explicit down/up + hold so drawio registers it."""
    pyautogui.moveTo(x, y)
    time.sleep(0.05)
    for i in range(clicks):
        pyautogui.mouseDown()
        time.sleep(hold)
        pyautogui.mouseUp()
        if i + 1 < clicks:
            time.sleep(0.08)


def atom_drag(
    sx: int, sy: int, tx: int, ty: int,
    duration: Optional[float] = None, hold_pre: float = 0.1,
) -> None:
    """Drag from (sx, sy) to (tx, ty)."""
    if duration is None:
        duration = config.drag_duration()
    pyautogui.moveTo(sx, sy)
    time.sleep(0.05)
    pyautogui.mouseDown()
    time.sleep(hold_pre)
    pyautogui.moveTo(tx, ty, duration=duration)
    pyautogui.mouseUp()


# ===========================================================================
# Keyboard
# ===========================================================================

def atom_press(key: str) -> None:
    """Press a single key."""
    pyautogui.hotkey(key)


def atom_hotkey(*keys: str) -> None:
    """Press a key combo (e.g. ``"command", "z"``)."""
    pyautogui.hotkey(*keys)


def atom_write(text: str, interval: Optional[float] = None) -> None:
    """Type *text* into the focused field."""
    if interval is None:
        interval = config.type_interval()
    pyautogui.write(text, interval=interval)
