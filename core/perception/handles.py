"""
Handles — CV detection of drawio selection chrome.

When a shape is selected (and hovered) in drawio, three classes of
interactive handles appear around it:

  1. **Resize handles**  — 8 bright cyan filled circles (corners + edge
     midpoints). Named tl, tm, tr, ml, mr, bl, bm, br.
  2. **Extend arrows**   — 4 N/S/E/W arrows just outside the shape.
     Clicking auto-creates a connected shape in that direction.
  3. **Rotate handle**   — small curved-arrow icon just above the
     top-right corner.

The Executor never sees these coords — it picks semantic operations
(resize, extend, rotate) and the operand functions translate that into
the right drag/click using the detected handles.

Color signatures (HSV, observed on drawio's dark theme — see
`tests/handles_diagnostic.py` for samples):

  - Resize dots: H≈102, S≥120, V≥180  (bright cyan)
  - Rotate icon: H≈102, S≈158, V≈237  (bright cyan, smaller blob)
  - Extend arrows: H≈102, S 80-160, V 40-120  (dark cyan — semi-
    transparent overlay on the canvas in dark mode)

The hue is stable across light and dark themes; the value/saturation
shift, so the dark-arrow range is a bit wider than strictly needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from core import config


# ---------------------------------------------------------------------------
# HSV ranges — physical-pixel screenshot.
# ---------------------------------------------------------------------------

# Bright cyan: resize dots + rotate icon. V≥180.
BRIGHT_HSV_LO = np.array([90, 120, 180], dtype=np.uint8)
BRIGHT_HSV_HI = np.array([115, 255, 255], dtype=np.uint8)

# Dark cyan: extend arrows. Same hue, much lower V.
DARK_HSV_LO = np.array([95, 70, 35], dtype=np.uint8)
DARK_HSV_HI = np.array([110, 200, 150], dtype=np.uint8)

# Resize-dot area window (physical px²). Observed handle area: ~215.
# Tight band cleanly separates from the smaller rotate icon (~117) and
# from sidebar/status-bar chrome blobs at various sizes.
RESIZE_AREA_MIN = 180
RESIZE_AREA_MAX = 260

# Rotate-icon area window — smaller than resize dots, often an arc.
# After morph closing the curved-arrow area inflates a bit; observed ~176.
ROTATE_AREA_MIN = 80
ROTATE_AREA_MAX = 200

# How tightly the 8 resize dots should cluster — pairwise distance from
# the cluster anchor (physical px). For a 120-px-tall shape the full
# 8-dot bbox is <300px in each dimension; 500px gives slack for big shapes
# while still rejecting chrome blobs elsewhere on screen.
RESIZE_CLUSTER_MAX_SPAN = 500

# Extend arrows: minimum blob area, max distance from a shape edge midpoint.
EXTEND_AREA_MIN = 80
EXTEND_AREA_MAX = 1500
EXTEND_MAX_OFFSET_PX = 180


RESIZE_SLOTS = ("tl", "tm", "tr", "ml", "mr", "bl", "bm", "br")
EXTEND_SLOTS = ("n", "s", "e", "w")


@dataclass
class SelectionHandles:
    """Detected handles for the currently-selected drawio shape.

    All coordinates are LOGICAL pixels (already divided by screen_scale).
    """
    resize: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    extend: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    rotate: Optional[Tuple[int, int]] = None
    shape_bbox: Optional[Tuple[int, int, int, int]] = None  # x, y, w, h

    def is_valid(self) -> bool:
        return all(k in self.resize for k in ("tl", "tr", "bl", "br"))

    def to_dict(self) -> dict:
        return {
            "resize": {k: list(v) for k, v in self.resize.items()},
            "extend": {k: list(v) for k, v in self.extend.items()},
            "rotate": list(self.rotate) if self.rotate else None,
            "shape_bbox": list(self.shape_bbox) if self.shape_bbox else None,
        }


# ===========================================================================
# Helpers
# ===========================================================================

def _bright_contours(img_bgr: np.ndarray) -> List[Tuple[int, int, float, float]]:
    """Return [(cx, cy, area, radius)] for all bright-cyan blobs."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, BRIGHT_HSV_LO, BRIGHT_HSV_HI)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    out = []
    for c in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        area = cv2.contourArea(c)
        if area < 30:
            continue
        (cx, cy), r = cv2.minEnclosingCircle(c)
        out.append((int(cx), int(cy), float(area), float(r)))
    return out


