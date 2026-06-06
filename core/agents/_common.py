"""
Shared agent helpers — coordinate-free state rendering + response parsing.

Both the :mod:`core.agents.executor` (one tool per turn) and the
:mod:`core.agents.planner` (whole plan in one call) build their prompts from the
same coordinate-free views of the UI/scene state, and both parse a JSON value
out of the model's free-text reply. Those pieces live here so the two agents
share one implementation instead of importing each other's privates.

Nothing here knows about *which* agent is calling it — it only renders the
``ui_graph`` (sidebar elements, canvas nodes/edges, active selection) and
extracts JSON.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List


# ===========================================================================
# Coordinate-free state rendering (shared prompt blocks)
# ===========================================================================

def element_summary(ui_graph: Dict[str, Any]) -> str:
    """
    Coordinate-free summary of detected elements.
    Shows names only — no (x, y) values.
    """
    parts = []

    tools = list(ui_graph.get("UI_Elements", {}).keys())
    if tools:
        parts.append("### Sidebar Shapes (use with `place_shape`)")
        for t in tools:
            parts.append(f"- `{t}`")

    nodes = ui_graph.get("Canvas_Nodes", [])
    if nodes:
        parts.append("\n### Canvas Nodes")
        for n in nodes:
            parts.append(f"- id=`{n['id']}`, text=`{n.get('text', '')}`")

    edges = ui_graph.get("Canvas_Edges", [])
    if edges:
        parts.append("\n### Canvas Edges")
        for e in edges:
            parts.append(f"- `{e['source']}` → `{e['target']}`")

    return "\n".join(parts)


# Maps a detected resize-handle slot back to the compass direction the model
# names (the inverse of the execution-side table in domains/drawio).
DIR_FOR_RESIZE_SLOT = {
    "tm": "n", "bm": "s", "mr": "e", "ml": "w",
    "tl": "nw", "tr": "ne", "bl": "sw", "br": "se",
}


def invert_resize_slots(resize: Dict[str, Any]) -> List[str]:
    return [DIR_FOR_RESIZE_SLOT[k] for k in resize if k in DIR_FOR_RESIZE_SLOT]


def active_selection_summary(ui_graph: Dict[str, Any]) -> str:
    """
    Describe the currently-selected shape and the semantic operations
    available on it. Coordinate-free — the model picks operations by name
    and direction, never by handle position.
    """
    h = ui_graph.get("selected_handles")
    if not h:
        return (
            "### Active Selection\n"
            "_No shape currently selected._ Use `click_node` to select a "
            "canvas node, or `scan_handles` to refresh after a placement."
        )

    bbox = h.get("shape_bbox") or [None] * 4
    resize_dirs = sorted(invert_resize_slots(h.get("resize", {})))
    extend_dirs = sorted(h.get("extend", {}).keys())
    can_rotate = bool(h.get("rotate"))

    size_line = (
        f"  - size: {bbox[2]}×{bbox[3]} logical px"
        if bbox[2] is not None else "  - size: unknown"
    )
    lines = [
        "### Active Selection",
        "A shape is selected. You can manipulate it with these semantic",
        "operations — pass only the direction/amount, the framework handles",
        "the click/drag coordinates:",
        "",
        size_line,
        f"  - `resize_shape(direction, amount)` — directions available: "
        f"{', '.join(resize_dirs) if resize_dirs else '(none detected)'}",
        f"  - `extend_shape(direction)` — directions available: "
        f"{', '.join(extend_dirs) if extend_dirs else '(none detected — try scan_handles)'}",
    ]
    if can_rotate:
        lines.append("  - `rotate_shape(angle_degrees)` — rotate around shape center")
    else:
        lines.append("  - rotate_shape: NOT available (no rotate handle detected)")
    lines.append("")
    lines.append(
        "`amount` is in logical pixels; reasonable values are a fraction of "
        "the shape's current size. `scan_handles` re-scans after any action "
        "that may have changed the shape's geometry."
    )
    return "\n".join(lines)


# ===========================================================================
# Response parsing
# ===========================================================================

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(raw: str) -> Any:
    """Pull a JSON value (object or array) out of the model's raw text reply.

    Tries, in order: the whole string, a fenced ```json block, then the first
    balanced ``{...}`` / ``[...]`` span (whichever appears first). Raises
    ``ValueError`` if none parse.
    """
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK_RE.search(text)
    if match:
        return json.loads(match.group(1))

    # First {...} or [...] — whichever starts earliest.
    candidates = [(text.find("{"), text.rfind("}")), (text.find("["), text.rfind("]"))]
    candidates = [(s, e) for s, e in candidates if s != -1 and e > s]
    if candidates:
        s, e = min(candidates, key=lambda c: c[0])
        return json.loads(text[s:e + 1])

    raise ValueError(f"Could not parse JSON from model response:\n{raw}")
