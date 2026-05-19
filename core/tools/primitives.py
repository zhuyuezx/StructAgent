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
from core.state import scene_graph as _sg
from core.tools.registry import (
    ToolNode, register, resolve_tool, resolve_node,
)


# ===========================================================================
# Scene graph helpers — deterministic state, threaded through ui_graph
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
# Inter-operation scanner
# ===========================================================================

def _scan_and_reconcile(
    ui_graph: Dict[str, Any], op_name: str,
    *, hint_bbox: Optional[tuple] = None,
) -> Optional[Dict[str, Any]]:
    """After a geometry-changing op: re-detect handles, then update the
    matching scene_graph object's bbox (and selection state).

    Reconciliation strategy — pick the scene_graph object to update by:
      1. Most-recently-added bbox-less object (a fresh placement that hasn't
         had its bbox filled in yet).
      2. Else the object whose center is closest to the new bbox center.

    Always called after deterministic operands; never under LLM control.
    """
    handles = _refresh_handles(ui_graph, hint_bbox=hint_bbox)
    sg = _get_scene(ui_graph)
    if not handles.is_valid() or not handles.shape_bbox:
        _sg.set_selected(sg, None)
        _save_scene(ui_graph)
        return None

    new_bbox = list(handles.shape_bbox)
    target: Optional[Dict[str, Any]] = None
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


# ===========================================================================
# Leaf tool functions (level 0 — single atomic operations)
# ===========================================================================

def _fn_place_shape(ui_graph: Dict[str, Any], tool_name: str) -> dict:
    """
    Place a sidebar shape onto the canvas.

    drawio auto-places the shape at a default canvas location on a single
    click of the sidebar icon and selects it (but stays out of text-edit
    mode — we press Enter to open the inline editor).

    Scene-graph effect: appends a new object with ``bbox=None``. The bbox
    gets filled in by the inter-op scanner once handles become visible
    again (after type_label + press_escape).
    """
    x, y = resolve_tool(ui_graph, tool_name)
    print(f"  [L0] place_shape('{tool_name}') → click ({x}, {y}) + Enter")
    pyautogui.click(x, y)
    time.sleep(0.3)
    pyautogui.press("enter")

    sg = _get_scene(ui_graph)
    # Tool names look like "Rectangle_Tool", "Ellipse_Tool" — strip the suffix.
    shape_type = tool_name.replace("_Tool", "").replace("_", " ").strip() or tool_name
    obj = _sg.add_object(sg, type_=shape_type, bbox=None, label="",
                         op_name="place_shape")
    _sg.set_selected(sg, obj["id"])
    _save_scene(ui_graph)
    return {"status": "ok", "tool": "place_shape", "tool_name": tool_name,
            "x": x, "y": y, "scene_object_id": obj["id"]}


def _fn_type_label(text: str, ui_graph: Optional[Dict[str, Any]] = None) -> dict:
    """Type *text* into the currently focused element.

    Uses ``pyautogui.write`` (NOT ``typewrite``) so capital letters and
    punctuation are typed correctly via Shift modifiers. If ``ui_graph`` is
    provided and a scene_graph selection exists, also updates that object's
    label for the LLM-facing scene summary.
    """
    print(f"  [L0] type_label('{text}')")
    pyautogui.write(text, interval=config.type_interval())
    if ui_graph is not None:
        sg = _get_scene(ui_graph)
        sel = _sg.get_selected(sg)
        if sel is not None:
            _sg.update_object_label(sg, sel["id"], text, op_name="type_label")
            _save_scene(ui_graph)
    return {"status": "ok", "tool": "type_label", "text": text}


def _fn_press_escape(ui_graph: Optional[Dict[str, Any]] = None) -> dict:
    print("  [L0] press_escape")
    pyautogui.hotkey("Escape")
    # Escape exits text-edit mode and leaves the shape selected with its
    # resize handles visible — perfect time to reconcile the bbox into
    # the scene graph (synthetic place_shape entries get their real bbox
    # filled in here).
    if ui_graph is not None:
        time.sleep(0.3)
        _scan_and_reconcile(ui_graph, op_name="press_escape")
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
    _scan_and_reconcile(
        ui_graph, op_name=f"resize_shape:{direction}",
        hint_bbox=tuple(h["shape_bbox"]) if h.get("shape_bbox") else None,
    )
    return {"status": "ok", "tool": "resize_shape",
            "direction": direction, "amount": amount,
            "from": [sx, sy], "to": [tx, ty]}


