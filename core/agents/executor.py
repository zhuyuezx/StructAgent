"""
Executor agent — picks the next tool given a task and current UI graph.

Constructs a coordinate-free prompt from the tool catalog and detected
element names, sends it to a local LLM via Ollama, and parses the JSON
response. The executor never sees pixel coordinates — it only picks
named tools and references elements by name/id.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import ollama

from core import config
from core.perception.canvas import tool_families
from core.tools import TOOL_CATALOG


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

        families = tool_families(ui_graph.get("UI_Elements", {}))
        if families:
            parts.append("\n### Ambiguous Sidebar Families")
            parts.append(
                "Use the exact tool names below with `place_shape`; "
                "`Rectangle_Tool` is the default rectangle candidate."
            )
            for family, candidates in families.items():
                joined = ", ".join(f"`{c}`" for c in candidates)
                parts.append(f"- `{family}` candidates: {joined}")

    nodes = ui_graph.get("Canvas_Nodes", [])
    parts.append("\n### Observed Canvas")
    if nodes:
        parts.append(f"Visible node count: {len(nodes)}")
        for n in nodes:
            text = n.get("text", "")
            confidence = n.get("confidence")
            source = n.get("source", "unknown")
            parts.append(
                f"- id=`{n['id']}`, text=`{text}`, "
                f"confidence=`{confidence}`, source=`{source}`"
            )
    else:
        parts.append("Visible node count: 0")

    edges = ui_graph.get("Canvas_Edges", [])
    if edges:
        parts.append("\n### Canvas Edges")
        for e in edges:
            parts.append(f"- `{e['source']}` → `{e['target']}`")

    return "\n".join(parts)


_SYSTEM_TEMPLATE = """\
You are the **Planner** agent for draw.io.

## RULES
1. You **CANNOT** specify or produce any pixel coordinates.
2. Choose ONLY from the AVAILABLE TOOLS below.
3. Reference elements by **name** or **id** only.
4. If the required element is not listed, use `"request_rescan"`.
5. Output **exactly ONE tool call** per response.

## draw.io WORKFLOW (important!)
- `place_shape` → shape appears on canvas. **Text cursor is ALREADY ACTIVE** inside the shape.
- After `place_shape`, use `type_label` directly — do NOT use `double_click_node`.
- After `type_label`, use `press_escape` to exit text editing.
- After `press_escape`, the shape is still selected. Use `click_empty_canvas` to deselect.
- `double_click_node` is ONLY needed to re-edit an existing node's label.

## AVAILABLE TOOLS
{tool_table}

**Special signals** (no params):
| tool | description |
|------|-------------|
| request_rescan | Re-perceive the screen |
| task_complete  | Signal task is finished |

## DETECTED ELEMENTS
{element_summary}

## OUTPUT FORMAT
Respond with a single JSON object — no markdown, no commentary:
{{
  "reasoning": "<your step-by-step logic>",
  "tool": "<tool_name>",
  "params": {{}}
}}
"""


def build_prompt(ui_graph: Dict[str, Any]) -> str:
    """Build the system prompt for the LLM."""
    return _SYSTEM_TEMPLATE.format(
        tool_table=_tool_table(),
        element_summary=_element_summary(ui_graph),
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

    print(f"[EXECUTOR] Querying {model} …")
    response = ollama.chat(model=model, messages=messages)
    raw = response["message"]["content"]
    print(f"[EXECUTOR] Raw response:\n{raw}")

    result = parse_response(raw)

    # Normalize: accept "action" key as alias for "tool"
    if "tool" not in result and "action" in result:
        result["tool"] = result.pop("action")
    if "tool" not in result:
        raise ValueError(f"Executor response missing 'tool' key: {result}")

    print(f"[EXECUTOR] Decided: {result['tool']}  {result.get('params', {})}")
    return result
