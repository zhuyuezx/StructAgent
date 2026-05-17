"""
Canvas perception for the dynamic draw.io scene.

This is intentionally approximate: it detects visible closed shapes well
enough for the pipeline to verify that actions changed the canvas.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import cv2
import numpy as np

from core import config


def observe_canvas(
    screenshot_path: str,
    region: Tuple[int, int, int, int] | None = None,
) -> List[Dict[str, Any]]:
    """
    Return approximate canvas nodes visible in a screenshot.

    Coordinates are logical pixels. Region values are physical pixels.
    """
    img = cv2.imread(screenshot_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {screenshot_path}")

    scale = config.screen_scale()
    x1, y1, x2, y2 = _clamped_region(img, region)
    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        return []

    contours = _shape_contours(crop)
    nodes = []
    for contour in contours:
        bx, by, bw, bh = cv2.boundingRect(contour)
        if not _is_node_candidate(bw, bh, crop.shape):
            continue

        cx = x1 + bx + bw // 2
        cy = y1 + by + bh // 2
        area = cv2.contourArea(contour)
        rect_area = max(bw * bh, 1)
        confidence = min(0.95, max(0.35, area / rect_area))
        nodes.append({
            "id": f"Observed_Node_{len(nodes) + 1}",
            "text": "",
            "x": cx // scale,
            "y": cy // scale,
            "w": bw // scale,
            "h": bh // scale,
            "confidence": round(float(confidence), 3),
            "source": "opencv_canvas_contour",
            "_px": {"x": cx, "y": cy, "w": bw, "h": bh},
        })

    nodes.sort(key=lambda n: (n["y"], n["x"]))
    for i, node in enumerate(nodes, start=1):
        node["id"] = f"Observed_Node_{i}"
    return nodes


def summarize_graph(ui_graph: Dict[str, Any]) -> Dict[str, Any]:
    """Return a compact trace-friendly graph summary."""
    elements = ui_graph.get("UI_Elements", {})
    nodes = ui_graph.get("Canvas_Nodes", [])
    families = tool_families(elements)
    return {
        "ui_element_count": len(elements),
        "canvas_node_count": len(nodes),
        "canvas_nodes": [
            {
                "id": n.get("id"),
                "text": n.get("text", ""),
                "confidence": n.get("confidence"),
                "source": n.get("source"),
            }
            for n in nodes
        ],
        "tool_families": families,
    }


def tool_families(ui_elements: Dict[str, Any]) -> Dict[str, List[str]]:
    """Group repeated sidebar labels like Rectangle_Tool_1 into families."""
    families: Dict[str, List[str]] = {}
    for name in sorted(ui_elements):
        base = _family_name(name)
        families.setdefault(base, []).append(name)
    return {k: v for k, v in families.items() if len(v) > 1}


def _clamped_region(
    img: np.ndarray,
    region: Tuple[int, int, int, int] | None,
) -> Tuple[int, int, int, int]:
    h, w = img.shape[:2]
    if region is None:
        region = config.canvas_region()
    if region is None:
        sidebar = config.sidebar_region()
        region = (sidebar[2], 0, w, h)

    x1, y1, x2, y2 = region
    return (
        max(0, min(w, x1)),
        max(0, min(h, y1)),
        max(0, min(w, x2)),
        max(0, min(h, y2)),
    )


def _shape_contours(crop: np.ndarray) -> List[np.ndarray]:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    edges = cv2.Canny(blurred, 40, 140)
    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return contours


def _is_node_candidate(width: int, height: int, crop_shape: Tuple[int, ...]) -> bool:
    crop_h, crop_w = crop_shape[:2]
    area = width * height
    crop_area = max(crop_w * crop_h, 1)
    aspect = width / height if height else 0

    if width < 35 or height < 20:
        return False
    if area < 900 or area > crop_area * 0.25:
        return False
    if not 0.25 <= aspect <= 4.5:
        return False
    return True


def _family_name(name: str) -> str:
    base = name
    if base.endswith("_Tool"):
        base = base[:-5]
    parts = base.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        base = parts[0]
    return f"{base}_Family"
