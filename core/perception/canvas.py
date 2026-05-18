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
    nodes = [dict(n) for n in observe_canvas_detailed(screenshot_path, region=region)["nodes"]]
    for i, node in enumerate(nodes, start=1):
        node["id"] = f"Observed_Node_{i}"
    return nodes


def observe_canvas_detailed(
    screenshot_path: str,
    region: Tuple[int, int, int, int] | None = None,
) -> Dict[str, Any]:
    """Return raw canvas detections plus debug metadata."""
    img = cv2.imread(screenshot_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {screenshot_path}")

    scale = config.screen_scale()
    x1, y1, x2, y2 = _clamped_region(img, region)
    crop = img[y1:y2, x1:x2]
    detail: Dict[str, Any] = {
        "nodes": [],
        "accepted_candidates": [],
        "rejected_candidates": [],
        "crop_region": [x1, y1, x2, y2],
        "theme": "unknown",
        "polarity": "unknown",
    }
    if crop.size == 0:
        return detail

    mask, mask_info = _stroke_mask(crop)
    detail.update(mask_info)
    contours = _shape_contours(mask)
    accepted = []
    rejected = []
    for contour in contours:
        bx, by, bw, bh = cv2.boundingRect(contour)
        candidate = _candidate_metrics(contour, mask, bx, by, bw, bh)
        reasons = _candidate_rejection_reasons(candidate, crop.shape)
        debug_candidate = _candidate_debug(candidate, x1, y1, scale, reasons)
        if reasons:
            rejected.append(debug_candidate)
            continue

        cx = x1 + bx + bw // 2
        cy = y1 + by + bh // 2
        confidence = min(0.98, max(
            0.35,
            0.55 * candidate["rectangularity"] + 0.45 * min(candidate["stroke_density"] * 6, 1),
        ))
        node = {
            "id": f"Raw_Node_{len(accepted) + 1}",
            "raw_detection_id": f"Raw_Node_{len(accepted) + 1}",
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
        }
        accepted.append(node)

    accepted.sort(key=lambda n: (n["y"], n["x"]))
    for i, node in enumerate(accepted, start=1):
        raw_id = f"Raw_Node_{i}"
        node["id"] = raw_id
        node["raw_detection_id"] = raw_id

    detail["nodes"] = accepted
    detail["accepted_candidates"] = [_node_debug(n) for n in accepted]
    detail["rejected_candidates"] = rejected
    return detail


def annotate_canvas(
    screenshot_path: str,
    nodes: List[Dict[str, Any]],
    output_path: str,
    *,
    detection: Dict[str, Any] | None = None,
) -> str:
    """Draw observed canvas nodes on a screenshot and save it."""
    img = cv2.imread(screenshot_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {screenshot_path}")

    scale = config.screen_scale()
    if detection:
        crop = detection.get("crop_region")
        if crop and len(crop) == 4:
            cv2.rectangle(img, (crop[0], crop[1]), (crop[2], crop[3]), (80, 180, 255), 2)
            label = f"canvas crop {detection.get('theme', '')}/{detection.get('polarity', '')}"
            cv2.putText(img, label, (crop[0], max(12, crop[1] - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (80, 180, 255), 1)

        for candidate in detection.get("rejected_candidates", []):
            p = candidate.get("_px")
            if not p:
                continue
            x1 = p["x"] - p["w"] // 2
            y1 = p["y"] - p["h"] // 2
            x2 = p["x"] + p["w"] // 2
            y2 = p["y"] + p["h"] // 2
            color = (90, 90, 90)
            if candidate.get("reasons"):
                color = (80, 80, 220)
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 1)
            reason = ",".join(candidate.get("reasons", [])[:2])
            if reason:
                cv2.putText(img, reason[:24], (x1, max(12, y1 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)

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
        motion_from = node.get("motion_from")
        if motion_from:
            start = (int(motion_from["x"] * scale), int(motion_from["y"] * scale))
            end = (int(node["x"] * scale), int(node["y"] * scale))
            cv2.arrowedLine(img, start, end, (0, 220, 255), 2, tipLength=0.2)

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
                "raw_detection_id": n.get("raw_detection_id"),
                "text": n.get("text", ""),
                "confidence": n.get("confidence"),
                "source": n.get("source"),
                "track_status": n.get("track_status"),
                "last_seen_step": n.get("last_seen_step"),
                "motion_from": n.get("motion_from"),
                "stroke_density": n.get("stroke_density"),
                "rectangularity": n.get("rectangularity"),
            }
            for n in nodes
        ],
        "tool_families": families,
    }


def tool_families(ui_elements: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Group repeated sidebar labels and merge configured family defaults."""
    grouped: Dict[str, List[str]] = {}
    for name in sorted(ui_elements):
        base = _family_name(name)
        grouped.setdefault(base, []).append(name)

    families: Dict[str, Dict[str, Any]] = {}
    for family, spec in config.tool_families().items():
        configured_candidates = [
            c for c in spec.get("candidates", [])
            if c in ui_elements or c in grouped.get(family, [])
        ]
        inferred = grouped.get(family, [])
        candidates = _dedupe(configured_candidates + inferred)
        if not candidates:
            continue
        default = spec.get("default")
        if default not in candidates:
            default = _default_family_candidate(family, candidates)
        families[family] = {"default": default, "candidates": candidates}

    for family, candidates in grouped.items():
        if family in families:
            continue
        if len(candidates) > 1:
            families[family] = {
                "default": _default_family_candidate(family, candidates),
                "candidates": candidates,
            }
    return families


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


def _stroke_mask(crop: np.ndarray) -> Tuple[np.ndarray, Dict[str, str]]:
    """Keep shape strokes while suppressing draw.io grid lines.

    Draw.io can run in light or dark mode. Light mode shapes are usually dark
    strokes on a bright grid; dark mode shapes are usually bright strokes on a
    dark grid. Pick the threshold polarity from the crop brightness instead of
    assuming one theme.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    kernel = np.ones((3, 3), np.uint8)

    median = float(np.median(gray))
    if median < 110:
        _, mask = cv2.threshold(blurred, 120, 255, cv2.THRESH_BINARY)
        info = {"theme": "dark", "polarity": "bright_strokes"}
    else:
        _, mask = cv2.threshold(blurred, 220, 255, cv2.THRESH_BINARY_INV)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        info = {"theme": "light", "polarity": "dark_strokes"}

    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    return mask, info


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


def _candidate_rejection_reasons(
    candidate: Dict[str, float],
    crop_shape: Tuple[int, ...],
) -> List[str]:
    crop_h, crop_w = crop_shape[:2]
    width = candidate["width"]
    height = candidate["height"]
    x = candidate["x"]
    y = candidate["y"]
    area = width * height
    crop_area = max(crop_w * crop_h, 1)
    aspect = width / height if height else 0
    touches_border = x <= 2 or y <= 2 or x + width >= crop_w - 2 or y + height >= crop_h - 2

    reasons = []
    if touches_border:
        reasons.append("touches_border")
    if width < 50 or height < 32:
        reasons.append("too_small")
    if area < 1800 or area > crop_area * 0.12:
        reasons.append("bad_area")
    if not 0.35 <= aspect <= 5.0:
        reasons.append("bad_aspect")
    if candidate["stroke_density"] < 0.012 or candidate["stroke_density"] > 0.55:
        reasons.append("bad_density")
    if candidate["rectangularity"] < 0.18:
        reasons.append("low_rectangularity")
    return reasons


def _is_node_candidate(candidate: Dict[str, float], crop_shape: Tuple[int, ...]) -> bool:
    return not _candidate_rejection_reasons(candidate, crop_shape)


def _candidate_debug(
    candidate: Dict[str, float],
    region_x: int,
    region_y: int,
    scale: int,
    reasons: List[str],
) -> Dict[str, Any]:
    bx = int(candidate["x"])
    by = int(candidate["y"])
    bw = int(candidate["width"])
    bh = int(candidate["height"])
    cx = region_x + bx + bw // 2
    cy = region_y + by + bh // 2
    return {
        "x": cx // scale,
        "y": cy // scale,
        "w": bw // scale,
        "h": bh // scale,
        "area": round(float(candidate["area"]), 1),
        "stroke_density": round(float(candidate["stroke_density"]), 4),
        "rectangularity": round(float(candidate["rectangularity"]), 4),
        "reasons": reasons,
        "_px": {"x": cx, "y": cy, "w": bw, "h": bh},
    }


def _node_debug(node: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": node.get("id"),
        "x": node.get("x"),
        "y": node.get("y"),
        "w": node.get("w"),
        "h": node.get("h"),
        "confidence": node.get("confidence"),
        "stroke_density": node.get("stroke_density"),
        "rectangularity": node.get("rectangularity"),
        "_px": node.get("_px"),
    }


def _family_name(name: str) -> str:
    base = name
    if base.endswith("_Tool"):
        base = base[:-5]
    parts = base.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        base = parts[0]
    return f"{base}_Family"


def _default_family_candidate(family: str, candidates: List[str]) -> str | None:
    if not candidates:
        return None
    if family.endswith("_Family"):
        unsuffixed = f"{family[:-7]}_Tool"
        if unsuffixed in candidates:
            return unsuffixed
    return candidates[0]


def _dedupe(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
