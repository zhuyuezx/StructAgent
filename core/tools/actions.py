"""
Actions — L1 operation implementations (no registration).

These functions are referenced by JSON definitions in state/tools/ via
"python_fn": "core.tools.actions:<fn_name>".  Registration (ToolNode
creation, children, level computation) is handled entirely by the JSON
loader; this file is pure implementation.

Each function:
  - Resolves a node/object reference to screen coordinates, OR
  - Composes multiple atom calls into one semantic step.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from core import config
from core.state import scene_graph as _sg
from core.tools.atoms import atom_click_at, atom_drag, atom_hotkey, atom_press
from core.tools.reconcile import get_scene, save_scene, scan_and_reconcile
from core.tools.registry import resolve_node

logger = logging.getLogger(__name__)


# ===========================================================================
# Node reference resolution
# ===========================================================================

def _resolve_node_geom(ui_graph: Dict[str, Any], ref: str) -> Dict[str, int]:
    """Resolve a node reference (id OR label) to canvas geometry.

    Looks up the calibrated ``Canvas_Nodes`` first (legacy perception), then
    the **live scene graph** by object id or label, using the object's bbox
    (center + size). This is why ``move_and_deselect`` / ``drag_node`` /
    ``resize_node`` can reference ``obj_001`` *or* its label (e.g. ``"R1"``):
    the scene graph is the source of truth now that ``Canvas_Nodes`` stays
    empty. Raises ``KeyError`` listing the scene objects if nothing matches.

    Returns ``{"x", "y", "w", "h"}`` where (x, y) is the node center.
    """
    try:
        node = resolve_node(ui_graph, ref)
        return {"x": node["x"], "y": node["y"],
                "w": node.get("w", 120), "h": node.get("h", 60)}
    except KeyError:
        pass

    sg = get_scene(ui_graph)
    obj = _sg.find_by_id(sg, ref)
    if obj is None:
        obj = next((o for o in sg["objects"] if o.get("label") == ref), None)
    if obj is not None and obj.get("bbox"):
        bx, by, bw, bh = obj["bbox"]
        return {"x": bx + bw // 2, "y": by + bh // 2, "w": bw, "h": bh}

    avail = [(o.get("id"), o.get("label")) for o in sg.get("objects", [])]
    raise KeyError(
        f"Node '{ref}' not found in Canvas_Nodes or scene graph. "
        f"Scene objects (id, label): {avail}"
    )


def _resolve_node_xy(ui_graph: Dict[str, Any], ref: str) -> tuple:
    """Resolve a node reference to its center ``(x, y)``. See _resolve_node_geom."""
    g = _resolve_node_geom(ui_graph, ref)
    return g["x"], g["y"]


# ===========================================================================
# Click actions
# ===========================================================================

def _fn_click_empty_canvas(ui_graph: Optional[Dict[str, Any]] = None) -> dict:
    """Click the configured empty-canvas point and clear any selection."""
    x, y = config.empty_canvas_point()
    logger.info("  [L1] click_empty_canvas → (%d, %d)", x, y)
    atom_click_at(x, y)
    if ui_graph is not None:
        ui_graph["selected_handles"] = None
        sg = get_scene(ui_graph)
        _sg.set_selected(sg, None)
        save_scene(ui_graph)
    return {"status": "ok", "tool": "click_empty_canvas", "x": x, "y": y}


def _fn_click_node(
    ui_graph: Dict[str, Any], node_ref: str, clicks: int = 1,
) -> dict:
    """Click a canvas node by id or label (resolves via ui_graph or scene_graph)."""
    x, y = _resolve_node_xy(ui_graph, node_ref)
    logger.info("  [L1] click_node('%s', clicks=%d) → (%d, %d)", node_ref, clicks, x, y)
    atom_click_at(x, y, clicks=clicks)
    time.sleep(0.4)
    target = scan_and_reconcile(ui_graph, op_name="click_node")
    return {"status": "ok", "tool": "click_node", "node_ref": node_ref,
            "x": x, "y": y,
            "selected_object": target["id"] if target else None}


def _fn_double_click_node(ui_graph: Dict[str, Any], node_ref: str) -> dict:
    """Double-click a canvas node to enter text-edit mode."""
    return _fn_click_node(ui_graph, node_ref, clicks=2)


# ===========================================================================
# Drag actions
# ===========================================================================

def _fn_drag_node(
    ui_graph: Dict[str, Any], node_ref: str, target_x: int, target_y: int,
) -> dict:
    """Drag a canvas node (by id or label) to (target_x, target_y)."""
    sx, sy = _resolve_node_xy(ui_graph, node_ref)
    logger.info("  [L1] drag_node('%s') → (%d,%d) → (%d,%d)", node_ref, sx, sy, target_x, target_y)
    atom_drag(sx, sy, target_x, target_y)
    return {"status": "ok", "tool": "drag_node", "node_ref": node_ref,
            "from": [sx, sy], "to": [target_x, target_y]}


def _fn_drag_node_near(
    ui_graph: Dict[str, Any], node_ref: str, reference_node: str,
    offset_x: int = 200, offset_y: int = 0,
) -> dict:
    """Drag *node_ref* to a position relative to *reference_node*."""
    rx, ry = _resolve_node_xy(ui_graph, reference_node)
    return _fn_drag_node(ui_graph, node_ref, rx + offset_x, ry + offset_y)


def _fn_resize_node(
    ui_graph: Dict[str, Any], node_ref: str, new_width: int, new_height: int,
) -> dict:
    """Resize a canvas node (by id or label) by dragging its handle."""
    geom = _resolve_node_geom(ui_graph, node_ref)
    x, y, w, h = geom["x"], geom["y"], geom["w"], geom["h"]
    handle_x, handle_y = x + w // 2, y + h // 2
    new_hx, new_hy = x + new_width // 2, y + new_height // 2
    logger.info("  [L1] resize_node('%s', %d×%d)", node_ref, new_width, new_height)
    atom_click_at(x, y)
    time.sleep(0.2)
    atom_drag(handle_x, handle_y, new_hx, new_hy, duration=0.3)
    return {"status": "ok", "tool": "resize_node", "node_ref": node_ref,
            "new_size": [new_width, new_height]}


# ===========================================================================
# Keyboard actions
# ===========================================================================

def _fn_hotkey(keys: list) -> dict:
    """Press a key chord given as a list, e.g. ["command", "z"]."""
    combo = " + ".join(keys) if isinstance(keys, list) else str(keys)
    logger.info("  [L1] hotkey(%s)", combo)
    if isinstance(keys, list):
        atom_hotkey(*keys)
    else:
        atom_hotkey(keys)
    return {"status": "ok", "tool": "hotkey", "keys": keys}


def _fn_undo() -> dict:
    """Undo the last canvas action (Cmd+Z)."""
    logger.info("  [L1] undo (Cmd+Z)")
    atom_hotkey("command", "z")
    return {"status": "ok", "tool": "undo"}


def _fn_press_enter() -> dict:
    logger.info("  [L1] press_enter")
    atom_press("Return")
    return {"status": "ok", "tool": "press_enter"}


def _fn_press_delete() -> dict:
    logger.info("  [L1] press_delete")
    atom_press("BackSpace")
    return {"status": "ok", "tool": "press_delete"}


def _fn_select_all() -> dict:
    logger.info("  [L1] select_all (Cmd+A)")
    atom_hotkey("command", "a")
    return {"status": "ok", "tool": "select_all"}
