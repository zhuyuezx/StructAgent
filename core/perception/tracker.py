"""
In-run canvas tracking for stable observed node ids.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple


class CanvasTracker:
    """Assign stable IDs to raw canvas detections within one pipeline run."""

    def __init__(self) -> None:
        self._tracks: Dict[str, Dict[str, Any]] = {}
        self._next_id = 1
        self.last_diagnostics: Dict[str, Any] = {
            "matches": [],
            "new_tracks": [],
            "deleted_tracks": [],
        }

    def update(self, raw_nodes: List[Dict[str, Any]], step: int) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        new_tracks: List[str] = []
        matched_tracks: set[str] = set()
        matched_raw: set[int] = set()
        tracked_nodes: List[Dict[str, Any]] = []

        pairs = []
        for raw_idx, raw in enumerate(raw_nodes):
            for track_id, prev in self._tracks.items():
                score = _match_score(prev, raw)
                if score < 0.45:
                    continue
                pairs.append((score, track_id, raw_idx))
        pairs.sort(reverse=True, key=lambda p: p[0])

        for score, track_id, raw_idx in pairs:
            if track_id in matched_tracks or raw_idx in matched_raw:
                continue
            prev = self._tracks[track_id]
            node = _tracked_node(raw_nodes[raw_idx], track_id, "matched", step, prev)
            self._tracks[track_id] = node
            tracked_nodes.append(node)
            matched_tracks.add(track_id)
            matched_raw.add(raw_idx)
            matches.append({
                "track_id": track_id,
                "raw_detection_id": raw_nodes[raw_idx].get("raw_detection_id"),
                "score": round(float(score), 3),
                "from": _pos(prev),
                "to": _pos(node),
            })

        for raw_idx, raw in enumerate(raw_nodes):
            if raw_idx in matched_raw:
                continue
            track_id = f"Observed_Node_{self._next_id}"
            self._next_id += 1
            node = _tracked_node(raw, track_id, "new", step, None)
            self._tracks[track_id] = node
            tracked_nodes.append(node)
            new_tracks.append(track_id)

        deleted = [
            {"track_id": tid, "last_position": _pos(prev)}
            for tid, prev in self._tracks.items()
            if tid not in matched_tracks and tid not in new_tracks
        ]
        self._tracks = {node["id"]: node for node in tracked_nodes}

        tracked_nodes.sort(key=lambda n: (n["y"], n["x"]))
        self.last_diagnostics = {
            "matches": matches,
            "new_tracks": new_tracks,
            "deleted_tracks": deleted,
        }
        return tracked_nodes


def _tracked_node(
    raw: Dict[str, Any],
    track_id: str,
    status: str,
    step: int,
    previous: Dict[str, Any] | None,
) -> Dict[str, Any]:
    node = dict(raw)
    node["id"] = track_id
    node["raw_detection_id"] = raw.get("raw_detection_id")
    node["track_status"] = status
    node["last_seen_step"] = step
    if previous:
        node["motion_from"] = _pos(previous)
    return node


def _match_score(prev: Dict[str, Any], raw: Dict[str, Any]) -> float:
    max_dim = max(prev.get("w", 1), prev.get("h", 1), raw.get("w", 1), raw.get("h", 1), 1)
    distance = math.hypot(prev["x"] - raw["x"], prev["y"] - raw["y"])
    distance_score = max(0.0, 1.0 - distance / (max_dim * 3.0))
    size_score = _size_similarity(prev, raw)
    iou = _bbox_iou(prev, raw)
    return 0.45 * distance_score + 0.35 * size_score + 0.20 * iou


def _size_similarity(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    aw, ah = max(a.get("w", 1), 1), max(a.get("h", 1), 1)
    bw, bh = max(b.get("w", 1), 1), max(b.get("h", 1), 1)
    width_ratio = min(aw, bw) / max(aw, bw)
    height_ratio = min(ah, bh) / max(ah, bh)
    return (width_ratio + height_ratio) / 2


def _bbox_iou(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    ax1, ay1, ax2, ay2 = _bounds(a)
    bx1, by1, bx2, by2 = _bounds(b)
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    intersection = iw * ih
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _bounds(node: Dict[str, Any]) -> Tuple[float, float, float, float]:
    half_w = node.get("w", 0) / 2
    half_h = node.get("h", 0) / 2
    return (
        node.get("x", 0) - half_w,
        node.get("y", 0) - half_h,
        node.get("x", 0) + half_w,
        node.get("y", 0) + half_h,
    )


def _pos(node: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "x": node.get("x"),
        "y": node.get("y"),
        "w": node.get("w"),
        "h": node.get("h"),
    }
