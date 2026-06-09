"""
draw.io L1 operand implementations (no registration).

These functions are referenced by JSON definitions in state/tools/ via
"python_fn": "domains.drawio.operations:<fn_name>".  Registration is
handled entirely by the JSON loader; this file is pure implementation.

Each function is a single semantic draw.io step that composes L0 atom
calls with scene_graph bookkeeping.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, Optional

from core import config
from core.state import scene_graph as _sg
from core.tools.atoms import atom_click_at, atom_drag, atom_move_to, atom_press
from core.tools.reconcile import (
    get_scene, save_scene,
    _HOVER_DELAY,
    refresh_handles, sync_current_bbox, scan_and_reconcile, ensure_handles,
)
from core.tools.registry import resolve_tool

logger = logging.getLogger(__name__)

# Direction / handle look-up tables (used across multiple functions)
_RESIZE_HANDLE_FOR_DIRECTION: Dict[str, str] = {
    "n":  "tm", "s":  "bm", "e":  "mr", "w":  "ml",
    "ne": "tr", "nw": "tl", "se": "br", "sw": "bl",
}
_RESIZE_DIRECTION_VECTOR: Dict[str, tuple] = {
    "n":  (0, -1),  "s":  (0, 1),   "e":  (1, 0),   "w":  (-1, 0),
    "ne": (1, -1),  "nw": (-1, -1), "se": (1, 1),   "sw": (-1, 1),
}
_EXTEND_OFFSET_PX = 140

# Accept human / LLM phrasings for directions and normalize to canonical
# compass codes. The Executor and Planner are told to use n/s/e/w, but local
# models occasionally emit "east", "left", "up". Widening what the operands
# accept makes them robust to that without changing the documented contract.
_DIRECTION_ALIASES: Dict[str, str] = {
    "n": "n", "s": "s", "e": "e", "w": "w",
    "ne": "ne", "nw": "nw", "se": "se", "sw": "sw",
    "north": "n", "south": "s", "east": "e", "west": "w",
    "up": "n", "down": "s", "right": "e", "left": "w",
    "northeast": "ne", "northwest": "nw", "southeast": "se", "southwest": "sw",
    "top": "n", "bottom": "s",
}


def _norm_dir(direction: str) -> str:
    """Normalize a direction/anchor to a canonical compass code.

    Unknown values pass through (lower-cased/stripped) so each caller's own
    validation still raises a clear 'unknown direction' error.
    """
    key = str(direction).lower().strip()
    return _DIRECTION_ALIASES.get(key, key)


def _active_object(sg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the object an operand should act on.

    Prefer the currently-selected object; otherwise fall back to the most
    recently created object that has a known bbox. The fallback exists because
    several common flows clear the selection — e.g. ``place_and_label`` ends
    with ``click_empty_canvas`` — yet the next step (``move_shape`` /
    ``resize_shape`` / …) means "the shape I just created". Returns None only
    when no object has a bbox yet.
    """
    sel = _sg.get_selected(sg)
    if sel and sel.get("bbox"):
        return sel
    return next((o for o in reversed(sg["objects"]) if o.get("bbox")), None)


