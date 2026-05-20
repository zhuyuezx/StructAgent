"""
Actions — L1 operations composed from L0 atom helpers.

These tools are NOT primitives — they either:

  - resolve a node/object reference to coordinates before clicking, or
  - compose multiple atom calls (a click followed by a drag, a multi-key
    chord, etc.) into a single semantic step.

Each action is registered as a ToolNode with ``level_override=1`` so the
hierarchical tool tree reflects the actual abstraction layer, even though
the children are bare atom helpers (not registered ToolNodes themselves).

Atoms imported below live in ``core.tools.primitives`` and are the only
things in this module that touch ``pyautogui`` directly.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from core import config
from core.state import scene_graph as _sg
from core.tools.primitives import (
    atom_click_at, atom_drag, atom_hotkey, atom_press,
    _get_scene, _save_scene, _scan_and_reconcile,
    N_MOUSE_CLICK, N_MOUSE_DRAG, N_KEY_PRESS, N_KEY_COMBO,
)
from core.tools.registry import (
    ToolNode, register, resolve_node,
)


# ===========================================================================
# Click-related L1 actions
# ===========================================================================

def _fn_click_empty_canvas(ui_graph: Optional[Dict[str, Any]] = None) -> dict:
    """Click the configured empty-canvas point and clear any selection."""
    x, y = config.empty_canvas_point()
    print(f"  [L1] click_empty_canvas → ({x}, {y})")
    atom_click_at(x, y)
    if ui_graph is not None:
        ui_graph["selected_handles"] = None
        sg = _get_scene(ui_graph)
        _sg.set_selected(sg, None)
        _save_scene(ui_graph)
    return {"status": "ok", "tool": "click_empty_canvas", "x": x, "y": y}


def _fn_click_node(
    ui_graph: Dict[str, Any], node_ref: str, clicks: int = 1,
) -> dict:
    """Click a known canvas node by id or label.

    Resolves the (x, y) target via two paths:
      1. ``ui_graph['Canvas_Nodes']`` (legacy hand-calibrated nodes), or
      2. ``ui_graph['scene_graph']`` (auto-tracked objects: matches by id
         or by label, uses the bbox center as the click point).
    """
    try:
        node = resolve_node(ui_graph, node_ref)
        x, y = node["x"], node["y"]
    except KeyError:
        sg = _get_scene(ui_graph)
        obj = _sg.find_by_id(sg, node_ref)
        if obj is None:
            for o in sg["objects"]:
                if o.get("label") == node_ref:
                    obj = o
                    break
        if obj is None or not obj.get("bbox"):
            raise
        bx, by, bw, bh = obj["bbox"]
        x, y = bx + bw // 2, by + bh // 2

    print(f"  [L1] click_node('{node_ref}', clicks={clicks}) → ({x}, {y})")
    atom_click_at(x, y, clicks=clicks)
    time.sleep(0.4)
    target = _scan_and_reconcile(ui_graph, op_name="click_node")
    return {"status": "ok", "tool": "click_node", "node_ref": node_ref,
            "x": x, "y": y,
            "selected_object": target["id"] if target else None}


def _fn_double_click_node(ui_graph: Dict[str, Any], node_ref: str) -> dict:
    """Double-click a canvas node — typically to enter text-edit mode."""
    return _fn_click_node(ui_graph, node_ref, clicks=2)


# ===========================================================================
# Drag-related L1 actions
# ===========================================================================

def _fn_drag_node(
    ui_graph: Dict[str, Any], node_ref: str, target_x: int, target_y: int,
) -> dict:
    """Drag a known canvas node by id to (target_x, target_y)."""
    node = resolve_node(ui_graph, node_ref)
    sx, sy = node["x"], node["y"]
    print(f"  [L1] drag_node('{node_ref}') → ({sx},{sy}) → ({target_x},{target_y})")
    atom_drag(sx, sy, target_x, target_y)
    return {"status": "ok", "tool": "drag_node", "node_ref": node_ref,
            "from": [sx, sy], "to": [target_x, target_y]}


def _fn_drag_node_near(
    ui_graph: Dict[str, Any], node_ref: str, reference_node: str,
    offset_x: int = 200, offset_y: int = 0,
) -> dict:
    """Drag node *node_ref* to a position relative to *reference_node*."""
    ref = resolve_node(ui_graph, reference_node)
    return _fn_drag_node(
        ui_graph, node_ref, ref["x"] + offset_x, ref["y"] + offset_y,
    )


def _fn_resize_node(
    ui_graph: Dict[str, Any], node_ref: str, new_width: int, new_height: int,
) -> dict:
    """Resize a calibrated canvas node by dragging its handle."""
    node = resolve_node(ui_graph, node_ref)
    x, y = node["x"], node["y"]
    w, h = node.get("w", 120), node.get("h", 60)
    handle_x, handle_y = x + w // 2, y + h // 2
    new_hx, new_hy = x + new_width // 2, y + new_height // 2
    print(f"  [L1] resize_node('{node_ref}', {new_width}×{new_height})")
    atom_click_at(x, y)
    time.sleep(0.2)
    atom_drag(handle_x, handle_y, new_hx, new_hy, duration=0.3)
    return {"status": "ok", "tool": "resize_node", "node_ref": node_ref,
            "new_size": [new_width, new_height]}


# ===========================================================================
# Keyboard L1 actions
# ===========================================================================

def _fn_hotkey(*keys: str) -> dict:
    """Press an arbitrary key chord (e.g. ``"command", "z"``)."""
    combo = " + ".join(keys)
    print(f"  [L1] hotkey({combo})")
    atom_hotkey(*keys)
    return {"status": "ok", "tool": "hotkey", "keys": list(keys)}


def _fn_undo() -> dict:
    """Undo the last canvas action (Cmd+Z)."""
    print("  [L1] undo (Cmd+Z)")
    atom_hotkey("command", "z")
    return {"status": "ok", "tool": "undo"}


def _fn_press_enter() -> dict:
    print("  [L1] press_enter")
    atom_press("Return")
    return {"status": "ok", "tool": "press_enter"}


def _fn_press_delete() -> dict:
    print("  [L1] press_delete")
    atom_press("BackSpace")
    return {"status": "ok", "tool": "press_delete"}


def _fn_select_all() -> dict:
    print("  [L1] select_all (Cmd+A)")
    atom_hotkey("command", "a")
    return {"status": "ok", "tool": "select_all"}


# ===========================================================================
# ToolNode declarations — explicit level_override=1
# ===========================================================================

N_CLICK_EMPTY = ToolNode(
    name="click_empty_canvas", fn=_fn_click_empty_canvas,
    params=[], needs_ui_graph=True,
    description="Click empty canvas area to deselect. Clears the Active selection block.",
    children=[N_MOUSE_CLICK],
)

N_CLICK_NODE = ToolNode(
    name="click_node", fn=_fn_click_node,
    params=["node_ref", "clicks"], needs_ui_graph=True,
    description=(
        "Click an existing canvas node by id (e.g. 'obj_001') or label. "
        "Defaults to a single click; pass clicks=2 to double-click "
        "(or use double_click_node)."
    ),
    children=[N_MOUSE_CLICK],
)

N_DOUBLE_CLICK_NODE = ToolNode(
    name="double_click_node", fn=_fn_double_click_node,
    params=["node_ref"], needs_ui_graph=True,
    description="Double-click a node to enter text-edit mode.",
    children=[N_MOUSE_CLICK],
)

N_DRAG_NODE = ToolNode(
    name="drag_node", fn=_fn_drag_node,
    params=["node_ref", "target_x", "target_y"], needs_ui_graph=True,
    description="Drag a node to a new (target_x, target_y) position.",
    children=[N_MOUSE_DRAG],
)

N_DRAG_NODE_NEAR = ToolNode(
    name="drag_node_near", fn=_fn_drag_node_near,
    params=["node_ref", "reference_node", "offset_x", "offset_y"],
    needs_ui_graph=True,
    description="Move a node to a position relative to another reference node.",
    children=[N_MOUSE_DRAG],
)

N_RESIZE_NODE = ToolNode(
    name="resize_node", fn=_fn_resize_node,
    params=["node_ref", "new_width", "new_height"], needs_ui_graph=True,
    description="Resize a calibrated canvas node by dragging its handle.",
    children=[N_MOUSE_CLICK, N_MOUSE_DRAG],
)

N_HOTKEY = ToolNode(
    name="hotkey", fn=_fn_hotkey,
    params=["keys"], needs_ui_graph=False,
    description="Press a keyboard shortcut (key chord).",
    children=[N_KEY_COMBO],
)

N_UNDO = ToolNode(
    name="undo", fn=_fn_undo,
    params=[], needs_ui_graph=False,
    description="Undo last canvas action (Cmd+Z).",
    children=[N_KEY_COMBO],
)

N_PRESS_ENTER = ToolNode(
    name="press_enter", fn=_fn_press_enter,
    params=[], needs_ui_graph=False,
    description="Press Enter to confirm input.",
    children=[N_KEY_PRESS],
)

N_PRESS_DELETE = ToolNode(
    name="press_delete", fn=_fn_press_delete,
    params=[], needs_ui_graph=False,
    description="Press Delete to remove the selected element.",
    children=[N_KEY_PRESS],
)

N_SELECT_ALL = ToolNode(
    name="select_all", fn=_fn_select_all,
    params=[], needs_ui_graph=False,
    description="Select all text in active field (Cmd+A).",
    children=[N_KEY_COMBO],
)


for _n in (
    N_CLICK_EMPTY, N_CLICK_NODE, N_DOUBLE_CLICK_NODE,
    N_DRAG_NODE, N_DRAG_NODE_NEAR, N_RESIZE_NODE,
    N_HOTKEY, N_UNDO,
    N_PRESS_ENTER, N_PRESS_DELETE, N_SELECT_ALL,
):
    register(_n)
