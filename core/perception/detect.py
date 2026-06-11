"""
Detect — OpenCV-based UI element detection.

Generic icon/region detection over a screenshot. Domain-agnostic — region
hints come from config (or callers).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np

from core import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Icon detection (OpenCV)
# ---------------------------------------------------------------------------

def detect_icons(
    screenshot_path: str,
    region: Tuple[int, int, int, int] | None = None,
    scale: float | None = None,
) -> List[Dict[str, Any]]:
    """
    Detect icon-sized rectangular regions inside *region*.

    Works on the raw screenshot pixels and returns coordinates in target input
    coordinates (screenshot pixels divided by ``scale``).
    """
    scale = float(scale if scale is not None else config.screen_scale())
    min_sz, max_sz = config.icon_size_range()
    nms_dist = config.nms_distance()

    img = cv2.imread(screenshot_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {screenshot_path}")

    if region is None:
        region = config.sidebar_region()
    x1, y1, x2, y2 = region
    crop = img[y1:y2, x1:x2]

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 30, 120)
    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    icons = []
    for c in contours:
        bx, by, bw, bh = cv2.boundingRect(c)
        if min_sz <= bw <= max_sz and min_sz <= bh <= max_sz:
            aspect = bw / bh if bh > 0 else 0
            if 0.4 <= aspect <= 2.5:
                cx = x1 + bx + bw // 2
                cy = y1 + by + bh // 2
                icons.append({
                    "x": round(cx / scale), "y": round(cy / scale),
                    "w": round(bw / scale), "h": round(bh / scale),
                    "_px": {"x": cx, "y": cy, "w": bw, "h": bh},
                })

    icons = _nms(icons, nms_dist)
    icons.sort(key=lambda i: (i["y"], i["x"]))
    return icons


def _nms(icons: List[Dict], threshold: int = 20) -> List[Dict]:
    """Remove duplicate detections within *threshold* logical pixels."""
    if not icons:
        return []
    icons.sort(key=lambda i: i["w"] * i["h"], reverse=True)
    keep = []
    for icon in icons:
        if not any(
            abs(icon["x"] - k["x"]) < threshold and abs(icon["y"] - k["y"]) < threshold
            for k in keep
        ):
            keep.append(icon)
    return keep


# ---------------------------------------------------------------------------
# Annotation (visual debug)
# ---------------------------------------------------------------------------

def annotate(
    screenshot_path: str,
    icons: List[Dict[str, Any]],
    output_path: str,
    scale: float | None = None,
) -> str:
    """Draw bounding boxes on the screenshot and save. Returns output path."""
    img = cv2.imread(screenshot_path)
    scale = float(scale if scale is not None else config.screen_scale())

    for i, icon in enumerate(icons):
        p = icon.get("_px", {
            "x": round(icon["x"] * scale), "y": round(icon["y"] * scale),
            "w": round(icon["w"] * scale), "h": round(icon["h"] * scale),
        })
        x1 = p["x"] - p["w"] // 2
        y1 = p["y"] - p["h"] // 2
        x2 = p["x"] + p["w"] // 2
        y2 = p["y"] + p["h"] // 2

        label = icon.get("label", f"#{i}")
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(img, label, (x1, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

    cv2.imwrite(output_path, img)
    logger.info("Annotated → %s", os.path.abspath(output_path))
    return output_path