_EXTEND_OFFSET_PX = 140  # how far past the arrow to drop the new shape


def _fn_extend_shape(ui_graph: Dict[str, Any], direction: str) -> dict:
    """Drag the N/S/E/W extend arrow outward — drawio creates a new
    connected shape (default Rectangle) at the drop point.

    Scene-graph effect: appends a new object AND an edge from the source
    object (the one selected before the operation) to the new object.
    """
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

    sg = _get_scene(ui_graph)
    source_obj = _sg.get_selected(sg)

    sx, sy = h["extend"][direction]
    dx, dy = _RESIZE_DIRECTION_VECTOR[direction]
    tx, ty = int(sx + dx * _EXTEND_OFFSET_PX), int(sy + dy * _EXTEND_OFFSET_PX)
    print(f"  [L0] extend_shape('{direction}') → drag ({sx},{sy}) → ({tx},{ty})")
    pyautogui.moveTo(sx, sy)
    time.sleep(0.1)
    pyautogui.mouseDown()
    time.sleep(0.1)
    pyautogui.moveTo(tx, ty, duration=config.drag_duration())
    pyautogui.mouseUp()
    time.sleep(0.8)

    # The new shape is now selected. Detect its bbox.
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
            # Edge anchor on source: the direction we extended from.
            # On target: the opposite direction (the side facing the source).
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
    _scan_and_reconcile(ui_graph, op_name=f"rotate_shape:{angle_degrees}")
    return {"status": "ok", "tool": "rotate_shape",
            "angle_degrees": angle_degrees,
            "from": [rx, ry], "to": [tx, ty]}


# ===========================================================================
# Higher-level shape ops needed for the scene-graph demo
# ===========================================================================

def _fn_move_shape(
    ui_graph: Dict[str, Any], direction: str, amount: int,
) -> dict:
    """Drag the currently-selected shape in a compass direction by ``amount``
    logical pixels. Picks any safe interior point of the shape (not on a
    handle) as the grab point so drawio interprets it as a move drag, not
    a resize."""
    direction = direction.lower().strip()
    if direction not in _RESIZE_DIRECTION_VECTOR:
        return {"status": "error", "tool": "move_shape",
                "error": f"unknown direction '{direction}'"}

    h = _ensure_handles(ui_graph)
    if not h or not h.get("shape_bbox"):
        return {"status": "error", "tool": "move_shape",
                "error": "no shape selected — call click_node first"}

    bx, by, bw, bh = h["shape_bbox"]
    # Grab near the shape center, slightly off-center so we're not on the
    # rotation icon at the top-right.
    gx, gy = bx + bw // 2, by + bh // 2
    dx, dy = _RESIZE_DIRECTION_VECTOR[direction]
    tx, ty = int(gx + dx * amount), int(gy + dy * amount)

    print(f"  [L0] move_shape('{direction}', {amount}) → "
          f"drag ({gx},{gy}) → ({tx},{ty})")
    pyautogui.moveTo(gx, gy)
    time.sleep(0.1)
    pyautogui.mouseDown()
    time.sleep(0.1)
    pyautogui.moveTo(tx, ty, duration=config.drag_duration())
    pyautogui.mouseUp()
    time.sleep(0.4)
    _scan_and_reconcile(ui_graph, op_name=f"move_shape:{direction}")
    return {"status": "ok", "tool": "move_shape",
            "direction": direction, "amount": amount,
            "from": [gx, gy], "to": [tx, ty]}


def _fn_hover_object(ui_graph: Dict[str, Any], object_id: str) -> dict:
    """Hover the mouse over a scene_graph object WITHOUT clicking it. In
    drawio this causes the N/S/E/W extend arrows to render even though the
    shape isn't selected. Useful for visual demos and for driving an
    extend/connect from a non-selected object."""
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
    pyautogui.moveTo(cx, cy)
    time.sleep(_HOVER_DELAY)
    return {"status": "ok", "tool": "hover_object",
            "object_id": object_id, "at": [cx, cy]}


