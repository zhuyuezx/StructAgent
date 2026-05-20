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
    try:
        node = resolve_node(ui_graph, node_ref)
        x, y = node["x"], node["y"]
    except KeyError:
        sg = get_scene(ui_graph)
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
    """Drag a calibrated canvas node by id to (target_x, target_y)."""
    node = resolve_node(ui_graph, node_ref)
    sx, sy = node["x"], node["y"]
    logger.info("  [L1] drag_node('%s') → (%d,%d) → (%d,%d)", node_ref, sx, sy, target_x, target_y)
    atom_drag(sx, sy, target_x, target_y)
    return {"status": "ok", "tool": "drag_node", "node_ref": node_ref,
            "from": [sx, sy], "to": [target_x, target_y]}


def _fn_drag_node_near(
    ui_graph: Dict[str, Any], node_ref: str, reference_node: str,
    offset_x: int = 200, offset_y: int = 0,
) -> dict:
    """Drag *node_ref* to a position relative to *reference_node*."""
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
