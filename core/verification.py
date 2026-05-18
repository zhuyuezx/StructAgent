"""
Post-action verification for closed-loop pipeline control.
"""

from __future__ import annotations

from typing import Any, Dict

import cv2
import numpy as np

from core import config


def verify_action(
    tool_name: str,
    params: Dict[str, Any],
    before_graph: Dict[str, Any],
    after_graph: Dict[str, Any],
    before_screenshot: str,
    after_screenshot: str,
    dispatch_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a lightweight verification record for one executed tool."""
    before_count = len(before_graph.get("Canvas_Nodes", []))
    after_count = len(after_graph.get("Canvas_Nodes", []))
    changed = _canvas_changed(before_screenshot, after_screenshot)

    if dispatch_result.get("status") == "error":
        return _result(False, "dispatch_error", before_count, after_count, changed)

    if tool_name in {"place_shape", "place_and_label", "place_shape_then_edit_label"}:
        new_tracks = after_graph.get("_canvas_tracking", {}).get("new_tracks", [])
        if after_count == before_count + 1 or new_tracks:
            return _result(True, "observed_canvas_node_count_increased",
                           before_count, after_count, changed,
                           new_tracks=new_tracks)
        if changed:
            return _result(True, "canvas_changed_but_node_count_did_not_increase",
                           before_count, after_count, changed, confidence="weak")
        return _result(False, "no_canvas_change_after_place",
                       before_count, after_count, changed)

    if tool_name in {"type_label", "edit_label"}:
        if changed:
            return _result(True, "canvas_changed_after_text_action",
                           before_count, after_count, changed, confidence="weak")
        return _result(False, "no_canvas_change_after_text_action",
                       before_count, after_count, changed)

    if tool_name in {"press_escape", "click_empty_canvas", "press_enter"}:
        return _result(True, "selection_state_not_strictly_verified",
                       before_count, after_count, changed, confidence="weak")

    if tool_name in {
        "drag_node", "drag_node_near", "drag_node_to_zone",
        "move_and_deselect", "move_node_to_zone_and_deselect",
    }:
        return _verify_drag(params, before_graph, after_graph, before_count, after_count, changed)

    if tool_name == "delete_node":
        target = params.get("node_ref")
        before_node = _find_node(before_graph, target)
        after_node = _find_node(after_graph, target)
        if before_node and after_node is None:
            return _result(True, "target_node_disappeared_after_delete",
                           before_count, after_count, changed,
                           target_node_id=target,
                           before_position=_position(before_node))
        if after_count < before_count:
            return _result(True, "observed_canvas_node_count_decreased",
                           before_count, after_count, changed,
                           target_node_id=target)
        return _result(False, "target_node_not_deleted",
                       before_count, after_count, changed)

    return _result(True, "no_specific_verifier_for_tool",
                   before_count, after_count, changed, confidence="weak")


def _result(
    passed: bool,
    reason: str,
    before_count: int,
    after_count: int,
    changed: bool,
    *,
    confidence: str = "strong",
    **extra: Any,
) -> Dict[str, Any]:
    result = {
        "passed": passed,
        "confidence": confidence,
        "reason": reason,
        "before_node_count": before_count,
        "after_node_count": after_count,
        "canvas_changed": changed,
        "text_placement": "unknown",
    }
    result.update(extra)
    return result


def _verify_drag(
    params: Dict[str, Any],
    before_graph: Dict[str, Any],
    after_graph: Dict[str, Any],
    before_count: int,
    after_count: int,
    changed: bool,
) -> Dict[str, Any]:
    target = params.get("node_ref")
    before_node = _find_node(before_graph, target)
    after_node = _find_node(after_graph, target)
    if not before_node or not after_node:
        return _result(False, "target_node_not_tracked_across_drag",
                       before_count, after_count, changed,
                       target_node_id=target)

    dx = after_node["x"] - before_node["x"]
    dy = after_node["y"] - before_node["y"]
    zone = params.get("zone")
    expected = _expected_direction(zone)
    direction_ok = _direction_matches(dx, dy, expected)
    movement_delta = {"dx": dx, "dy": dy}
    common = {
        "target_node_id": target,
        "before_position": _position(before_node),
        "after_position": _position(after_node),
        "expected_direction": expected,
        "movement_delta": movement_delta,
    }
    if expected and direction_ok:
        return _result(True, "target_node_moved_expected_direction",
                       before_count, after_count, changed, **common)
    if not expected and (abs(dx) >= 8 or abs(dy) >= 8):
        return _result(True, "target_node_moved",
                       before_count, after_count, changed, **common)
    if changed:
        return _result(True, "canvas_changed_but_target_motion_not_confirmed",
                       before_count, after_count, changed,
                       confidence="weak", **common)
    return _result(False, "target_node_did_not_move_after_drag",
                   before_count, after_count, changed, **common)


def _find_node(graph: Dict[str, Any], ref: str | None) -> Dict[str, Any] | None:
    if not ref:
        return None
    for node in graph.get("Canvas_Nodes", []):
        if node.get("id") == ref or node.get("text") == ref:
            return node
    return None


def _position(node: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "x": node.get("x"),
        "y": node.get("y"),
        "w": node.get("w"),
        "h": node.get("h"),
    }


def _expected_direction(zone: str | None) -> str | None:
    if not zone:
        return None
    zone_name = str(zone).lower().replace("-", "_").replace(" ", "_")
    if "right" in zone_name:
        return "right"
    if "left" in zone_name:
        return "left"
    if "top" in zone_name or "upper" in zone_name:
        return "up"
    if "bottom" in zone_name or "lower" in zone_name:
        return "down"
    return None


def _direction_matches(dx: int, dy: int, expected: str | None) -> bool:
    threshold = 8
    if expected == "right":
        return dx >= threshold
    if expected == "left":
        return dx <= -threshold
    if expected == "up":
        return dy <= -threshold
    if expected == "down":
        return dy >= threshold
    return False


def _canvas_changed(before_path: str, after_path: str) -> bool:
    before = cv2.imread(before_path)
    after = cv2.imread(after_path)
    if before is None or after is None:
        return False

    before_crop = _canvas_crop(before)
    after_crop = _canvas_crop(after)
    if before_crop.shape != after_crop.shape or before_crop.size == 0:
        return False

    diff = cv2.absdiff(before_crop, after_crop)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    changed_pixels = int(np.count_nonzero(gray > 18))
    return changed_pixels > 50


def _canvas_crop(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    region = config.canvas_region()
    if region is None:
        sidebar = config.sidebar_region()
        region = (sidebar[2], 0, w, h)

    x1, y1, x2, y2 = region
    x1 = max(0, min(w, x1))
    x2 = max(0, min(w, x2))
    y1 = max(0, min(h, y1))
    y2 = max(0, min(h, y2))
    return img[y1:y2, x1:x2]
