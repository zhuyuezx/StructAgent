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
from typing import Optional

from core import config
from core.target import manager as target_manager

logger = logging.getLogger(__name__)


# ===========================================================================
# Mouse
# ===========================================================================

def atom_move_to(x: int, y: int) -> None:
    """Move the cursor to (x, y) without clicking."""
    target_manager.input_controller().move_to(x, y)


def atom_click_at(x: int, y: int, clicks: int = 1, hold: float = 0.08) -> None:
    """Click at (x, y) with explicit down/up + hold so drawio registers it."""
    target_manager.input_controller().click_at(x, y, clicks=clicks, hold=hold)


def atom_drag(
    sx: int, sy: int, tx: int, ty: int,
    duration: Optional[float] = None, hold_pre: float = 0.1,
) -> None:
    """Drag from (sx, sy) to (tx, ty)."""
    if duration is None:
        duration = config.drag_duration()
    target_manager.input_controller().drag(sx, sy, tx, ty, duration=duration, hold_pre=hold_pre)


# ===========================================================================
# Keyboard
# ===========================================================================

def atom_press(key: str) -> None:
    """Press a single key."""
    target_manager.input_controller().press(key)


def atom_hotkey(*keys: str) -> None:
    """Press a key combo (e.g. ``"command", "z"``)."""
    target_manager.input_controller().hotkey(*keys)


def atom_write(text: str, interval: Optional[float] = None) -> None:
    """Type *text* into the focused field."""
    if interval is None:
        interval = config.type_interval()
    target_manager.input_controller().write(text, interval=interval)
