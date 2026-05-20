"""
Primitives — L0 registered ToolNodes (computer-native operations).

These are the **only** things registered in Python (all higher-level
tools are registered from JSON definitions by the loader).

Raw helpers live in ``core.tools.atoms``.
Scene-graph reconciliation lives in ``core.tools.reconcile``.
"""

from __future__ import annotations

from core.tools.atoms import (                                     # noqa: F401
    atom_move_to, atom_click_at, atom_drag,
    atom_press, atom_hotkey, atom_write,
)
from core.tools.reconcile import (                                 # noqa: F401
    get_scene, save_scene,
    refresh_handles, sync_current_bbox, scan_and_reconcile,
    ensure_handles, _HOVER_DELAY,
)
from core.tools.registry import ToolNode, register


# ===========================================================================
# L0 registered ToolNodes — computer-native operations, app-agnostic
#
# Every higher-level tool (L1+) composes from these atoms.
# ===========================================================================

def _fn_mouse_move(x: int, y: int) -> dict:
    atom_move_to(x, y)
    return {"status": "ok", "tool": "mouse_move", "x": x, "y": y}


def _fn_mouse_click(x: int, y: int, clicks: int = 1) -> dict:
    atom_click_at(x, y, clicks=clicks)
    return {"status": "ok", "tool": "mouse_click",
            "x": x, "y": y, "clicks": clicks}


def _fn_mouse_drag(sx: int, sy: int, tx: int, ty: int) -> dict:
    atom_drag(sx, sy, tx, ty)
    return {"status": "ok", "tool": "mouse_drag",
            "from": [sx, sy], "to": [tx, ty]}


def _fn_key_press(key: str) -> dict:
    atom_press(key)
    return {"status": "ok", "tool": "key_press", "key": key}


def _fn_key_combo(keys: list) -> dict:
    """Press a key chord given as a list, e.g. ["command", "z"]."""
    atom_hotkey(*keys)
    return {"status": "ok", "tool": "key_combo", "keys": keys}


def _fn_keyboard_type(text: str) -> dict:
    atom_write(text)
    return {"status": "ok", "tool": "keyboard_type", "text": text}


N_MOUSE_MOVE = ToolNode(
    name="mouse_move", fn=_fn_mouse_move,
    params=["x", "y"], needs_ui_graph=False,
    description="Move the mouse cursor to absolute screen coordinates (x, y).",
)
N_MOUSE_CLICK = ToolNode(
    name="mouse_click", fn=_fn_mouse_click,
    params=["x", "y", "clicks"], needs_ui_graph=False,
    description="Click at absolute screen coordinates. clicks=1 (default) or 2.",
)
N_MOUSE_DRAG = ToolNode(
    name="mouse_drag", fn=_fn_mouse_drag,
    params=["sx", "sy", "tx", "ty"], needs_ui_graph=False,
    description="Drag from (sx, sy) to (tx, ty).",
)
N_KEY_PRESS = ToolNode(
    name="key_press", fn=_fn_key_press,
    params=["key"], needs_ui_graph=False,
    description="Press a single key by name (e.g. 'Return', 'Escape', 'BackSpace').",
)
N_KEY_COMBO = ToolNode(
    name="key_combo", fn=_fn_key_combo,
    params=["keys"], needs_ui_graph=False,
    description="Press a key chord given as a list, e.g. [\"command\", \"z\"].",
)
N_KEYBOARD_TYPE = ToolNode(
    name="keyboard_type", fn=_fn_keyboard_type,
    params=["text"], needs_ui_graph=False,
    description="Type a string of text into the focused field.",
)

for _n in (
    N_MOUSE_MOVE, N_MOUSE_CLICK, N_MOUSE_DRAG,
    N_KEY_PRESS, N_KEY_COMBO, N_KEYBOARD_TYPE,
):
    register(_n)
