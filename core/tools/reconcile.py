"""
Reconcile — inter-operation scanning and scene-graph threading.

This module is the bridge between **perception** (CV-based handle
detection) and **state** (the scene graph).  After geometry-changing
operations, it re-detects the selection bbox and reconciles it back
into the matching scene-graph object so the next operation reasons
about an accurate canvas state.

Shared by ``core.tools.actions`` and ``domains.drawio.operations``.

Handle detection is domain-specific.  The active domain must expose a
``detect_handles(screenshot_path) -> SelectionHandles`` function in its
``domains.<name>.perception`` module.  Domains that have no selection-
chrome concept (e.g. iMovie) simply omit the function; reconcile then
skips handle-based bbox updates and returns an empty SelectionHandles.
"""

from __future__ import annotations

import importlib
import logging
import time
from typing import Any, Callable, Dict, Optional

from core.capture import screenshot as _capture_screenshot
from core.perception.handles import SelectionHandles  # data structure only
from core.state import scene_graph as _sg
from core.tools.atoms import atom_move_to, atom_press

logger = logging.getLogger(__name__)


# ===========================================================================
# Domain handle-detector loader
# ===========================================================================

def _load_handle_detector() -> Optional[Callable[[str], SelectionHandles]]:
    """Return the active domain's ``detect_handles`` function, or None.

    Loads ``domains.<domain>.perception.detect_handles`` at call time so the
    domain plugin can be swapped without restarting.  Returns None when the
    domain has no handle concept (e.g. iMovie).
    """
    from core import config as _cfg
    try:
        mod = importlib.import_module(f"domains.{_cfg.domain()}.perception")
        fn = getattr(mod, "detect_handles", None)
        return fn  # None if the domain doesn't define it
    except ImportError:
        return None


# ===========================================================================
# Scene-graph threading helpers
# ===========================================================================

def get_scene(ui_graph: Dict[str, Any]) -> Dict[str, Any]:
    """Lazy-load the scene_graph onto ui_graph['scene_graph']."""
    sg = ui_graph.get("scene_graph")
    if sg is None:
        sg = _sg.load()
        ui_graph["scene_graph"] = sg
    return sg


def save_scene(ui_graph: Dict[str, Any]) -> None:
    """Persist the in-memory scene_graph to disk."""
    sg = ui_graph.get("scene_graph")
    if sg is not None:
        _sg.save(sg)


# ===========================================================================
# Selection-handle refresh and reconciliation
# ===========================================================================

_HOVER_DELAY = 0.7


def refresh_handles(
    ui_graph: Dict[str, Any], hint_bbox: Optional[tuple] = None,
) -> SelectionHandles:
    """Snapshot the screen, detect selection handles, store on ui_graph.

    If the active domain does not provide a ``detect_handles`` function
    (e.g. a domain without selection chrome), clears ``selected_handles``
    and returns an empty SelectionHandles immediately.
    """
    detect_fn = _load_handle_detector()
    if detect_fn is None:
        ui_graph["selected_handles"] = None
        return SelectionHandles()

    path = _capture_screenshot("_handles_scan_a.png")
    handles = detect_fn(path)

    bbox = handles.shape_bbox or hint_bbox
    if bbox and (not handles.extend or len(handles.extend) < 4):
        cx, cy = bbox[0] + bbox[2] // 2, bbox[1] + bbox[3] // 2
        atom_move_to(cx, cy)
        time.sleep(_HOVER_DELAY)
        path = _capture_screenshot("_handles_scan_b.png")
        handles = detect_fn(path)

    ui_graph["selected_handles"] = handles.to_dict() if handles.is_valid() else None
    return handles


def sync_current_bbox(ui_graph: Dict[str, Any]) -> None:
    """If the currently-selected scene_graph object has no bbox, escape +
    scan to fill it."""
    sg = get_scene(ui_graph)
    sel = _sg.get_selected(sg)
    if sel is None or sel.get("bbox") is not None:
        return
    target_id = sel["id"]
    atom_press("Escape")
    time.sleep(0.3)
    scan_and_reconcile(ui_graph, op_name="sync_current_bbox",
                       target_id=target_id)


def scan_and_reconcile(
    ui_graph: Dict[str, Any], op_name: str,
    *, hint_bbox: Optional[tuple] = None,
    target_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Re-detect handles, update the matching scene_graph object's bbox."""
    handles = refresh_handles(ui_graph, hint_bbox=hint_bbox)
    sg = get_scene(ui_graph)
    if not handles.is_valid() or not handles.shape_bbox:
        _sg.set_selected(sg, None)
        save_scene(ui_graph)
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
    save_scene(ui_graph)
    return target


def ensure_handles(ui_graph: Dict[str, Any]) -> Optional[dict]:
    """Return cached handles dict, refreshing once (and escape+retry) if absent."""
    h = ui_graph.get("selected_handles")
    if h:
        return h
    refresh_handles(ui_graph)
    h = ui_graph.get("selected_handles")
    if h:
        return h
    logger.debug("No handles detected — sending defensive Escape")
    atom_press("Escape")
    time.sleep(0.3)
    scan_and_reconcile(ui_graph, op_name="defensive_escape")
    return ui_graph.get("selected_handles")
