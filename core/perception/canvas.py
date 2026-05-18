"""
Canvas perception for the dynamic draw.io scene.

This is intentionally approximate: it detects visible closed shapes well
enough for the pipeline to verify that actions changed the canvas.
"""

from __future__ import annotations

import os
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

    mask = _stroke_mask(crop)
    contours = _shape_contours(mask)
    nodes = []
    for contour in contours:
        bx, by, bw, bh = cv2.boundingRect(contour)
        candidate = _candidate_metrics(contour, mask, bx, by, bw, bh)
        if not _is_node_candidate(candidate, crop.shape):
            continue

        cx = x1 + bx + bw // 2
        cy = y1 + by + bh // 2
        confidence = min(0.98, max(
            0.35,
            0.55 * candidate["rectangularity"] + 0.45 * min(candidate["stroke_density"] * 6, 1),
        ))
        nodes.append({
            "id": f"Observed_Node_{len(nodes) + 1}",
            "text": "",
            "x": cx // scale,
            "y": cy // scale,
            "w": bw // scale,
            "h": bh // scale,
            "confidence": round(float(confidence), 3),
            "source": "opencv_canvas_contour",
            "area": round(float(candidate["area"]), 1),
            "stroke_density": round(float(candidate["stroke_density"]), 4),
            "rectangularity": round(float(candidate["rectangularity"]), 4),
            "_px": {"x": cx, "y": cy, "w": bw, "h": bh},
        })

    nodes.sort(key=lambda n: (n["y"], n["x"]))
    for i, node in enumerate(nodes, start=1):
        node["id"] = f"Observed_Node_{i}"
    return nodes


def annotate_canvas(
    screenshot_path: str,
    nodes: List[Dict[str, Any]],
    output_path: str,
) -> str:
    """Draw observed canvas nodes on a screenshot and save it."""
    img = cv2.imread(screenshot_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {screenshot_path}")

    scale = config.screen_scale()
    for i, node in enumerate(nodes, start=1):
        p = node.get("_px", {
            "x": node["x"] * scale,
            "y": node["y"] * scale,
            "w": node["w"] * scale,
            "h": node["h"] * scale,
        })
        x1 = p["x"] - p["w"] // 2
        y1 = p["y"] - p["h"] // 2
        x2 = p["x"] + p["w"] // 2
        y2 = p["y"] + p["h"] // 2
        label = f"{node.get('id', f'Node_{i}')} {node.get('confidence', '')}"
        cv2.rectangle(img, (x1, y1), (x2, y2), (255, 128, 0), 2)
        cv2.putText(img, label, (x1, max(12, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 128, 0), 1)

    cv2.imwrite(output_path, img)
    print(f"[PERCEPTION] Canvas annotation → {os.path.abspath(output_path)}")
    return output_path


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
                "stroke_density": n.get("stroke_density"),
                "rectangularity": n.get("rectangularity"),
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


def _stroke_mask(crop: np.ndarray) -> np.ndarray:
    """Keep darker strokes while suppressing light draw.io grid lines."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, mask = cv2.threshold(blurred, 220, 255, cv2.THRESH_BINARY_INV)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    return mask


def _shape_contours(mask: np.ndarray) -> List[np.ndarray]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return contours


def _candidate_metrics(
    contour: np.ndarray,
    mask: np.ndarray,
    x: int,
    y: int,
    width: int,
    height: int,
) -> Dict[str, float]:
    rect_area = max(width * height, 1)
    roi = mask[y:y + height, x:x + width]
    stroke_pixels = int(np.count_nonzero(roi))
    return {
        "area": float(cv2.contourArea(contour)),
        "rect_area": float(rect_area),
        "stroke_density": stroke_pixels / rect_area,
        "rectangularity": float(cv2.contourArea(contour)) / rect_area,
        "x": float(x),
        "y": float(y),
        "width": float(width),
        "height": float(height),
    }


def _is_node_candidate(candidate: Dict[str, float], crop_shape: Tuple[int, ...]) -> bool:
    crop_h, crop_w = crop_shape[:2]
    width = candidate["width"]
    height = candidate["height"]
    x = candidate["x"]
    y = candidate["y"]
    area = width * height
    crop_area = max(crop_w * crop_h, 1)
    aspect = width / height if height else 0
    touches_border = x <= 2 or y <= 2 or x + width >= crop_w - 2 or y + height >= crop_h - 2

    if touches_border:
        return False
    if width < 50 or height < 32:
        return False
    if area < 1800 or area > crop_area * 0.12:
        return False
    if not 0.35 <= aspect <= 5.0:
        return False
    if candidate["stroke_density"] < 0.012 or candidate["stroke_density"] > 0.55:
        return False
    if candidate["rectangularity"] < 0.18:
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
