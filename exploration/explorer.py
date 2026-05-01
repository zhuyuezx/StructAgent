"""
Explorer — UI exploration and auto-calibration.

Detects clickable sidebar icons in draw.io screenshots using OpenCV,
optionally labels them with the VLM, and writes results to icons.json.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np

from shared import config


# ---------------------------------------------------------------------------
# Icon detection (OpenCV)
# ---------------------------------------------------------------------------

def detect_icons(
    screenshot_path: str,
    region: Tuple[int, int, int, int] | None = None,
) -> List[Dict[str, Any]]:
    """
    Detect icon-sized rectangular regions in the sidebar.

    Works on the raw screenshot (physical pixels) and returns coordinates
    in LOGICAL pixels (divided by screen_scale).
    """
    scale = config.screen_scale()
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
                    "x": cx // scale, "y": cy // scale,
                    "w": bw // scale, "h": bh // scale,
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
) -> str:
    """Draw bounding boxes on the screenshot and save. Returns output path."""
    img = cv2.imread(screenshot_path)
    scale = config.screen_scale()

    for i, icon in enumerate(icons):
        p = icon.get("_px", {
            "x": icon["x"] * scale, "y": icon["y"] * scale,
            "w": icon["w"] * scale, "h": icon["h"] * scale,
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
    print(f"[EXPLORER] Annotated → {os.path.abspath(output_path)}")
    return output_path


# ---------------------------------------------------------------------------
# LLM labeling
# ---------------------------------------------------------------------------

def label_icons(
    screenshot_path: str,
    icons: List[Dict[str, Any]],
    timeout: float | None = None,
    max_retries: int | None = None,
) -> List[Dict[str, Any]]:
    """
    Send each cropped icon to the VLM to identify its shape type.

    Uses ``ollama.Client`` with a real HTTP timeout so hung requests
    are actually cancelled.
    """
    import httpx
    import ollama

    img = cv2.imread(screenshot_path)
    model = config.explorer_model()
    scale = config.screen_scale()
    timeout = timeout or config.label_timeout()
    max_retries = max_retries or config.label_max_retries()

    client = ollama.Client(timeout=httpx.Timeout(timeout, connect=10.0))

    labeled = []
    total = len(icons)
    skipped = 0

    print(f"  Model: {model}  |  Timeout: {timeout}s  |  Max retries: {max_retries}")

    for i, icon in enumerate(icons):
        p = icon.get("_px", {
            "x": icon["x"] * scale, "y": icon["y"] * scale,
            "w": icon["w"] * scale, "h": icon["h"] * scale,
        })
        pad = 5
        ry1 = max(0, p["y"] - p["h"] // 2 - pad)
        ry2 = min(img.shape[0], p["y"] + p["h"] // 2 + pad)
        rx1 = max(0, p["x"] - p["w"] // 2 - pad)
        rx2 = min(img.shape[1], p["x"] + p["w"] // 2 + pad)
        crop = img[ry1:ry2, rx1:rx2]

        _, buf = cv2.imencode(".png", crop)
        img_bytes = buf.tobytes()

        messages = [{
            "role": "user",
            "content": (
                "This is a small icon from draw.io's shape sidebar. "
                "What shape does it represent? Reply with ONLY a short "
                "label like Rectangle, Ellipse, Rounded_Rectangle, Diamond, "
                "Triangle, Arrow, Text, Cylinder, Cloud, etc. "
                "One or two words, use underscores."
            ),
            "images": [img_bytes],
        }]

        label = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = client.chat(model=model, messages=messages)
                raw = resp["message"]["content"].strip().split("\n")[0]
                label = raw.strip(".,!\"'` ").replace(" ", "_")
                break
            except httpx.TimeoutException:
                print(f"  Icon {i:>2}: ⏱ timeout ({timeout}s) — "
                      f"retry {attempt}/{max_retries}")
            except Exception as e:
                err = str(e)[:60]
                print(f"  Icon {i:>2}: ❌ {err} — retry {attempt}/{max_retries}")

        if label is None:
            label = "unknown"
            skipped += 1
            print(f"  Icon {i:>2}: ({icon['x']:>3}, {icon['y']:>3}) → "
                  f"⚠️ SKIPPED (max retries exceeded)")
        else:
            print(f"  Icon {i:>2}: ({icon['x']:>3}, {icon['y']:>3}) → {label}")

        labeled.append({**icon, "label": label})

    if skipped:
        print(f"\n  ⚠️  {skipped}/{total} icons skipped (labeled 'unknown')")

    return labeled


# ---------------------------------------------------------------------------
# Write to icons.json
# ---------------------------------------------------------------------------

def write_icons(icons: List[Dict[str, Any]]) -> str:
    """
    Write detected icons to exploration/icons.json.
    Returns the output file path.
    """
    out_path = config.icons_path()

    ui_elements = {}
    seen: Dict[str, int] = {}
    for icon in icons:
        base = icon.get("label", f"icon_{icon['x']}_{icon['y']}")
        if not base.endswith("_Tool"):
            base = f"{base}_Tool"
        if base in seen:
            seen[base] += 1
            name = f"{base}_{seen[base]}"
        else:
            seen[base] = 0
            name = base
        ui_elements[name] = {
            "x": icon["x"], "y": icon["y"],
            "w": icon["w"], "h": icon["h"],
        }

    with open(out_path, "w") as f:
        json.dump({"ui_elements": ui_elements}, f, indent=2)

    print(f"[EXPLORER] Wrote {len(ui_elements)} elements → {out_path}")
    return out_path
