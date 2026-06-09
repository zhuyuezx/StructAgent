"""
Executor agent — picks the next tool given a task and current UI graph.

Constructs a coordinate-free prompt from the tool catalog and detected
element names, sends it to a local LLM via Ollama, and parses the JSON
response. The executor never sees pixel coordinates — it only picks
named tools and references elements by name/id.

Two inference modes, selected per-call via ``infer(screenshot_path=…)``:

- **screenshot+SG** (default) — the LLM gets both the screenshot and the
  SCENE GRAPH block. The prompt tells it to treat the SCENE GRAPH as
  authoritative and the screenshot as a visual cross-check.
- **text-only** — pass ``screenshot_path=None``. The prompt tells the LLM
  the SCENE GRAPH is its only view of the canvas, and no image is attached
  to the user message. Useful for low-cost planning when the symbolic state
  is known to be complete; see ``notebooks/text_only_executor_test.ipynb``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core import config
from core import llm
from core.agents._common import (
    active_selection_summary,
    element_summary,
    extract_json,
)
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


# The coordinate-free state renderers (element_summary, active_selection_summary)
# and JSON extraction live in core.agents._common — shared with the planner.


_INPUTS_SCREENSHOT = """\
# INPUTS YOU RECEIVE

Every turn you get TWO views of the canvas:

- A **screenshot** of the application window (attached to the user message).
- The **SCENE GRAPH** below — the framework's deterministic symbolic model
  of canvas objects, edges, and selection.

Treat the SCENE GRAPH as authoritative. The screenshot is a visual cross-check
useful for noticing things the symbolic state cannot capture (overlap, fine
alignment, off-canvas drift). When the two agree, plan from the SCENE GRAPH.
When they disagree, the SCENE GRAPH is stale; call `scan_handles` to refresh."""

_INPUTS_TEXT_ONLY = """\
# INPUTS YOU RECEIVE

Every turn you get ONE view of the canvas:

- The **SCENE GRAPH** below — the framework's deterministic symbolic model
  of canvas objects, edges, and selection. **This is your ONLY view.**

You do NOT receive a screenshot. Every reasoning step must cite SCENE GRAPH
content directly. If the SCENE GRAPH lacks the information you need to choose
a tool, call `scan_handles` (refreshes selection chrome) or
`click_empty_canvas` (resets focus) rather than guessing."""


_SYSTEM_TEMPLATE = """\
You are the **Executor** agent for draw.io. You pick exactly one tool
per turn. You do NOT specify coordinates — the framework owns those.

{inputs_block}

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


def build_prompt(ui_graph: Dict[str, Any], use_screenshot: bool = True) -> str:
    """Build the system prompt for the LLM.

    Parameters
    ----------
    ui_graph:
        Current UI graph (with scene_graph + selected_handles mounted).
    use_screenshot:
        If True (default), the INPUTS block tells the LLM to expect a
        screenshot alongside the SCENE GRAPH. If False, the INPUTS block
        states the SCENE GRAPH is the sole view of the canvas. The choice
        must match what the caller actually attaches to the user message
        — see ``infer(screenshot_path=...)``.
    """
    sg_data = ui_graph.get("scene_graph") or _sg.load()
    inputs_block = _INPUTS_SCREENSHOT if use_screenshot else _INPUTS_TEXT_ONLY
    return _SYSTEM_TEMPLATE.format(
        inputs_block=inputs_block,
        tool_table=_tool_table(),
        element_summary=element_summary(ui_graph),
        scene_graph_summary=_sg.summary_for_prompt(sg_data),
        active_selection=active_selection_summary(ui_graph),
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def parse_response(raw: str) -> Dict[str, Any]:
    """Extract the decision JSON object from the LLM's raw text output."""
    return extract_json(raw)


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def infer(
    task: str,
    ui_graph: Dict[str, Any],
    screenshot_path: Optional[str] = None,
    history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Ask the LLM to choose the next tool.

    The caller decides whether the LLM sees a screenshot on this turn by
    passing (or omitting) ``screenshot_path``. The system prompt adapts:

    - ``screenshot_path`` is a path → the prompt's INPUTS block says
      "you receive a screenshot + SCENE GRAPH", and the image is attached
      to the user message.
    - ``screenshot_path`` is ``None`` → the prompt's INPUTS block says
      "SCENE GRAPH is your only view", and no image is attached.

    Both modes share the rest of the prompt (tool catalog, decision
    procedure, scene-graph summary, active selection, drawio quirks).

    Args:
        task:            Natural-language task description.
        ui_graph:        Current UI graph (element names shown, no coords).
        screenshot_path: Path to a PNG to attach. Pass ``None`` for
                         text-only inference (SCENE GRAPH as sole input).
        history:         Prior conversation turns for multi-step reasoning.

    Returns:
        Dict with keys: ``reasoning``, ``tool``, ``params``.
    """
    use_screenshot = screenshot_path is not None
    model = config.executor_model_config().model
    prompt = build_prompt(ui_graph, use_screenshot=use_screenshot)

    messages: List[Dict[str, Any]] = [{"role": "system", "content": prompt}]
    if history:
        messages.extend(history)

    user_msg: Dict[str, Any] = {"role": "user", "content": f"Task: {task}"}
    messages.append(user_msg)

    mode = "screenshot+sg" if use_screenshot else "text-only"
    logger.info("Querying %s (%s) …", model, mode)
    response = llm.chat(
        purpose="executor",
        messages=messages,
        images=[screenshot_path] if use_screenshot else None,
        response_format="json_object",
    )
    raw = response.content
    logger.debug("Raw response:\n%s", raw)

    result = parse_response(raw)

    # Normalize: accept "action" key as alias for "tool"
    if "tool" not in result and "action" in result:
        result["tool"] = result.pop("action")
    if "tool" not in result:
        raise ValueError(f"Executor response missing 'tool' key: {result}")

    logger.info("Decided: %s  %s", result['tool'], result.get('params', {}))
    return result