def _largest_cluster(
    centers: List[Tuple[int, int]], max_span_px: int = RESIZE_CLUSTER_MAX_SPAN,
) -> List[Tuple[int, int]]:
    """Reject outliers — keep the largest group of centers whose pairwise
    bounding-box span fits inside ``max_span_px``.

    drawio's 8 resize handles are within a few hundred px of each other; UI
    chrome blobs elsewhere on screen are far outliers.
    """
    if len(centers) <= 1:
        return centers
    # Simple greedy: for each center, count neighbours within span; keep the
    # group with the most members, then prune anything outside the resulting
    # bbox.
    best: List[Tuple[int, int]] = []
    for i, anchor in enumerate(centers):
        group = [
            p for p in centers
            if abs(p[0] - anchor[0]) <= max_span_px
            and abs(p[1] - anchor[1]) <= max_span_px
        ]
        if len(group) > len(best):
            best = group
    if not best:
        return centers
    xs = [p[0] for p in best]; ys = [p[1] for p in best]
    bx, by, bw, bh = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
    # Tighten: only keep centers within the smallest enclosing bbox of `best`
    return [p for p in best
            if bx <= p[0] <= bx + bw and by <= p[1] <= by + bh]


def _classify_resize(
    centers: List[Tuple[int, int]],
) -> Dict[str, Tuple[int, int]]:
    """Group 8 centers into the 3×3-minus-center grid."""
    if len(centers) < 4:
        return {}
    ys = np.array([y for _, y in centers])
    y_min, y_max = int(ys.min()), int(ys.max())
    span = max(1, y_max - y_min)
    t1 = y_min + span / 3
    t2 = y_min + 2 * span / 3

    rows: Dict[str, List[Tuple[int, int]]] = {"t": [], "m": [], "b": []}
    for x, y in centers:
        if y < t1:
            rows["t"].append((x, y))
        elif y < t2:
            rows["m"].append((x, y))
        else:
            rows["b"].append((x, y))

    out: Dict[str, Tuple[int, int]] = {}
    for row_label, pts in (("t", rows["t"]), ("b", rows["b"])):
        if not pts:
            continue
        pts = sorted(pts, key=lambda p: p[0])
        if len(pts) >= 3:
            cols = ("l", "m", "r")
        elif len(pts) == 2:
            cols = ("l", "r")
        else:
            cols = ("m",)
        for col, pt in zip(cols, pts):
            out[f"{row_label}{col}"] = pt
    if rows["m"]:
        pts = sorted(rows["m"], key=lambda p: p[0])
        if len(pts) >= 2:
            out["ml"], out["mr"] = pts[0], pts[-1]
        elif len(pts) == 1:
            x_med = np.median([p[0] for p in centers])
            out["ml" if pts[0][0] < x_med else "mr"] = pts[0]
    return out


def _find_extend_arrows(
    img_bgr: np.ndarray, shape_bbox_phys: Tuple[int, int, int, int],
) -> Dict[str, Tuple[int, int]]:
    """Detect the 4 N/S/E/W extend arrows in the dark-cyan range, classifying
    by direction relative to the shape's edge midpoints."""
    bx, by, bw, bh = shape_bbox_phys
    cx_shape = bx + bw // 2
    cy_shape = by + bh // 2

    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, DARK_HSV_LO, DARK_HSV_HI)
    # Remove anything inside the shape bbox + small padding (kills dashed
    # selection border and the shape interior).
    pad = 6
    cv2.rectangle(
        mask, (bx - pad, by - pad), (bx + bw + pad, by + bh + pad), 0, -1,
    )
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Edge midpoints (physical px).
    midpoints = {
        "n": (cx_shape, by),
        "s": (cx_shape, by + bh),
        "w": (bx, cy_shape),
        "e": (bx + bw, cy_shape),
    }
    extend: Dict[str, Tuple[int, int]] = {}
    best_dist: Dict[str, float] = {}

    for c in contours:
        area = cv2.contourArea(c)
        if not (EXTEND_AREA_MIN <= area <= EXTEND_AREA_MAX):
            continue
        M = cv2.moments(c)
        if M["m00"] == 0:
            continue
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])

        # Decide direction by which edge midpoint we're closest to.
        for direction, (mx, my) in midpoints.items():
            dx = cx - mx
            dy = cy - my
            # Must lie in the half-plane outside that edge.
            outside = (
                (direction == "n" and dy < 0)
                or (direction == "s" and dy > 0)
                or (direction == "w" and dx < 0)
                or (direction == "e" and dx > 0)
            )
            if not outside:
                continue
            dist = (dx * dx + dy * dy) ** 0.5
            if dist > EXTEND_MAX_OFFSET_PX:
                continue
            if direction not in extend or dist < best_dist[direction]:
                extend[direction] = (cx, cy)
                best_dist[direction] = dist
    return extend


