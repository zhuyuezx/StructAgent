"""
Primitives — L0 atomic tools.

Domain-agnostic mouse/keyboard primitives. Each function wraps a single
``pyautogui`` call and returns a status dict. ToolNodes are self-registered
at import time.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import pyautogui

from core import config
from core.capture import screenshot as _capture_screenshot
from core.perception.handles import detect_handles, SelectionHandles
from core.tools.registry import (
    ToolNode, register, resolve_tool, resolve_node,
)


# ===========================================================================
# Selection-handle refresh helper
# ===========================================================================

_HOVER_DELAY = 0.7  # seconds — drawio takes ~0.5s after hover to render arrows


def _refresh_handles(
    ui_graph: Dict[str, Any], hint_bbox: Optional[tuple] = None,
) -> SelectionHandles:
    """Snapshot the screen, detect selection handles, store on ui_graph.

    Two-pass when arrows aren't visible yet:
      1. Initial capture — finds the 8 resize dots (always visible whenever
         a shape is selected).
      2. If we got a shape bbox, hover its center so drawio renders the
         N/S/E/W extend arrows, then re-capture and re-detect.

    The result is stored under ``ui_graph['selected_handles']`` as a plain
    dict (so it survives JSON round-trips). Returns the SelectionHandles
    object as well, for callers who want it immediately.
    """
    path = _capture_screenshot("_handles_scan_a.png")
    handles = detect_handles(path)

    bbox = handles.shape_bbox or hint_bbox
    if bbox and (not handles.extend or len(handles.extend) < 4):
        cx, cy = bbox[0] + bbox[2] // 2, bbox[1] + bbox[3] // 2
        pyautogui.moveTo(cx, cy)
        time.sleep(_HOVER_DELAY)
        path = _capture_screenshot("_handles_scan_b.png")
        handles = detect_handles(path)

    ui_graph["selected_handles"] = handles.to_dict() if handles.is_valid() else None
    return handles


# ===========================================================================
# Leaf tool functions (level 0 — single atomic operations)
# ===========================================================================

def _fn_place_shape(ui_graph: Dict[str, Any], tool_name: str) -> dict:
    """
    Place a sidebar shape onto the canvas.

    drawio auto-places the shape at a default canvas location on a single
    click of the sidebar icon. The click selects the shape but does NOT
    enter text-edit mode, so we follow up with Enter — drawio's "edit
    label" shortcut on a selected shape — to leave it ready to receive
    a label. (F2 would also work in drawio, but on macOS the function
    keys default to hardware controls and may not reach the app.)
    """
    x, y = resolve_tool(ui_graph, tool_name)
    print(f"  [L0] place_shape('{tool_name}') → click ({x}, {y}) + Enter")
    pyautogui.click(x, y)
    time.sleep(0.3)
    pyautogui.press("enter")
    return {"status": "ok", "tool": "place_shape", "tool_name": tool_name,
            "x": x, "y": y}


def _fn_type_label(text: str) -> dict:
    """
    Type *text* into the currently focused element.

    Uses ``pyautogui.write`` (NOT ``typewrite``) so capital letters and
    punctuation are typed correctly via Shift modifiers.
    """
    print(f"  [L0] type_label('{text}')")
    pyautogui.write(text, interval=config.type_interval())
    return {"status": "ok", "tool": "type_label", "text": text}


def _fn_press_escape(ui_graph: Optional[Dict[str, Any]] = None) -> dict:
    print("  [L0] press_escape")
    pyautogui.hotkey("Escape")
    # Escape from text-edit mode leaves the shape selected — refresh handles.
    if ui_graph is not None:
        time.sleep(0.3)
        _refresh_handles(ui_graph)
    return {"status": "ok", "tool": "press_escape"}


def _fn_scan_handles(ui_graph: Dict[str, Any]) -> dict:
    """Force a fresh handle scan of the currently-selected shape."""
    print("  [L0] scan_handles")
    handles = _refresh_handles(ui_graph)
    return {
        "status": "ok" if handles.is_valid() else "no_selection",
        "tool": "scan_handles",
        "handles": handles.to_dict(),
    }


# ===========================================================================
# Semantic shape-manipulation operands (use detected handles internally)
# ===========================================================================

# Map a compass direction → which of the 8 resize handles to grab, and the
# unit vector to drag that handle in. The vector is multiplied by the
# ``amount`` arg to compute the drop point.
_RESIZE_HANDLE_FOR_DIRECTION: Dict[str, str] = {
    "n":  "tm", "s":  "bm", "e":  "mr", "w":  "ml",
    "ne": "tr", "nw": "tl", "se": "br", "sw": "bl",
}
_RESIZE_DIRECTION_VECTOR: Dict[str, tuple] = {
    "n":  (0, -1),  "s":  (0, 1),   "e":  (1, 0),   "w":  (-1, 0),
    "ne": (1, -1),  "nw": (-1, -1), "se": (1, 1),   "sw": (-1, 1),
}


def _ensure_handles(ui_graph: Dict[str, Any]) -> Optional[dict]:
    """Return the cached handles dict, refreshing once if absent."""
    h = ui_graph.get("selected_handles")
    if h:
        return h
    handles = _refresh_handles(ui_graph)
    return ui_graph.get("selected_handles")


def _fn_resize_shape(
    ui_graph: Dict[str, Any], direction: str, amount: int,
) -> dict:
    """Resize the selected shape by dragging the appropriate handle.

    ``direction`` is a compass name (n/s/e/w/ne/nw/se/sw). ``amount`` is in
    logical pixels — positive grows the shape outward in that direction,
    negative shrinks it inward.
    """
    direction = direction.lower().strip()
    if direction not in _RESIZE_HANDLE_FOR_DIRECTION:
        return {"status": "error", "tool": "resize_shape",
                "error": f"unknown direction '{direction}' — expected one of "
                         f"{sorted(_RESIZE_HANDLE_FOR_DIRECTION)}"}

    h = _ensure_handles(ui_graph)
    if not h or not h.get("resize"):
        return {"status": "error", "tool": "resize_shape",
                "error": "no shape selected — call scan_handles or click_node first"}

    slot = _RESIZE_HANDLE_FOR_DIRECTION[direction]
    if slot not in h["resize"]:
        return {"status": "error", "tool": "resize_shape",
                "error": f"resize handle '{slot}' for direction '{direction}' not detected"}

    sx, sy = h["resize"][slot]
    dx, dy = _RESIZE_DIRECTION_VECTOR[direction]
    tx, ty = int(sx + dx * amount), int(sy + dy * amount)

    print(f"  [L0] resize_shape('{direction}', {amount}) → "
          f"drag handle '{slot}' ({sx},{sy}) → ({tx},{ty})")
    pyautogui.moveTo(sx, sy)
    time.sleep(0.1)
    pyautogui.mouseDown()
    time.sleep(0.1)
    pyautogui.moveTo(tx, ty, duration=config.drag_duration())
    pyautogui.mouseUp()
    time.sleep(0.4)
    _refresh_handles(ui_graph, hint_bbox=tuple(h["shape_bbox"]) if h.get("shape_bbox") else None)
    return {"status": "ok", "tool": "resize_shape",
            "direction": direction, "amount": amount,
            "from": [sx, sy], "to": [tx, ty]}


def _fn_extend_shape(ui_graph: Dict[str, Any], direction: str) -> dict:
    """Click the N/S/E/W extend arrow to auto-create a connected shape."""
    direction = direction.lower().strip()
    if direction not in ("n", "s", "e", "w"):
        return {"status": "error", "tool": "extend_shape",
                "error": f"unknown direction '{direction}' — expected n/s/e/w"}

    h = _ensure_handles(ui_graph)
    if not h or not h.get("extend"):
        return {"status": "error", "tool": "extend_shape",
                "error": "no shape selected (or extend arrows not visible) — "
                         "call scan_handles first"}
    if direction not in h["extend"]:
        return {"status": "error", "tool": "extend_shape",
                "error": f"extend arrow '{direction}' not detected"}

    x, y = h["extend"][direction]
    print(f"  [L0] extend_shape('{direction}') → click ({x}, {y})")
    pyautogui.moveTo(x, y)
    time.sleep(0.1)
    pyautogui.mouseDown()
    time.sleep(0.08)
    pyautogui.mouseUp()
    time.sleep(0.6)
    # Extend creates a NEW shape that becomes selected — refresh against it.
    _refresh_handles(ui_graph)
    return {"status": "ok", "tool": "extend_shape", "direction": direction,
            "at": [x, y]}


def _fn_rotate_shape(ui_graph: Dict[str, Any], angle_degrees: float) -> dict:
    """Rotate the selected shape by dragging the rotate handle around the
    shape center by ``angle_degrees`` (positive = clockwise)."""
    import math

    h = _ensure_handles(ui_graph)
    if not h or not h.get("rotate") or not h.get("shape_bbox"):
        return {"status": "error", "tool": "rotate_shape",
                "error": "no rotate handle visible — call scan_handles first"}

    rx, ry = h["rotate"]
    bx, by, bw, bh = h["shape_bbox"]
    cx, cy = bx + bw // 2, by + bh // 2

    dx, dy = rx - cx, ry - cy
    rad = math.radians(angle_degrees)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    new_dx = dx * cos_a - dy * sin_a
    new_dy = dx * sin_a + dy * cos_a
    tx, ty = int(cx + new_dx), int(cy + new_dy)

    print(f"  [L0] rotate_shape({angle_degrees}°) → "
          f"drag rotate ({rx},{ry}) → ({tx},{ty})")
    pyautogui.moveTo(rx, ry)
    time.sleep(0.1)
    pyautogui.mouseDown()
    time.sleep(0.1)
    pyautogui.moveTo(tx, ty, duration=config.drag_duration())
    pyautogui.mouseUp()
    time.sleep(0.4)
    _refresh_handles(ui_graph)
    return {"status": "ok", "tool": "rotate_shape",
            "angle_degrees": angle_degrees,
            "from": [rx, ry], "to": [tx, ty]}


def _fn_press_enter() -> dict:
    print("  [L0] press_enter")
    pyautogui.hotkey("Return")
    return {"status": "ok", "tool": "press_enter"}


def _fn_press_delete() -> dict:
    print("  [L0] press_delete")
    pyautogui.hotkey("BackSpace")
    return {"status": "ok", "tool": "press_delete"}


def _fn_select_all() -> dict:
    print("  [L0] select_all (Cmd+A)")
    pyautogui.hotkey("command", "a")
    return {"status": "ok", "tool": "select_all"}


def _fn_click_empty_canvas(ui_graph: Optional[Dict[str, Any]] = None) -> dict:
    x, y = config.empty_canvas_point()
    print(f"  [L0] click_empty_canvas → ({x}, {y})")
    pyautogui.click(x, y)
    if ui_graph is not None:
        ui_graph["selected_handles"] = None
    return {"status": "ok", "tool": "click_empty_canvas", "x": x, "y": y}


def _fn_click_node(ui_graph: Dict[str, Any], node_ref: str, clicks: int = 1) -> dict:
    node = resolve_node(ui_graph, node_ref)
    x, y = node["x"], node["y"]
    print(f"  [L0] click_node('{node_ref}', clicks={clicks}) → ({x}, {y})")
    # Explicit down/up with hold — drawio ignores too-fast synthetic clicks.
    pyautogui.moveTo(x, y)
    time.sleep(0.1)
    for i in range(clicks):
        pyautogui.mouseDown()
        time.sleep(0.08)
        pyautogui.mouseUp()
        if i + 1 < clicks:
            time.sleep(0.08)
    time.sleep(0.4)
    handles = _refresh_handles(ui_graph)
    return {"status": "ok", "tool": "click_node", "node_ref": node_ref,
            "x": x, "y": y,
            "handles_found": handles.is_valid()}


def _fn_double_click_node(ui_graph: Dict[str, Any], node_ref: str) -> dict:
    return _fn_click_node(ui_graph, node_ref, clicks=2)


def _fn_drag_node(
    ui_graph: Dict[str, Any], node_ref: str, target_x: int, target_y: int,
) -> dict:
    node = resolve_node(ui_graph, node_ref)
    sx, sy = node["x"], node["y"]
    dur = config.drag_duration()
    print(f"  [L0] drag_node('{node_ref}') → ({sx},{sy}) → ({target_x},{target_y})")
    pyautogui.moveTo(sx, sy)
    pyautogui.mouseDown()
    pyautogui.moveTo(target_x, target_y, duration=dur)
    pyautogui.mouseUp()
    return {"status": "ok", "tool": "drag_node", "node_ref": node_ref,
            "from": [sx, sy], "to": [target_x, target_y]}


def _fn_drag_node_near(
    ui_graph: Dict[str, Any], node_ref: str, reference_node: str,
    offset_x: int = 200, offset_y: int = 0,
) -> dict:
    ref = resolve_node(ui_graph, reference_node)
    return _fn_drag_node(ui_graph, node_ref, ref["x"] + offset_x, ref["y"] + offset_y)


def _fn_resize_node(
    ui_graph: Dict[str, Any], node_ref: str, new_width: int, new_height: int,
) -> dict:
    node = resolve_node(ui_graph, node_ref)
    x, y = node["x"], node["y"]
    w, h = node.get("w", 120), node.get("h", 60)
    handle_x, handle_y = x + w // 2, y + h // 2
    new_hx, new_hy = x + new_width // 2, y + new_height // 2
    print(f"  [L0] resize_node('{node_ref}', {new_width}×{new_height})")
    pyautogui.click(x, y)
    time.sleep(0.2)
    pyautogui.moveTo(handle_x, handle_y)
    pyautogui.mouseDown()
    pyautogui.moveTo(new_hx, new_hy, duration=0.3)
    pyautogui.mouseUp()
    return {"status": "ok", "tool": "resize_node", "node_ref": node_ref,
            "new_size": [new_width, new_height]}


def _fn_hotkey(*keys: str) -> dict:
    combo = " + ".join(keys)
    print(f"  [L0] hotkey({combo})")
    pyautogui.hotkey(*keys)
    return {"status": "ok", "tool": "hotkey", "keys": list(keys)}


def _fn_undo() -> dict:
    print("  [L0] undo (Cmd+Z)")
    pyautogui.hotkey("command", "z")
    return {"status": "ok", "tool": "undo"}


# ===========================================================================
# Leaf ToolNodes (level 0)
# ===========================================================================

N_PLACE_SHAPE = ToolNode(
    name="place_shape", fn=_fn_place_shape,
    params=["tool_name"], needs_ui_graph=True,
    description="Click a sidebar shape to place it on the canvas.",
)

N_TYPE_LABEL = ToolNode(
    name="type_label", fn=_fn_type_label,
    params=["text"], needs_ui_graph=False,
    description="Type a text label into the active shape.",
)

N_PRESS_ESCAPE = ToolNode(
    name="press_escape", fn=_fn_press_escape,
    params=[], needs_ui_graph=True,
    description=(
        "Press Escape to exit text editing or deselect. "
        "When a shape stays selected afterwards, the selection handles are "
        "auto-refreshed into the prompt's Active selection block."
    ),
)

N_PRESS_ENTER = ToolNode(
    name="press_enter", fn=_fn_press_enter,
    params=[], needs_ui_graph=False,
    description="Press Enter to confirm input.",
)

N_PRESS_DELETE = ToolNode(
    name="press_delete", fn=_fn_press_delete,
    params=[], needs_ui_graph=False,
    description="Press Delete to remove the selected element.",
)

N_SELECT_ALL = ToolNode(
    name="select_all", fn=_fn_select_all,
    params=[], needs_ui_graph=False,
    description="Select all text in active field (Cmd+A).",
)

N_CLICK_EMPTY = ToolNode(
    name="click_empty_canvas", fn=_fn_click_empty_canvas,
    params=[], needs_ui_graph=True,
    description="Click empty canvas area to deselect. Clears the Active selection block.",
)


N_SCAN_HANDLES = ToolNode(
    name="scan_handles", fn=_fn_scan_handles,
    params=[], needs_ui_graph=True,
    description=(
        "Re-detect selection handles for the currently-selected shape. "
        "Use this if the Active selection block is missing or stale "
        "(e.g. after an action that may have moved or resized the shape). "
        "Refreshes resize handles, extend arrows, and rotate handle."
    ),
)

N_RESIZE_SHAPE = ToolNode(
    name="resize_shape", fn=_fn_resize_shape,
    params=["direction", "amount"], needs_ui_graph=True,
    description=(
        "Resize the currently-selected shape by dragging a corner/edge handle. "
        "direction = one of n,s,e,w,ne,nw,se,sw. "
        "amount = logical pixels (positive grows outward, negative shrinks)."
    ),
)

N_EXTEND_SHAPE = ToolNode(
    name="extend_shape", fn=_fn_extend_shape,
    params=["direction"], needs_ui_graph=True,
    description=(
        "Click the N/S/E/W extend arrow next to the selected shape — drawio "
        "auto-creates a connected shape in that direction. "
        "direction = one of n,s,e,w."
    ),
)

N_ROTATE_SHAPE = ToolNode(
    name="rotate_shape", fn=_fn_rotate_shape,
    params=["angle_degrees"], needs_ui_graph=True,
    description=(
        "Rotate the selected shape around its center by angle_degrees "
        "(positive = clockwise)."
    ),
)

N_CLICK_NODE = ToolNode(
    name="click_node", fn=_fn_click_node,
    params=["node_ref", "clicks"], needs_ui_graph=True,
    description="Click on an existing canvas node.",
)

N_DOUBLE_CLICK_NODE = ToolNode(
    name="double_click_node", fn=_fn_double_click_node,
    params=["node_ref"], needs_ui_graph=True,
    description="Double-click a node to enter text-edit mode.",
)

N_DRAG_NODE = ToolNode(
    name="drag_node", fn=_fn_drag_node,
    params=["node_ref", "target_x", "target_y"], needs_ui_graph=True,
    description="Drag a node to a new position.",
)

N_DRAG_NODE_NEAR = ToolNode(
    name="drag_node_near", fn=_fn_drag_node_near,
    params=["node_ref", "reference_node", "offset_x", "offset_y"],
    needs_ui_graph=True,
    description="Move a node to a position relative to another node.",
)

N_RESIZE_NODE = ToolNode(
    name="resize_node", fn=_fn_resize_node,
    params=["node_ref", "new_width", "new_height"], needs_ui_graph=True,
    description="Resize a node by dragging its handle.",
)

N_HOTKEY = ToolNode(
    name="hotkey", fn=_fn_hotkey,
    params=["keys"], needs_ui_graph=False,
    description="Press a keyboard shortcut.",
)

N_UNDO = ToolNode(
    name="undo", fn=_fn_undo,
    params=[], needs_ui_graph=False,
    description="Undo last action (Cmd+Z).",
)


# ===========================================================================
# Self-register all primitives
# ===========================================================================

for _n in (
    N_PLACE_SHAPE, N_TYPE_LABEL, N_PRESS_ESCAPE, N_PRESS_ENTER,
    N_PRESS_DELETE, N_SELECT_ALL, N_CLICK_EMPTY, N_CLICK_NODE,
    N_DOUBLE_CLICK_NODE, N_DRAG_NODE, N_DRAG_NODE_NEAR,
    N_RESIZE_NODE, N_HOTKEY, N_UNDO,
    N_SCAN_HANDLES, N_RESIZE_SHAPE, N_EXTEND_SHAPE, N_ROTATE_SHAPE,
):
    register(_n)


# ===========================================================================
# Public function aliases (for direct script use)
# ===========================================================================

place_shape = _fn_place_shape
type_label = _fn_type_label
press_escape = _fn_press_escape
press_enter = _fn_press_enter
press_delete = _fn_press_delete
select_all_text = _fn_select_all
click_empty_canvas = _fn_click_empty_canvas
click_node = _fn_click_node
double_click_node = _fn_double_click_node
drag_node = _fn_drag_node
drag_node_near = _fn_drag_node_near
resize_node = _fn_resize_node
hotkey = _fn_hotkey
undo = _fn_undo
