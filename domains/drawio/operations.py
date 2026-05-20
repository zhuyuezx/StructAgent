"""
draw.io atomic operands — L0 drawio-specific actions.

These tools are the smallest semantic operations that modify the draw.io
canvas: placing a shape, labelling it, scanning handles, resizing, moving,
connecting, etc. They are aware of draw.io's interaction model and
scene_graph state but compose from app-agnostic atom helpers.

Layer map:
  atom_*          core/tools/primitives.py  — bare pyautogui, NOT registered
  operations (here)  domains/drawio/         — drawio L0, registered
  actions         core/tools/actions.py     — generic L1, registered
  tools           domains/drawio/tools.py   — drawio compounds, registered
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, Optional

from core import config
from core.state import scene_graph as _sg
from core.tools.primitives import (
    atom_click_at, atom_drag, atom_move_to, atom_press,
    _get_scene, _save_scene,
    _HOVER_DELAY,
    _refresh_handles, _sync_current_bbox, _scan_and_reconcile, _ensure_handles,
    N_MOUSE_MOVE, N_MOUSE_CLICK, N_MOUSE_DRAG, N_KEY_PRESS, N_KEYBOARD_TYPE,
)
from core.tools.registry import ToolNode, register, resolve_tool


# ===========================================================================
# Direction / handle look-up tables
# ===========================================================================

_RESIZE_HANDLE_FOR_DIRECTION: Dict[str, str] = {
    "n":  "tm", "s":  "bm", "e":  "mr", "w":  "ml",
    "ne": "tr", "nw": "tl", "se": "br", "sw": "bl",
}
_RESIZE_DIRECTION_VECTOR: Dict[str, tuple] = {
    "n":  (0, -1),  "s":  (0, 1),   "e":  (1, 0),   "w":  (-1, 0),
    "ne": (1, -1),  "nw": (-1, -1), "se": (1, 1),   "sw": (-1, 1),
}
_EXTEND_OFFSET_PX = 140


# ===========================================================================
# draw.io L0 operand implementations
# ===========================================================================

def _fn_place_shape(ui_graph: Dict[str, Any], tool_name: str) -> dict:
    """Place a sidebar shape onto the canvas."""
    _sync_current_bbox(ui_graph)
    x, y = resolve_tool(ui_graph, tool_name)
    print(f"  [L0] place_shape('{tool_name}') → click ({x}, {y}) + Enter")
    atom_click_at(x, y)
    time.sleep(0.3)
    atom_press("Return")
    sg = _get_scene(ui_graph)
    shape_type = tool_name.replace("_Tool", "").replace("_", " ").strip() or tool_name
    obj = _sg.add_object(sg, type_=shape_type, bbox=None, label="",
                         op_name="place_shape")
    _sg.set_selected(sg, obj["id"])
    _save_scene(ui_graph)
    return {"status": "ok", "tool": "place_shape", "tool_name": tool_name,
            "x": x, "y": y, "scene_object_id": obj["id"]}


def _fn_type_label(text: str, ui_graph: Optional[Dict[str, Any]] = None) -> dict:
    """Type *text* into the currently focused element + sync scene_graph."""
    from core.tools.primitives import atom_write
    print(f"  [L0] type_label('{text}')")
    atom_write(text)
    if ui_graph is not None:
        sg = _get_scene(ui_graph)
        sel = _sg.get_selected(sg)
        if sel is not None:
            _sg.update_object_label(sg, sel["id"], text, op_name="type_label")
            _save_scene(ui_graph)
    return {"status": "ok", "tool": "type_label", "text": text}


def _fn_press_escape(ui_graph: Optional[Dict[str, Any]] = None) -> dict:
    print("  [L0] press_escape")
    atom_press("Escape")
    if ui_graph is not None:
        time.sleep(0.3)
        _scan_and_reconcile(ui_graph, op_name="press_escape")
    return {"status": "ok", "tool": "press_escape"}


def _fn_scan_handles(ui_graph: Dict[str, Any]) -> dict:
    print("  [L0] scan_handles")
    handles = _refresh_handles(ui_graph)
    return {
        "status": "ok" if handles.is_valid() else "no_selection",
        "tool": "scan_handles", "handles": handles.to_dict(),
    }


def _fn_resize_shape(
    ui_graph: Dict[str, Any], direction: str, amount: int,
) -> dict:
    direction = direction.lower().strip()
    if direction not in _RESIZE_HANDLE_FOR_DIRECTION:
        return {"status": "error", "tool": "resize_shape",
                "error": f"unknown direction '{direction}' — expected one of "
                         f"{sorted(_RESIZE_HANDLE_FOR_DIRECTION)}"}
    _sync_current_bbox(ui_graph)
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
    sg = _get_scene(ui_graph)
    sel = _sg.get_selected(sg)
    target_id = sel["id"] if sel else None
    atom_drag(sx, sy, tx, ty)
    time.sleep(0.4)
    _scan_and_reconcile(
        ui_graph, op_name=f"resize_shape:{direction}",
        hint_bbox=tuple(h["shape_bbox"]) if h.get("shape_bbox") else None,
        target_id=target_id,
    )
    return {"status": "ok", "tool": "resize_shape",
            "direction": direction, "amount": amount,
            "from": [sx, sy], "to": [tx, ty]}


def _fn_extend_shape(ui_graph: Dict[str, Any], direction: str) -> dict:
    direction = direction.lower().strip()
    if direction not in ("n", "s", "e", "w"):
        return {"status": "error", "tool": "extend_shape",
                "error": f"unknown direction '{direction}'"}
    _sync_current_bbox(ui_graph)
    h = _ensure_handles(ui_graph)
    if not h or not h.get("extend"):
        return {"status": "error", "tool": "extend_shape",
                "error": "no shape selected (or extend arrows not visible)"}
    if direction not in h["extend"]:
        return {"status": "error", "tool": "extend_shape",
                "error": f"extend arrow '{direction}' not detected"}
    sg = _get_scene(ui_graph)
    source_obj = _sg.get_selected(sg)
    sx, sy = h["extend"][direction]
    dx, dy = _RESIZE_DIRECTION_VECTOR[direction]
    tx, ty = int(sx + dx * _EXTEND_OFFSET_PX), int(sy + dy * _EXTEND_OFFSET_PX)
    print(f"  [L0] extend_shape('{direction}') → drag ({sx},{sy}) → ({tx},{ty})")
    atom_drag(sx, sy, tx, ty)
    time.sleep(0.8)
    handles = _refresh_handles(ui_graph)
    new_obj_id = None
    if handles.is_valid() and handles.shape_bbox:
        new_obj = _sg.add_object(
            sg, type_="Rectangle", bbox=list(handles.shape_bbox),
            label="", op_name=f"extend_shape:{direction}",
        )
        new_obj_id = new_obj["id"]
        _sg.set_selected(sg, new_obj["id"])
        if source_obj is not None:
            opposite = {"n": "s", "s": "n", "e": "w", "w": "e"}[direction]
            _sg.add_edge(
                sg, source=source_obj["id"], target=new_obj["id"],
                source_anchor=direction, target_anchor=opposite,
                op_name=f"extend_shape:{direction}",
            )
    _save_scene(ui_graph)
    return {"status": "ok", "tool": "extend_shape", "direction": direction,
            "from": [sx, sy], "to": [tx, ty],
            "new_object_id": new_obj_id,
            "source_object_id": source_obj["id"] if source_obj else None}


def _fn_rotate_shape(ui_graph: Dict[str, Any], angle_degrees: float) -> dict:
    _sync_current_bbox(ui_graph)
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
    sg = _get_scene(ui_graph)
    sel = _sg.get_selected(sg)
    target_id = sel["id"] if sel else None
    atom_drag(rx, ry, tx, ty)
    time.sleep(0.4)
    _scan_and_reconcile(
        ui_graph, op_name=f"rotate_shape:{angle_degrees}",
        target_id=target_id,
    )
    return {"status": "ok", "tool": "rotate_shape",
            "angle_degrees": angle_degrees,
            "from": [rx, ry], "to": [tx, ty]}


def _fn_move_shape(
    ui_graph: Dict[str, Any], direction: str, amount: int,
) -> dict:
    """Move the selected shape. Always escape+reclick to guarantee select mode
    (drawio's resize chrome appears in both edit and select mode; an interior
    drag in edit mode selects text, not the shape)."""
    direction = direction.lower().strip()
    if direction not in _RESIZE_DIRECTION_VECTOR:
        return {"status": "error", "tool": "move_shape",
                "error": f"unknown direction '{direction}'"}
    _sync_current_bbox(ui_graph)
    sg = _get_scene(ui_graph)
    sel = _sg.get_selected(sg)
    if not sel or not sel.get("bbox"):
        return {"status": "error", "tool": "move_shape",
                "error": "no selected scene_graph object with a known bbox "
                         "(call press_escape after type_label, or click_node first)"}
    target_id = sel["id"]
    bx, by, bw, bh = sel["bbox"]
    gx, gy = bx + bw // 2, by + bh // 2
    atom_press("Escape")
    time.sleep(0.25)
    atom_click_at(gx, gy)
    time.sleep(0.3)
    dx, dy = _RESIZE_DIRECTION_VECTOR[direction]
    tx, ty = int(gx + dx * amount), int(gy + dy * amount)
    print(f"  [L0] move_shape('{direction}', {amount}) → "
          f"escape+reclick, drag ({gx},{gy}) → ({tx},{ty})")
    atom_drag(gx, gy, tx, ty)
    time.sleep(0.4)
    _scan_and_reconcile(
        ui_graph, op_name=f"move_shape:{direction}",
        target_id=target_id,
    )
    return {"status": "ok", "tool": "move_shape",
            "direction": direction, "amount": amount,
            "from": [gx, gy], "to": [tx, ty]}


def _fn_hover_object(ui_graph: Dict[str, Any], object_id: str) -> dict:
    sg = _get_scene(ui_graph)
    obj = _sg.find_by_id(sg, object_id)
    if obj is None:
        return {"status": "error", "tool": "hover_object",
                "error": f"object '{object_id}' not in scene_graph"}
    if not obj.get("bbox"):
        return {"status": "error", "tool": "hover_object",
                "error": f"object '{object_id}' has no bbox yet"}
    bx, by, bw, bh = obj["bbox"]
    cx, cy = bx + bw // 2, by + bh // 2
    print(f"  [L0] hover_object('{object_id}') → moveTo ({cx},{cy})")
    atom_move_to(cx, cy)
    time.sleep(_HOVER_DELAY)
    return {"status": "ok", "tool": "hover_object",
            "object_id": object_id, "at": [cx, cy]}


def _fn_connect_shapes(
    ui_graph: Dict[str, Any], source_id: str, target_id: str,
    source_anchor: str = "auto",
) -> dict:
    _sync_current_bbox(ui_graph)
    sg = _get_scene(ui_graph)
    src = _sg.find_by_id(sg, source_id)
    tgt = _sg.find_by_id(sg, target_id)
    if not src or not tgt:
        return {"status": "error", "tool": "connect_shapes",
                "error": f"source '{source_id}' or target '{target_id}' "
                         f"not in scene_graph"}
    # Local import avoids circular dep (actions.py imports from primitives.py
    # which is a dependency of this module).
    from core.tools.actions import _fn_click_node as _click_node
    if not src.get("bbox"):
        _click_node(ui_graph, source_id)
        src = _sg.find_by_id(sg, source_id)
    if not tgt.get("bbox"):
        _click_node(ui_graph, target_id)
        tgt = _sg.find_by_id(sg, target_id)
    if not src.get("bbox") or not tgt.get("bbox"):
        return {"status": "error", "tool": "connect_shapes",
                "error": f"could not determine bbox for source or target — "
                         f"src.bbox={src.get('bbox')}, tgt.bbox={tgt.get('bbox')}"}
    sbx, sby, sbw, sbh = src["bbox"]
    tbx, tby, tbw, tbh = tgt["bbox"]
    src_cx, src_cy = sbx + sbw // 2, sby + sbh // 2
    tgt_cx, tgt_cy = tbx + tbw // 2, tby + tbh // 2
    if source_anchor == "auto":
        if abs(tgt_cx - src_cx) >= abs(tgt_cy - src_cy):
            source_anchor = "e" if tgt_cx > src_cx else "w"
        else:
            source_anchor = "s" if tgt_cy > src_cy else "n"
    elif source_anchor not in ("n", "s", "e", "w"):
        return {"status": "error", "tool": "connect_shapes",
                "error": f"source_anchor must be n/s/e/w/auto, got '{source_anchor}'"}
    if not src.get("selected") or not ui_graph.get("selected_handles"):
        _click_node(ui_graph, source_id)
    handles = ui_graph.get("selected_handles") or {}
    extend = handles.get("extend", {})
    if source_anchor not in extend:
        sa_pt = src["anchors"][source_anchor]
        nudge = 12
        dx, dy = _RESIZE_DIRECTION_VECTOR[source_anchor]
        sx, sy = sa_pt[0] + dx * nudge, sa_pt[1] + dy * nudge
    else:
        sx, sy = extend[source_anchor]
    print(f"  [L0] connect_shapes({source_id}→{target_id}) "
          f"drag ({sx},{sy}) → ({tgt_cx},{tgt_cy})")
    atom_drag(sx, sy, tgt_cx, tgt_cy,
              duration=config.drag_duration() * 1.5, hold_pre=0.15)
    time.sleep(0.6)
    opp = {"n": "s", "s": "n", "e": "w", "w": "e"}[source_anchor]
    _sg.add_edge(
        sg, source=source_id, target=target_id,
        source_anchor=source_anchor, target_anchor=opp,
        op_name="connect_shapes",
    )
    _save_scene(ui_graph)
    return {"status": "ok", "tool": "connect_shapes",
            "source": source_id, "target": target_id,
            "source_anchor": source_anchor, "target_anchor": opp,
            "from": [sx, sy], "to": [tgt_cx, tgt_cy]}


# ===========================================================================
# ToolNode declarations (L0 drawio operands)
# ===========================================================================

N_PLACE_SHAPE = ToolNode(
    name="place_shape", fn=_fn_place_shape,
    params=["tool_name"], needs_ui_graph=True,
    description="Click a sidebar shape to place it on the canvas.",
    children=[N_MOUSE_CLICK, N_KEY_PRESS],
)
N_TYPE_LABEL = ToolNode(
    name="type_label", fn=_fn_type_label,
    params=["text"], needs_ui_graph=True,
    description=(
        "Type a text label into the active shape. Also updates the label "
        "of the currently-selected scene_graph object."
    ),
    children=[N_KEYBOARD_TYPE],
)
N_PRESS_ESCAPE = ToolNode(
    name="press_escape", fn=_fn_press_escape,
    params=[], needs_ui_graph=True,
    description=(
        "Press Escape to exit text editing or deselect. When a shape stays "
        "selected afterwards, the selection handles are auto-refreshed."
    ),
    children=[N_KEY_PRESS],
)
N_SCAN_HANDLES = ToolNode(
    name="scan_handles", fn=_fn_scan_handles,
    params=[], needs_ui_graph=True,
    description=(
        "Re-detect selection handles for the currently-selected shape. "
        "Use this if the Active selection block is missing or stale."
    ),
    children=[N_MOUSE_MOVE],
)
N_RESIZE_SHAPE = ToolNode(
    name="resize_shape", fn=_fn_resize_shape,
    params=["direction", "amount"], needs_ui_graph=True,
    description=(
        "Resize the currently-selected shape by dragging a corner/edge handle. "
        "direction = one of n,s,e,w,ne,nw,se,sw. "
        "amount = logical pixels (positive grows outward, negative shrinks)."
    ),
    children=[N_MOUSE_DRAG],
)
N_EXTEND_SHAPE = ToolNode(
    name="extend_shape", fn=_fn_extend_shape,
    params=["direction"], needs_ui_graph=True,
    description=(
        "Drag the N/S/E/W extend arrow outward — drawio auto-creates a "
        "connected shape in that direction. direction = one of n,s,e,w."
    ),
    children=[N_MOUSE_DRAG],
)
N_ROTATE_SHAPE = ToolNode(
    name="rotate_shape", fn=_fn_rotate_shape,
    params=["angle_degrees"], needs_ui_graph=True,
    description=(
        "Rotate the selected shape around its center by angle_degrees "
        "(positive = clockwise)."
    ),
    children=[N_MOUSE_DRAG],
)
N_MOVE_SHAPE = ToolNode(
    name="move_shape", fn=_fn_move_shape,
    params=["direction", "amount"], needs_ui_graph=True,
    description=(
        "Drag the selected shape in a compass direction by amount logical px. "
        "Internally escape+reclicks to avoid drawio's text-edit interior-drag "
        "ambiguity. direction = one of n,s,e,w,ne,nw,se,sw."
    ),
    children=[N_KEY_PRESS, N_MOUSE_CLICK, N_MOUSE_DRAG],
)
N_HOVER_OBJECT = ToolNode(
    name="hover_object", fn=_fn_hover_object,
    params=["object_id"], needs_ui_graph=True,
    description=(
        "RARE. Hovers cursor over a scene_graph object without clicking. "
        "Only useful as a prep step before extend_shape on a non-selected shape. "
        "NOT how you draw an edge — use connect_shapes."
    ),
    children=[N_MOUSE_MOVE],
)
N_CONNECT_SHAPES = ToolNode(
    name="connect_shapes", fn=_fn_connect_shapes,
    params=["source_id", "target_id", "source_anchor"], needs_ui_graph=True,
    description=(
        "PREFERRED for drawing an edge between two EXISTING scene_graph "
        "objects. Handles selection of the source internally — no need to "
        "click_node or hover_object first. source_anchor ∈ n/s/e/w or 'auto'."
    ),
    children=[N_MOUSE_DRAG],
)


# ===========================================================================
# Self-register all drawio operands
# ===========================================================================

for _n in (
    N_PLACE_SHAPE, N_TYPE_LABEL, N_PRESS_ESCAPE,
    N_SCAN_HANDLES, N_RESIZE_SHAPE, N_EXTEND_SHAPE, N_ROTATE_SHAPE,
    N_MOVE_SHAPE, N_HOVER_OBJECT, N_CONNECT_SHAPES,
):
    register(_n)


# ===========================================================================
# Public aliases (for direct script use and re-export by tools.py)
# ===========================================================================

place_shape = _fn_place_shape
type_label = _fn_type_label
press_escape = _fn_press_escape
