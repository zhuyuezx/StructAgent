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

    if tool_name in {"place_shape", "place_and_label"}:
        if after_count > before_count:
            return _result(True, "observed_canvas_node_count_increased",
                           before_count, after_count, changed)
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
) -> Dict[str, Any]:
    return {
        "passed": passed,
        "confidence": confidence,
        "reason": reason,
        "before_node_count": before_count,
        "after_node_count": after_count,
        "canvas_changed": changed,
    }


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
