"""
Executor agent — picks the next tool given a task and current UI graph.

Constructs a coordinate-free prompt from the tool catalog and detected
element names, sends it to a local LLM via Ollama, and parses the JSON
response. The executor never sees pixel coordinates — it only picks
named tools and references elements by name/id.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

import ollama

from core import config
from core.state import scene_graph as _sg
from core.tools import TOOL_CATALOG

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt construction — coordinate-free
# ---------------------------------------------------------------------------

def _tool_table() -> str:
    """Render the tool catalog as a markdown table for the prompt."""
    lines = []
    for name, node in TOOL_CATALOG.items():
        params = ", ".join(node.params) if node.params else "(none)"
        lines.append(f"| {name} | L{node.level} | {params} | {node.description} |")
    header = "| tool | level | params | description |\n|------|-------|--------|-------------|"
    return header + "\n" + "\n".join(lines)


def _element_summary(ui_graph: Dict[str, Any]) -> str:
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


def _active_selection_summary(ui_graph: Dict[str, Any]) -> str:
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
    resize_dirs = sorted(_invert_resize_slots(h.get("resize", {})))
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


_DIR_FOR_RESIZE_SLOT = {
    "tm": "n", "bm": "s", "mr": "e", "ml": "w",
    "tl": "nw", "tr": "ne", "bl": "sw", "br": "se",
}


def _invert_resize_slots(resize: Dict[str, Any]) -> List[str]:
    return [_DIR_FOR_RESIZE_SLOT[k] for k in resize if k in _DIR_FOR_RESIZE_SLOT]


_SYSTEM_TEMPLATE = """\
You are the **Executor** agent for draw.io. You pick exactly one tool
per turn. You do NOT specify coordinates — the framework owns those.

# DECISION PROCEDURE — run these 4 steps before every response

1. **Read CURRENT STATE below.** What objects exist? Which is selected?
   Which edges exist? What's the last_op?
2. **Compare to the task.** What is still missing or wrong?
3. **Pick the single tool** that closes the smallest gap toward the goal.
   Skim TOOLS BY GOAL if unsure which one applies.
4. **If you're about to repeat your last tool, or the SCENE GRAPH did
   not change as expected**, STOP and call `click_empty_canvas` first.
   That clears the selection and the active selection block, giving you
   a clean slate to re-read CURRENT STATE and pick differently.

# CURRENT STATE — always check this FIRST

## SCENE GRAPH (canvas objects + edges, deterministic — updated by framework)
{scene_graph_summary}

{active_selection}

# drawio QUIRKS — what to expect from the application

These behaviours are baked into drawio. The framework already handles
the mechanics; you only need to plan around them.

- **`place_shape` always drops at the same default canvas position.** A
  second `place_shape` without moving the first will land ON TOP, and
  the SCENE GRAPH will show two overlapping bboxes. Move the previous
  shape (or use `extend_shape`) before placing again.
- **`place_shape` automatically enters text-edit mode** on the new shape.
  Follow with `type_label` then `press_escape`. Don't `double_click_node`.
- **Selection is single-shape**: clicking a different shape switches
  selection; clicking empty canvas deselects everything. The SCENE GRAPH
  shows the current selection with `*SELECTED*`.
- **Extend arrows and resize handles only appear on the selected shape**
  (and require a hover for the arrows). The framework re-detects them
  automatically after operations that change geometry.
- **`connect_shapes` handles selection itself.** You do not need to
  click_node / hover_object the source first; just call it with the two
  scene-graph ids.

# TOOLS BY GOAL — scan this when planning

- Add a free-standing shape →
    `place_shape(tool_name=…)` + `type_label(text=…)` + `press_escape`
- Add a new shape **connected to the current one** →
    `extend_shape(direction=n/s/e/w)`  *(creates new object + edge)*
- Connect TWO EXISTING shapes with an edge →
    `connect_shapes(source_id=…, target_id=…, source_anchor='auto')`
- Move the selected shape →
    `move_shape(direction=…, amount=…)`
- Resize the selected shape →
    `resize_shape(direction=…, amount=…)`