def _pick_rotate(
    contours: List[Tuple[int, int, float, float]],
    shape_bbox_phys: Tuple[int, int, int, int],
    used_centers: List[Tuple[int, int]],
) -> Optional[Tuple[int, int]]:
    """The rotate icon is the bright-cyan blob just above & right of the
    top-right resize handle, with area smaller than the resize dots."""
    bx, by, bw, bh = shape_bbox_phys
    tr_x, tr_y = bx + bw, by
    best: Optional[Tuple[int, int]] = None
    best_dist = float("inf")
    for cx, cy, area, _r in contours:
        if (cx, cy) in used_centers:
            continue
        if not (ROTATE_AREA_MIN <= area <= ROTATE_AREA_MAX):
            continue
        # Must sit above-right of the top-right corner.
        if cx < tr_x - 10 or cy > tr_y + 10:
            continue
        d = ((cx - tr_x) ** 2 + (cy - tr_y) ** 2) ** 0.5
        if d < best_dist and d < 120:
            best = (cx, cy)
            best_dist = d
    return best


# ===========================================================================
# Public entry point
# ===========================================================================

def detect_handles(screenshot_path: str) -> SelectionHandles:
    img = cv2.imread(screenshot_path)
    if img is None:
        raise FileNotFoundError(screenshot_path)
    scale = config.screen_scale()

    bright = _bright_contours(img)

    # 1) Resize handles: area in dot-window, then cluster-prune outliers.
    resize_candidates = [
        (cx, cy) for cx, cy, area, _r in bright
        if RESIZE_AREA_MIN <= area <= RESIZE_AREA_MAX
    ]
    resize_clean = _largest_cluster(resize_candidates)
    resize_phys = _classify_resize(resize_clean)
    if not resize_phys:
        return SelectionHandles()

    # 2) Infer shape bbox from corners.
    xs = [p[0] for p in resize_phys.values()]
    ys = [p[1] for p in resize_phys.values()]
    bbox_phys = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    # 3) Rotation icon — bright but smaller, positioned above top-right.
    rotate_phys = _pick_rotate(bright, bbox_phys, list(resize_phys.values()))

    # 4) Extend arrows (dark cyan, outside shape edges).
    extend_phys = _find_extend_arrows(img, bbox_phys)

    def _logical(p: Tuple[int, int]) -> Tuple[int, int]:
        return (p[0] // scale, p[1] // scale)

    return SelectionHandles(
        resize={k: _logical(v) for k, v in resize_phys.items()},
        extend={k: _logical(v) for k, v in extend_phys.items()},
        rotate=_logical(rotate_phys) if rotate_phys else None,
        shape_bbox=(
            bbox_phys[0] // scale, bbox_phys[1] // scale,
            bbox_phys[2] // scale, bbox_phys[3] // scale,
        ),
    )


# ===========================================================================
# CLI for quick manual testing
# ===========================================================================

if __name__ == "__main__":
    import argparse, json
    p = argparse.ArgumentParser(description="Detect drawio selection handles.")
    p.add_argument("image", help="Path to a screenshot containing a selection.")
    args = p.parse_args()
    h = detect_handles(args.image)
    print(json.dumps(h.to_dict(), indent=2))