def _reselect_if_needed(ui_graph: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Physically re-select a shape so on-screen handle detection works.

    Handle-based operands (resize/rotate/extend) read the selection chrome of
    the *currently selected* shape. If nothing is selected (e.g. after a
    deselecting compound), click the recovered object's center to re-select it
    on the canvas, then mark it selected in the scene graph. No-op when a shape
    with a known bbox is already selected. Returns the active object or None.
    """
    sg = get_scene(ui_graph)
    sel = _sg.get_selected(sg)
    if sel and sel.get("bbox"):
        return sel
    target = _active_object(sg)
    if target is None:
        return None
    bx, by, bw, bh = target["bbox"]
    cx, cy = bx + bw // 2, by + bh // 2
    logger.info("  [L1] re-selecting %s (no live selection)", target["id"])
    atom_press("Escape")
    time.sleep(0.2)
    atom_click_at(cx, cy)
    time.sleep(0.3)
    _sg.set_selected(sg, target["id"])
    save_scene(ui_graph)
    return target


# ===========================================================================
# draw.io L1 operand implementations
# ===========================================================================

def _fn_place_shape(ui_graph: Dict[str, Any], tool_name: str) -> dict:
    """Place a sidebar shape onto the canvas."""
    # Pre-click the canvas to ensure draw.io is the active window before we
    # touch the sidebar.  On macOS the first click on a non-focused window is
    # an "activation click" — the OS brings the window to the front but
    # silently discards the click so it never reaches draw.io's sidebar tool.
    # This happens whenever the user clicked the IDE's "Run cell" button to
    # start this cell, stealing focus from draw.io.  A canvas pre-click costs
    # one deselect (harmless here) and guarantees the sidebar click registers.
    _fcx, _fcy = config.empty_canvas_point()
    atom_click_at(_fcx, _fcy)
    time.sleep(0.2)

    sync_current_bbox(ui_graph)
    x, y = resolve_tool(ui_graph, tool_name)
    logger.info("  [L1] place_shape('%s') → click (%d, %d) + Enter", tool_name, x, y)
    atom_click_at(x, y)
    time.sleep(0.3)
    atom_press("Return")
    sg = get_scene(ui_graph)
    shape_type = tool_name.replace("_Tool", "").replace("_", " ").strip() or tool_name
    obj = _sg.add_object(sg, type_=shape_type, bbox=None, label="",
                         op_name="place_shape")
    _sg.set_selected(sg, obj["id"])
    save_scene(ui_graph)
    return {"status": "ok", "tool": "place_shape", "tool_name": tool_name,
            "x": x, "y": y, "scene_object_id": obj["id"]}


def _fn_type_label(text: str, ui_graph: Optional[Dict[str, Any]] = None) -> dict:
    """Type *text* into the currently focused element + sync scene_graph."""
    from core.tools.atoms import atom_write
    logger.info("  [L1] type_label('%s')", text)
    atom_write(text)
    if ui_graph is not None:
        sg = get_scene(ui_graph)
        sel = _sg.get_selected(sg)
        if sel is not None:
            _sg.update_object_label(sg, sel["id"], text, op_name="type_label")
            save_scene(ui_graph)
    return {"status": "ok", "tool": "type_label", "text": text}


def _fn_press_escape(ui_graph: Optional[Dict[str, Any]] = None) -> dict:
    logger.info("  [L1] press_escape")
    atom_press("Escape")
    if ui_graph is not None:
        time.sleep(0.3)
        scan_and_reconcile(ui_graph, op_name="press_escape")
    return {"status": "ok", "tool": "press_escape"}


def _fn_scan_handles(ui_graph: Dict[str, Any]) -> dict:
    logger.info("  [L1] scan_handles")
    handles = refresh_handles(ui_graph)
    return {
        "status": "ok" if handles.is_valid() else "no_selection",
        "tool": "scan_handles", "handles": handles.to_dict(),
    }


def _fn_resize_shape(
    ui_graph: Dict[str, Any], direction: str, amount: int,
) -> dict:
    direction = _norm_dir(direction)
    if direction not in _RESIZE_HANDLE_FOR_DIRECTION:
        return {"status": "error", "tool": "resize_shape",
                "error": f"unknown direction '{direction}'"}
    sync_current_bbox(ui_graph)
    _reselect_if_needed(ui_graph)
    h = ensure_handles(ui_graph)
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
    logger.info("  [L1] resize_shape('%s', %d) → "
                "drag handle '%s' (%d,%d) → (%d,%d)",
                direction, amount, slot, sx, sy, tx, ty)
    sg = get_scene(ui_graph)
    sel = _sg.get_selected(sg)
    target_id = sel["id"] if sel else None
    atom_drag(sx, sy, tx, ty)
    time.sleep(0.4)
    scan_and_reconcile(
        ui_graph, op_name=f"resize_shape:{direction}",
        hint_bbox=tuple(h["shape_bbox"]) if h.get("shape_bbox") else None,
        target_id=target_id,
    )
    return {"status": "ok", "tool": "resize_shape",
            "direction": direction, "amount": amount,
            "from": [sx, sy], "to": [tx, ty]}


def _fn_extend_shape(ui_graph: Dict[str, Any], direction: str) -> dict:
    direction = _norm_dir(direction)
    if direction not in ("n", "s", "e", "w"):
        return {"status": "error", "tool": "extend_shape",
                "error": f"unknown direction '{direction}'"}
    sync_current_bbox(ui_graph)
    _reselect_if_needed(ui_graph)
    h = ensure_handles(ui_graph)
    if not h or not h.get("extend"):
        return {"status": "error", "tool": "extend_shape",
                "error": "no shape selected (or extend arrows not visible)"}
    if direction not in h["extend"]:
        return {"status": "error", "tool": "extend_shape",
                "error": f"extend arrow '{direction}' not detected"}
    sg = get_scene(ui_graph)
    source_obj = _sg.get_selected(sg)
    sx, sy = h["extend"][direction]
    dx, dy = _RESIZE_DIRECTION_VECTOR[direction]
    tx, ty = int(sx + dx * _EXTEND_OFFSET_PX), int(sy + dy * _EXTEND_OFFSET_PX)
    logger.info("  [L1] extend_shape('%s') → drag (%d,%d) → (%d,%d)",
                direction, sx, sy, tx, ty)
    atom_drag(sx, sy, tx, ty)
    time.sleep(0.8)
    handles = refresh_handles(ui_graph)
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
    save_scene(ui_graph)
    return {"status": "ok", "tool": "extend_shape", "direction": direction,
            "from": [sx, sy], "to": [tx, ty],
            "new_object_id": new_obj_id,
            "source_object_id": source_obj["id"] if source_obj else None}


def _fn_rotate_shape(ui_graph: Dict[str, Any], angle_degrees: float) -> dict:
    sync_current_bbox(ui_graph)
    _reselect_if_needed(ui_graph)
    h = ensure_handles(ui_graph)
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
    logger.info("  [L1] rotate_shape(%s°) → "
                "drag rotate (%d,%d) → (%d,%d)",
                angle_degrees, rx, ry, tx, ty)
    sg = get_scene(ui_graph)
    sel = _sg.get_selected(sg)
    target_id = sel["id"] if sel else None
    atom_drag(rx, ry, tx, ty)
    time.sleep(0.4)
    scan_and_reconcile(
        ui_graph, op_name=f"rotate_shape:{angle_degrees}",
        target_id=target_id,
    )
    return {"status": "ok", "tool": "rotate_shape",
            "angle_degrees": angle_degrees,
            "from": [rx, ry], "to": [tx, ty]}


def _fn_move_shape(
    ui_graph: Dict[str, Any], direction: str, amount: int,
) -> dict:
    """Move the selected shape; escape+reclicks to guarantee select mode."""
    direction = _norm_dir(direction)
    if direction not in _RESIZE_DIRECTION_VECTOR:
        return {"status": "error", "tool": "move_shape",
                "error": f"unknown direction '{direction}'"}
    sync_current_bbox(ui_graph)
    sg = get_scene(ui_graph)
    # Use the selected object, or recover the last-created bbox'd object when
    # the selection was cleared (e.g. by place_and_label's click_empty_canvas).
    # move_shape re-clicks the shape's center below, so this physically
    # re-selects it before the drag.
    sel = _active_object(sg)
    if not sel or not sel.get("bbox"):
        return {"status": "error", "tool": "move_shape",
                "error": "no scene_graph object with a known bbox to move — "
                         "place or select a shape first"}
    _sg.set_selected(sg, sel["id"])
    target_id = sel["id"]
    bx, by, bw, bh = sel["bbox"]
    gx, gy = bx + bw // 2, by + bh // 2
    atom_press("Escape")
    time.sleep(0.25)
    atom_click_at(gx, gy)
    time.sleep(0.3)
    dx, dy = _RESIZE_DIRECTION_VECTOR[direction]
    tx, ty = int(gx + dx * amount), int(gy + dy * amount)
    logger.info("  [L1] move_shape('%s', %d) → "
                "escape+reclick, drag (%d,%d) → (%d,%d)",
                direction, amount, gx, gy, tx, ty)
    atom_drag(gx, gy, tx, ty)
    time.sleep(0.4)
    scan_and_reconcile(
        ui_graph, op_name=f"move_shape:{direction}",
        target_id=target_id,
    )
    return {"status": "ok", "tool": "move_shape",
            "direction": direction, "amount": amount,
            "from": [gx, gy], "to": [tx, ty]}


def _fn_place_label_and_move(
    ui_graph: Dict[str, Any], tool_name: str, label: str,
    direction: str, amount: int,
) -> dict:
    """Place, label, move the newly-created selected shape, then deselect."""
    direction = _norm_dir(direction)
    if direction not in _RESIZE_DIRECTION_VECTOR:
        return {"status": "error", "tool": "place_label_and_move",
                "error": f"unknown direction '{direction}'"}

    placed = _fn_place_shape(ui_graph, tool_name)
    if placed.get("status") != "ok":
        return {**placed, "tool": "place_label_and_move"}
    target_id = placed.get("scene_object_id")

    typed = _fn_type_label(label, ui_graph=ui_graph)
    if typed.get("status") != "ok":
        return {**typed, "tool": "place_label_and_move"}

    escaped = _fn_press_escape(ui_graph=ui_graph)
    if escaped.get("status") != "ok":
        return {**escaped, "tool": "place_label_and_move"}

    sg = get_scene(ui_graph)
    obj = _sg.find_by_id(sg, target_id) if target_id else _sg.get_selected(sg)
    h = ui_graph.get("selected_handles") or {}
    bbox = (obj or {}).get("bbox") or h.get("shape_bbox")
    if bbox:
        gx, gy = bbox[0] + bbox[2] // 2, bbox[1] + bbox[3] // 2
    else:
        # New draw.io shapes are dropped at the calibrated empty-canvas point.
        # This fallback lets the location-aware compound move immediately even
        # when handle detection has not yet reconciled a bbox.
        gx, gy = config.empty_canvas_point()

    dx, dy = _RESIZE_DIRECTION_VECTOR[direction]
    tx, ty = int(gx + dx * amount), int(gy + dy * amount)
    logger.info("  [L2] place_label_and_move('%s', '%s', %s, %d) drag (%d,%d) -> (%d,%d)",
                tool_name, label, direction, amount, gx, gy, tx, ty)
    atom_drag(gx, gy, tx, ty)
    time.sleep(0.4)
    if target_id:
        width = int(bbox[2]) if bbox else 80
        height = int(bbox[3]) if bbox else 40
        _sg.update_object_bbox(
            sg, target_id,
            [int(tx - width // 2), int(ty - height // 2), width, height],
            op_name=f"place_label_and_move:{direction}",
        )
        _sg.set_selected(sg, target_id)
        save_scene(ui_graph)
    atom_press("Escape")
    time.sleep(0.1)
    dispatch_result = {
        "status": "ok",
        "tool": "place_label_and_move",
        "tool_name": tool_name,
        "label": label,
        "direction": direction,
        "amount": amount,
        "scene_object_id": target_id,
        "from": [gx, gy],
        "to": [tx, ty],
    }
    return dispatch_result


def _fn_hover_object(ui_graph: Dict[str, Any], object_id: str) -> dict:
    sg = get_scene(ui_graph)
    obj = _sg.find_by_id(sg, object_id)
    if obj is None:
        obj = next((o for o in sg["objects"] if o.get("label") == object_id), None)
    if obj is None:
        return {"status": "error", "tool": "hover_object",
                "error": f"object '{object_id}' not in scene_graph"}
    if not obj.get("bbox"):
        return {"status": "error", "tool": "hover_object",
                "error": f"object '{object_id}' has no bbox yet"}
    bx, by, bw, bh = obj["bbox"]
    cx, cy = bx + bw // 2, by + bh // 2
    logger.info("  [L1] hover_object('%s') → moveTo (%d,%d)", object_id, cx, cy)
    atom_move_to(cx, cy)
    time.sleep(_HOVER_DELAY)
    return {"status": "ok", "tool": "hover_object",
            "object_id": object_id, "at": [cx, cy]}


def _fn_connect_shapes(
    ui_graph: Dict[str, Any], source_id: str, target_id: str,
    source_anchor: str = "auto",
) -> dict:
    """Draw a visible edge between two scene-graph objects.

    Algorithm:
      1. Ensure both source and target have known bboxes (click to detect).
      2. If ``source_anchor='auto'``, pick the cardinal direction (n/s/e/w)
         on the source whose center→target vector has the largest component
         (i.e. the edge of the source closest to the target).
      3. Select the source, find the extend-arrow handle at ``source_anchor``,
         and drag it to the target's center.
      4. Record the edge in the scene graph.
    """
    sync_current_bbox(ui_graph)
    sg = get_scene(ui_graph)

    # Resolve source and target — accept either obj_NNN IDs or labels.
    src = _sg.find_by_id(sg, source_id)
    if src is None:
        src = next((o for o in sg["objects"] if o.get("label") == source_id), None)
    tgt = _sg.find_by_id(sg, target_id)
    if tgt is None:
        tgt = next((o for o in sg["objects"] if o.get("label") == target_id), None)

    if not src or not tgt:
        return {"status": "error", "tool": "connect_shapes",
                "error": f"source '{source_id}' or target '{target_id}' "
                         f"not in scene_graph"}
    # Ensure both source and target have bboxes (click_node triggers
    # handle detection + bbox reconciliation via scan_and_reconcile).
    from core.tools.actions import _fn_click_node as _click_node
    if not src.get("bbox"):
        _click_node(ui_graph, source_id)
        src = _sg.find_by_id(sg, source_id)
    if not tgt.get("bbox"):
        _click_node(ui_graph, target_id)
        tgt = _sg.find_by_id(sg, target_id)
    if not src.get("bbox") or not tgt.get("bbox"):
        return {"status": "error", "tool": "connect_shapes",
                "error": f"could not determine bbox — "
                         f"src.bbox={src.get('bbox')}, tgt.bbox={tgt.get('bbox')}"}
    sbx, sby, sbw, sbh = src["bbox"]
    tbx, tby, tbw, tbh = tgt["bbox"]
    src_cx, src_cy = sbx + sbw // 2, sby + sbh // 2
    tgt_cx, tgt_cy = tbx + tbw // 2, tby + tbh // 2

    # Auto-anchor: pick the source edge whose outward direction best
    # aligns with the source→target vector.  If the horizontal distance
    # dominates, use east/west; otherwise north/south.
    if source_anchor != "auto":
        source_anchor = _norm_dir(source_anchor)
    if source_anchor == "auto":
        if abs(tgt_cx - src_cx) >= abs(tgt_cy - src_cy):
            source_anchor = "e" if tgt_cx > src_cx else "w"
        else:
            source_anchor = "s" if tgt_cy > src_cy else "n"
    elif source_anchor not in ("n", "s", "e", "w"):
        return {"status": "error", "tool": "connect_shapes",
                "error": f"source_anchor must be n/s/e/w/auto, got '{source_anchor}'"}

    # Ensure the source shape is selected so its extend-arrows are visible.
    if not src.get("selected") or not ui_graph.get("selected_handles"):
        _click_node(ui_graph, source_id)
    handles = ui_graph.get("selected_handles") or {}
    extend = handles.get("extend", {})

    # Determine the drag start point: prefer the detected extend-arrow
    # handle if available; otherwise fall back to the source's anchor
    # point nudged slightly outward so the drag starts just outside the
    # shape border (where drawio's connection zone begins).
    if source_anchor not in extend:
        sa_pt = src["anchors"][source_anchor]
        nudge = 12
        dx, dy = _RESIZE_DIRECTION_VECTOR[source_anchor]
        sx, sy = sa_pt[0] + dx * nudge, sa_pt[1] + dy * nudge
    else:
        sx, sy = extend[source_anchor]
    logger.info("  [L1] connect_shapes(%s→%s) "
                "drag (%d,%d) → (%d,%d)",
                source_id, target_id, sx, sy, tgt_cx, tgt_cy)
    atom_drag(sx, sy, tgt_cx, tgt_cy,
              duration=config.drag_duration() * 1.5, hold_pre=0.15)
    time.sleep(0.6)
    opp = {"n": "s", "s": "n", "e": "w", "w": "e"}[source_anchor]
    _sg.add_edge(
        sg, source=source_id, target=target_id,
        source_anchor=source_anchor, target_anchor=opp,
        op_name="connect_shapes",
    )
    save_scene(ui_graph)
    return {"status": "ok", "tool": "connect_shapes",
            "source": source_id, "target": target_id,
            "source_anchor": source_anchor, "target_anchor": opp,
            "from": [sx, sy], "to": [tgt_cx, tgt_cy]}


def _fn_label_edge(ui_graph: Dict[str, Any], edge_id: str, text: str) -> dict:
    """Double-click an edge midpoint to add or edit its text label.

    Computes the midpoint between the source anchor point and the target
    anchor point (accurate for straight draw.io edges), double-clicks there
    to enter the edge's inline label editor, types the text, and escapes.
    """
    from core.tools.atoms import atom_write
    sg = get_scene(ui_graph)

    edge = _sg.find_edge_by_id(sg, edge_id)
    if edge is None:
        return {"status": "error", "tool": "label_edge",
                "error": f"edge '{edge_id}' not in scene_graph"}

    src = _sg.find_by_id(sg, edge["source"])
    tgt = _sg.find_by_id(sg, edge["target"])
    if not src or not tgt:
        return {"status": "error", "tool": "label_edge",
                "error": f"source/target objects missing for edge '{edge_id}'"}
    if not src.get("bbox") or not tgt.get("bbox"):
        return {"status": "error", "tool": "label_edge",
                "error": "source or target has no bbox — call scan_handles or click_node first"}

    # Use stored anchor points for the midpoint; fall back to bbox centers.
    sa, ta = edge.get("source_anchor", "e"), edge.get("target_anchor", "w")
    src_anc = (src.get("anchors") or {}).get(sa)
    tgt_anc = (tgt.get("anchors") or {}).get(ta)
    if src_anc and tgt_anc:
        sx, sy = src_anc
        ex, ey = tgt_anc
    else:
        sbx, sby, sbw, sbh = src["bbox"]
        tbx, tby, tbw, tbh = tgt["bbox"]
        sx, sy = sbx + sbw // 2, sby + sbh // 2
        ex, ey = tbx + tbw // 2, tby + tbh // 2

    mx, my = (sx + ex) // 2, (sy + ey) // 2
    logger.info("  [L1] label_edge('%s', '%s') → double-click (%d,%d)", edge_id, text, mx, my)

    atom_press("Escape")           # ensure clean state before clicking the edge
    time.sleep(0.2)
    atom_click_at(mx, my, clicks=2)
    time.sleep(0.4)
    atom_write(text)
    atom_press("Escape")
    time.sleep(0.3)

    _sg.update_edge_label(sg, edge_id, text, op_name="label_edge")
    save_scene(ui_graph)
    return {"status": "ok", "tool": "label_edge",
            "edge_id": edge_id, "text": text, "at": [mx, my]}


# ===========================================================================
# Public aliases (for direct script use and backward compat)
# ===========================================================================

place_shape = _fn_place_shape
type_label = _fn_type_label
press_escape = _fn_press_escape
