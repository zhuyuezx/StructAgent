"""
Primitives — app-agnostic atoms and shared state helpers.

Two things live here:

  1. **Raw atom helpers** (``atom_*``) — single-call pyautogui wrappers
     with explicit coords/keys/text. NOT registered as ToolNodes; they
     are the building blocks used by ``core.tools.actions`` (L1 generic
     actions) and ``domains.drawio.operations`` (L0 drawio operands).

  2. **Shared scene/handle utilities** — small helpers that thread
     ``ui_graph['scene_graph']`` state and detect selection handles.
     Used by both ``actions.py`` and ``domains.drawio.operations``.
     NOT registered as ToolNodes.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import pyautogui

from core import config
from core.capture import screenshot as _capture_screenshot
from core.perception.handles import detect_handles, SelectionHandles
from core.state import scene_graph as _sg
from core.tools.registry import ToolNode, register


# ===========================================================================
# Scene graph helpers
# ===========================================================================

def _get_scene(ui_graph: Dict[str, Any]) -> Dict[str, Any]:
    """Lazy-load the scene_graph onto ui_graph['scene_graph']."""
    sg = ui_graph.get("scene_graph")
    if sg is None:
        sg = _sg.load()
        ui_graph["scene_graph"] = sg
    return sg


def _save_scene(ui_graph: Dict[str, Any]) -> None:
    sg = ui_graph.get("scene_graph")
    if sg is not None:
        _sg.save(sg)


# ===========================================================================
# Raw atom helpers — bare pyautogui wrappers, NOT registered ToolNodes
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


# ===========================================================================
# Selection-handle refresh helpers (shared by actions + drawio/operations)
# ===========================================================================

_HOVER_DELAY = 0.7


def _refresh_handles(
    ui_graph: Dict[str, Any], hint_bbox: Optional[tuple] = None,
) -> SelectionHandles:
    """Snapshot the screen, detect selection handles, store on ui_graph."""
    path = _capture_screenshot("_handles_scan_a.png")
    handles = detect_handles(path)

    bbox = handles.shape_bbox or hint_bbox
    if bbox and (not handles.extend or len(handles.extend) < 4):
        cx, cy = bbox[0] + bbox[2] // 2, bbox[1] + bbox[3] // 2
        atom_move_to(cx, cy)
        time.sleep(_HOVER_DELAY)
        path = _capture_screenshot("_handles_scan_b.png")
        handles = detect_handles(path)

    ui_graph["selected_handles"] = handles.to_dict() if handles.is_valid() else None
    return handles


def _sync_current_bbox(ui_graph: Dict[str, Any]) -> None:
    """If the currently-selected scene_graph object has no bbox, escape +
    scan to fill it."""
    sg = _get_scene(ui_graph)
    sel = _sg.get_selected(sg)
    if sel is None or sel.get("bbox") is not None:
        return
    target_id = sel["id"]
    atom_press("Escape")
    time.sleep(0.3)
    _scan_and_reconcile(ui_graph, op_name="sync_current_bbox",
                        target_id=target_id)


def _scan_and_reconcile(
    ui_graph: Dict[str, Any], op_name: str,
    *, hint_bbox: Optional[tuple] = None,
    target_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Re-detect handles, update the matching scene_graph object's bbox."""
    handles = _refresh_handles(ui_graph, hint_bbox=hint_bbox)
    sg = _get_scene(ui_graph)
    if not handles.is_valid() or not handles.shape_bbox:
        _sg.set_selected(sg, None)
        _save_scene(ui_graph)
        return None

    new_bbox = list(handles.shape_bbox)
    target: Optional[Dict[str, Any]] = None
    if target_id:
        target = _sg.find_by_id(sg, target_id)
    if target is None:
        for o in reversed(sg["objects"]):
            if o.get("bbox") is None:
                target = o
                break
    if target is None:
        target = _sg.find_closest_to_bbox(sg, new_bbox)

    if target is not None:
        _sg.update_object_bbox(sg, target["id"], new_bbox, op_name=op_name)
        _sg.set_selected(sg, target["id"])
    _save_scene(ui_graph)
    return target


def _ensure_handles(ui_graph: Dict[str, Any]) -> Optional[dict]:
    """Return cached handles dict, refreshing once (and escape+retry) if absent."""
    h = ui_graph.get("selected_handles")
    if h:
        return h
    _refresh_handles(ui_graph)
    h = ui_graph.get("selected_handles")
    if h:
        return h
    print("  (no handles detected — sending defensive Escape)")
    atom_press("Escape")
    time.sleep(0.3)
    _scan_and_reconcile(ui_graph, op_name="defensive_escape")
    return ui_graph.get("selected_handles")


# ===========================================================================
# L0 registered ToolNodes — computer-native operations, app-agnostic
#
# These are the only things in this module that get registered.  Every
# higher-level tool (L1+) composes from these atoms.
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