- Rotate the selected shape →
    `rotate_shape(angle_degrees=…)`
- Select a known canvas shape →
    `click_node(node_ref=obj_NNN)`
- Re-edit an existing shape's text →
    `double_click_node` → `select_all` → `type_label` → `press_escape`
- Add or edit the label on an existing edge →
    `label_edge(edge_id=edge_NNN, text=…)`
- Clear selection / reset focus (use this when stuck) →
    `click_empty_canvas`
- Refresh handle detection (if SCENE GRAPH selection shows `bbox=?`) →
    `scan_handles`
- Finish →
    `task_complete`

**Tool choice cheats** (apply these literally before doing anything else):

- Task says *connect / link / arrow between A and B*, both in SCENE GRAPH
  → emit `connect_shapes(A, B, 'auto')` immediately. Do not hover, do
  not click_node, do not extend_shape. Just connect_shapes.
- Need a second shape and the task does *not* mention an edge → first
  `move_shape` the current selection out of the default drop zone (e.g.
  east by ~180 px), THEN `place_shape`.
- About to call the same tool you just called → call `click_empty_canvas`
  instead and reassess from the SCENE GRAPH.

# AVAILABLE TOOLS (full catalog with params)
{tool_table}

**Special signals** (no params):
| tool | description |
|------|-------------|
| request_rescan | Re-perceive the sidebar / perception state |
| task_complete  | Signal that the task is finished |

# REFERENCE — sidebar shapes you can place
{element_summary}

# OUTPUT FORMAT
Respond with a single JSON object — no markdown, no commentary, no code
fences. Reasoning must explicitly cite SCENE GRAPH state.

```
{{
  "reasoning": "SCENE GRAPH shows <state>; task needs <gap>; therefore <tool>.",
  "tool": "<tool_name>",
  "params": {{}}
}}
```
"""


def build_prompt(ui_graph: Dict[str, Any]) -> str:
    """Build the system prompt for the LLM."""
    sg_data = ui_graph.get("scene_graph") or _sg.load()
    return _SYSTEM_TEMPLATE.format(
        tool_table=_tool_table(),
        element_summary=_element_summary(ui_graph),
        scene_graph_summary=_sg.summary_for_prompt(sg_data),
        active_selection=_active_selection_summary(ui_graph),
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_response(raw: str) -> Dict[str, Any]:
    """Extract a JSON dict from the LLM's raw text output."""
    text = raw.strip()

    # Try raw JSON first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fenced JSON block
    match = _JSON_BLOCK_RE.search(text)
    if match:
        return json.loads(match.group(1))

    # First { … last }
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])

    raise ValueError(f"Could not parse JSON from LLM response:\n{text}")


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def infer(
    task: str,
    ui_graph: Dict[str, Any],
    screenshot_path: str,
    history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Ask the LLM to choose the next tool.

    Args:
        task:            Natural-language task description.
        ui_graph:        Current UI graph (element names shown, no coords).
        screenshot_path: Path to screenshot (sent as image).
        history:         Prior conversation turns for multi-step reasoning.

    Returns:
        Dict with keys: ``reasoning``, ``tool``, ``params``.
    """
    model = config.llm_model()
    prompt = build_prompt(ui_graph)

    messages: List[Dict[str, Any]] = [{"role": "system", "content": prompt}]
    if history:
        messages.extend(history)

    with open(screenshot_path, "rb") as f:
        image_bytes = f.read()

    messages.append({
        "role": "user",
        "content": f"Task: {task}",
        "images": [image_bytes],
    })

    logger.info("Querying %s …", model)
    response = ollama.chat(model=model, messages=messages)
    raw = response["message"]["content"]
    logger.debug("Raw response:\n%s", raw)

    result = parse_response(raw)

    # Normalize: accept "action" key as alias for "tool"
    if "tool" not in result and "action" in result:
        result["tool"] = result.pop("action")
    if "tool" not in result:
        raise ValueError(f"Executor response missing 'tool' key: {result}")

    logger.info("Decided: %s  %s", result['tool'], result.get('params', {}))
    return result