def _fn_connect_shapes(
    ui_graph: Dict[str, Any], source_id: str, target_id: str,
    source_anchor: str = "auto",
) -> dict:
    """Draw an edge from one scene_graph object to another by dragging from
    the source's chosen edge anchor to the target's bbox center.

    Pre-conditions:
      - Both objects exist in scene_graph and have bboxes.
      - The source is currently selected and hovered (so its extend arrows
        are visible). This function will click+hover the source first if
        it isn't selected.

    ``source_anchor`` is one of n/s/e/w, or "auto" to pick whichever side
    faces the target.
    """
    sg = _get_scene(ui_graph)
    src = _sg.find_by_id(sg, source_id)
    tgt = _sg.find_by_id(sg, target_id)
    if not src or not tgt or not src.get("bbox") or not tgt.get("bbox"):
        return {"status": "error", "tool": "connect_shapes",
                "error": "source/target not found or missing bbox"}

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

    # Ensure source is selected + handles fresh so we can find its extend arrow.
    if not src.get("selected") or not ui_graph.get("selected_handles"):
        _fn_click_node(ui_graph, source_id)
    handles = ui_graph.get("selected_handles") or {}
    extend = handles.get("extend", {})
    if source_anchor not in extend:
        # Fall back to a computed anchor on the source edge.
        sa_pt = src["anchors"][source_anchor]
        # Nudge slightly outward — drawio's drag-from-edge to create a
        # connection works best slightly outside the shape.
        nudge = 12
        dx, dy = _RESIZE_DIRECTION_VECTOR[source_anchor]
        sx, sy = sa_pt[0] + dx * nudge, sa_pt[1] + dy * nudge
    else:
        sx, sy = extend[source_anchor]

    print(f"  [L0] connect_shapes({source_id}→{target_id}) "
          f"drag ({sx},{sy}) → ({tgt_cx},{tgt_cy})")
    pyautogui.moveTo(sx, sy)
    time.sleep(0.1)
    pyautogui.mouseDown()
    time.sleep(0.15)
    pyautogui.moveTo(tgt_cx, tgt_cy, duration=config.drag_duration() * 1.5)
    pyautogui.mouseUp()
    time.sleep(0.6)

    # Determine target anchor from drag direction.
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
        sg = _get_scene(ui_graph)
        _sg.set_selected(sg, None)
        _save_scene(ui_graph)
    return {"status": "ok", "tool": "click_empty_canvas", "x": x, "y": y}


def _fn_click_node(ui_graph: Dict[str, Any], node_ref: str, clicks: int = 1) -> dict:
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
    target = _scan_and_reconcile(ui_graph, op_name="click_node")
    return {"status": "ok", "tool": "click_node", "node_ref": node_ref,
            "x": x, "y": y,
            "selected_object": target["id"] if target else None}


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
    params=["text"], needs_ui_graph=True,
    description=(
        "Type a text label into the active shape. Also updates the label "
        "of the currently-selected scene_graph object."
    ),
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

N_MOVE_SHAPE = ToolNode(
    name="move_shape", fn=_fn_move_shape,
    params=["direction", "amount"], needs_ui_graph=True,
    description=(
        "Drag the selected shape in a compass direction "
        "(n/s/e/w/ne/nw/se/sw) by ``amount`` logical pixels. Updates the "
        "scene_graph bbox after the move."
    ),
)

N_HOVER_OBJECT = ToolNode(
    name="hover_object", fn=_fn_hover_object,
    params=["object_id"], needs_ui_graph=True,
    description=(
        "Hover the mouse over a scene_graph object WITHOUT clicking it. "
        "Causes drawio to render the directional extend arrows even though "
        "the shape is not selected. object_id refers to scene_graph ids "
        "like 'obj_001'."
    ),
)

N_CONNECT_SHAPES = ToolNode(
    name="connect_shapes", fn=_fn_connect_shapes,
    params=["source_id", "target_id", "source_anchor"], needs_ui_graph=True,
    description=(
        "Draw a connector edge from one scene_graph object to another by "
        "dragging from the source's edge anchor to the target's center. "
        "source_anchor ∈ n/s/e/w or 'auto' to pick the side facing target."
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
    N_MOVE_SHAPE, N_HOVER_OBJECT, N_CONNECT_SHAPES,
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
