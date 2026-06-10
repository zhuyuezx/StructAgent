"""
Scene graph — deterministic numerical model of the canvas.

While ``ui_graph`` describes the *static* parts of the UI (sidebar tools,
section headers etc.), the **scene graph** describes the *dynamic* state
of the canvas — every shape the agent has placed, every edge connecting
them, and where each object currently lives in logical pixel space.

Two design rules:

  1. **Deterministic, not LLM-controlled.** The framework mutates the
     scene graph in response to operands. The LLM only reads it.
  2. **Synthetic-first, CV-verified.** When we know we just placed a
     shape, we record it from the operand call (synthetic). After
     geometry-changing operations we re-detect the selection handles to
     get a fresh bbox and reconcile it into the matching object.

Schema (``state/scene_graph.json``):

    {
      "version": 1,
      "next_object_id": 3,
      "next_edge_id": 1,
      "objects": [
        {
          "id": "obj_001",
          "type": "Rectangle",
          "label": "Cache",
          "bbox": [x, y, w, h],
          "anchors": {"n":[x,y],"s":[x,y],"e":[x,y],"w":[x,y]},
          "selected": true,
          "created_op": 1,
          "last_updated_op": 3
        }, ...
      ],
      "edges": [
        {
          "id": "edge_001",
          "source": "obj_001", "target": "obj_002",
          "source_anchor": "e", "target_anchor": "w",
          "label": ""
        }, ...
      ],
      "metadata": {
        "op_count": 4,
        "last_op": "extend_shape"
      }
    }
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from core import config


SCENE_GRAPH_VERSION = 1


# ===========================================================================
# Persistence
# ===========================================================================

def _scene_path() -> str:
    """Absolute path of the live scene graph, under the dedicated
    (gitignored) ``scene_graph/`` folder — see ``config.scene_graph_dir``."""
    return os.path.join(config.scene_graph_dir(), "scene_graph.json")


def scene_path() -> str:
    """Public accessor for the scene-graph file path (used by notebooks/UI)."""
    return _scene_path()


def empty_graph() -> Dict[str, Any]:
    return {
        "version": SCENE_GRAPH_VERSION,
        "next_object_id": 1,
        "next_edge_id": 1,
        "objects": [],
        "edges": [],
        "metadata": {"op_count": 0, "last_op": None},
    }


def load() -> Dict[str, Any]:
    """Read the scene graph from disk, returning an empty one if missing."""
    path = _scene_path()
    if not os.path.exists(path):
        return empty_graph()
    try:
        with open(path) as f:
            g = json.load(f)
        # Backfill missing fields for forward compat.
        if "version" not in g:
            g = empty_graph()
        return g
    except (json.JSONDecodeError, OSError):
        return empty_graph()


def save(graph: Dict[str, Any]) -> None:
    path = _scene_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(graph, f, indent=2)


def reset() -> Dict[str, Any]:
    """Wipe the scene graph (start from empty). Returns the new graph."""
    g = empty_graph()
    save(g)
    return g


# ===========================================================================
# Mutations
# ===========================================================================

def _anchors_from_bbox(bbox: List[int]) -> Dict[str, List[int]]:
    """Compute draw.io connection points from a bbox."""
    x, y, w, h = bbox
    return {
        "n": [x + w // 2, y],
        "s": [x + w // 2, y + h],
        "e": [x + w, y + h // 2],
        "w": [x, y + h // 2],
        "nw": [x, y],
        "ne": [x + w, y],
        "sw": [x, y + h],
        "se": [x + w, y + h],
    }


def _bump_op(graph: Dict[str, Any], op_name: str) -> int:
    graph["metadata"]["op_count"] += 1
    graph["metadata"]["last_op"] = op_name
    return graph["metadata"]["op_count"]


def add_object(
    graph: Dict[str, Any],
    *,
    type_: str,
    bbox: Optional[List[int]] = None,
    label: str = "",
    op_name: str = "",
) -> Dict[str, Any]:
    """Append a new object. Returns the object dict."""
    op_idx = _bump_op(graph, op_name or "add_object")
    oid = f"obj_{graph['next_object_id']:03d}"
    graph["next_object_id"] += 1
    obj = {
        "id": oid,
        "type": type_,
        "label": label,
        "bbox": list(bbox) if bbox else None,
        "anchors": _anchors_from_bbox(bbox) if bbox else None,
        "selected": False,
        "created_op": op_idx,
        "last_updated_op": op_idx,
    }
    graph["objects"].append(obj)
    return obj


def update_object_bbox(
    graph: Dict[str, Any], object_id: str, new_bbox: List[int],
    op_name: str = "",
) -> Optional[Dict[str, Any]]:
    op_idx = _bump_op(graph, op_name or "update_bbox")
    for o in graph["objects"]:
        if o["id"] == object_id:
            o["bbox"] = list(new_bbox)
            o["anchors"] = _anchors_from_bbox(new_bbox)
            o["last_updated_op"] = op_idx
            return o
    return None


def update_object_label(
    graph: Dict[str, Any], object_id: str, label: str,
    op_name: str = "",
) -> Optional[Dict[str, Any]]:
    op_idx = _bump_op(graph, op_name or "update_label")
    for o in graph["objects"]:
        if o["id"] == object_id:
            o["label"] = label
            o["last_updated_op"] = op_idx
            return o
    return None


def remove_object(
    graph: Dict[str, Any], object_id: str, op_name: str = "",
) -> bool:
    _bump_op(graph, op_name or "remove_object")
    before = len(graph["objects"])
    graph["objects"] = [o for o in graph["objects"] if o["id"] != object_id]
    # Drop any edges touching this object.
    graph["edges"] = [
        e for e in graph["edges"]
        if e["source"] != object_id and e["target"] != object_id
    ]
    return len(graph["objects"]) < before


def add_edge(
    graph: Dict[str, Any],
    *,
    source: str, target: str,
    source_anchor: str = "e", target_anchor: str = "w",
    label: str = "", op_name: str = "",
) -> Dict[str, Any]:
    _bump_op(graph, op_name or "add_edge")
    eid = f"edge_{graph['next_edge_id']:03d}"
    graph["next_edge_id"] += 1
    edge = {
        "id": eid,
        "source": source, "target": target,
        "source_anchor": source_anchor, "target_anchor": target_anchor,
        "label": label,
    }
    graph["edges"].append(edge)
    return edge


def set_selected(graph: Dict[str, Any], object_id: Optional[str]) -> None:
    """Mark ``object_id`` as selected (others cleared). Pass None to clear."""
    for o in graph["objects"]:
        o["selected"] = (o["id"] == object_id)


def get_selected(graph: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for o in graph["objects"]:
        if o.get("selected"):
            return o
    return None


# ===========================================================================
# Lookup helpers
# ===========================================================================

def find_by_id(graph: Dict[str, Any], object_id: str) -> Optional[Dict[str, Any]]:
    for o in graph["objects"]:
        if o["id"] == object_id:
            return o
    return None


def find_edge_by_id(graph: Dict[str, Any], edge_id: str) -> Optional[Dict[str, Any]]:
    for e in graph["edges"]:
        if e["id"] == edge_id:
            return e
    return None


def update_edge_label(
    graph: Dict[str, Any], edge_id: str, label: str,
    op_name: str = "",
) -> Optional[Dict[str, Any]]:
    _bump_op(graph, op_name or "update_edge_label")
    for e in graph["edges"]:
        if e["id"] == edge_id:
            e["label"] = label
            return e
    return None


def find_at_point(
    graph: Dict[str, Any], x: int, y: int,
    tolerance: int = 6,
) -> Optional[Dict[str, Any]]:
    """Return the object whose bbox contains (x, y), if any."""
    for o in graph["objects"]:
        b = o.get("bbox")
        if not b:
            continue
        bx, by, bw, bh = b
        if (bx - tolerance <= x <= bx + bw + tolerance
                and by - tolerance <= y <= by + bh + tolerance):
            return o
    return None


def find_closest_to_bbox(
    graph: Dict[str, Any], target_bbox: List[int],
    max_center_dist: int = 400,
) -> Optional[Dict[str, Any]]:
    """Find the object whose bbox center is closest to ``target_bbox``'s center.

    Used by the inter-operation scanner to reconcile a freshly-detected
    selection bbox back to the right scene-graph object.
    """
    tx, ty, tw, th = target_bbox
    tcx, tcy = tx + tw // 2, ty + th // 2
    best, best_d = None, float("inf")
    for o in graph["objects"]:
        b = o.get("bbox")
        if not b:
            continue
        ocx = b[0] + b[2] // 2
        ocy = b[1] + b[3] // 2
        d = ((ocx - tcx) ** 2 + (ocy - tcy) ** 2) ** 0.5
        if d < best_d:
            best, best_d = o, d
    return best if best_d <= max_center_dist else None


# ===========================================================================
# Prompt rendering — numerical summary for the LLM
# ===========================================================================

def summary_for_prompt(graph: Dict[str, Any]) -> str:
    """Render a compact numerical summary for inclusion in the Executor prompt.

    Includes object IDs, types, labels, bboxes, and edges — enough for the
    LLM to reason about the scene without seeing the screen.
    """
    if not graph["objects"]:
        return "_Canvas is empty._"

    lines = [f"**Objects ({len(graph['objects'])}):**"]
    for o in graph["objects"]:
        sel = "  *SELECTED*" if o.get("selected") else ""
        bbox = o.get("bbox") or [None] * 4
        bx, by, bw, bh = bbox
        if bx is None:
            geom = "bbox=?"
        else:
            geom = f"bbox=[{bx},{by},{bw}x{bh}]"
        label = f' "{o["label"]}"' if o.get("label") else ""
        lines.append(f"  - `{o['id']}` {o['type']}{label}  {geom}{sel}")

    if graph["edges"]:
        lines.append(f"\n**Edges ({len(graph['edges'])}):**")
        for e in graph["edges"]:
            lbl = f' "{e["label"]}"' if e.get("label") else ""
            lines.append(
                f"  - `{e['id']}` `{e['source']}`.{e['source_anchor']} → "
                f"`{e['target']}`.{e['target_anchor']}{lbl}"
            )

    meta = graph.get("metadata", {})
    if meta.get("last_op"):
        lines.append(
            f"\n_(scene_graph op #{meta.get('op_count', 0)}, "
            f"last op: {meta['last_op']})_"
        )
    return "\n".join(lines)


# ===========================================================================
# CLI helpers — for the notebook + debugging
# ===========================================================================

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Scene graph CLI.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="Print the current scene graph summary.")
    sub.add_parser("reset", help="Wipe state/scene_graph.json.")
    args = p.parse_args()
    if args.cmd == "show":
        print(summary_for_prompt(load()))
    elif args.cmd == "reset":
        reset()
        print("scene_graph.json reset.")
