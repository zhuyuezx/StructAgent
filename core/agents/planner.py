"""
Planner agent — text prompt → full ordered sequence of parameterized tools.

Where the :mod:`core.agents.executor` picks ONE tool per turn (N LLM calls
per task), the Planner emits the WHOLE plan in a SINGLE LLM call: an ordered
list of ``{tool, params}`` steps that the framework then runs deterministically
via :func:`core.orchestrator.run_plan`. This is the "prompt → draft graph"
call from ORCHESTRATOR.md, narrowed to a linear sequence for Phase 1.

The Planner never specifies pixel coordinates. It fills each tool's *typed*
parameters (see :mod:`core.tools.param_specs`) by reading:

  - the **SCENE GRAPH** — existing objects/edges, referenced by ``obj_NNN`` /
    ``edge_NNN`` id;
  - the **sidebar shape list** — valid ``tool_name`` values;
  - the fixed vocabularies (directions, anchors) baked into the param specs.

Objects the plan *creates* are referenced downstream by the **label** assigned
to them (``type_label`` / the ``label`` param), since their ``obj_NNN`` id does
not exist at planning time. The draw.io operands resolve labels → ids at run
time (see ``connect_shapes`` / ``click_node`` in domains/drawio).

Two inference modes, mirroring the executor and selected per call:

  - **screenshot+SG** (default) — pass ``screenshot_path``; the image is
    attached and the SCENE GRAPH is authoritative.
  - **text-only** — pass ``screenshot_path=None``; the SCENE GRAPH is the only
    view. This is the cheap mode the orchestrator is designed around.
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
from core.tools.param_specs import format_param, spec_for
# Reuse the executor's coordinate-free state renderers — same package, same
# SCENE GRAPH / sidebar / active-selection blocks the executor already trusts.
from core.agents.executor import _element_summary, _active_selection_summary

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _typed_tool_table() -> str:
    """Render the catalog with each param shown as ``name:type`` (+enum)."""
    lines = [
        "| tool | level | parameters | description |",
        "|------|-------|------------|-------------|",
    ]
    for name, node in TOOL_CATALOG.items():
        if node.params:
            ptxt = ", ".join(format_param(p, node.param_specs) for p in node.params)
        else:
            ptxt = "(none)"
        lines.append(f"| {name} | L{node.level} | {ptxt} | {node.description} |")
    return "\n".join(lines)


def _param_type_glossary() -> str:
    """Describe each param *type* once (keyed by type, not by every param).

    Pulls the canonical descriptions from the central spec map so the glossary
    stays in sync with what the tool table advertises.
    """
    # One representative param per type → its description.
    reps = {
        "tool_name": "tool_name",
        "scene_object": "source_id",
        "scene_edge": "edge_id",
        "direction": "direction",
        "anchor": "source_anchor",
        "int": "amount",
        "string": "text",
        "keys": "keys",
    }
    lines = []
    for type_name, rep in reps.items():
        desc = spec_for(rep).get("description", "")
        lines.append(f"- **{type_name}** — {desc}")
    return "\n".join(lines)


_INPUTS_SCREENSHOT = """\
You receive TWO views of the canvas:

- A **screenshot** of the application window (attached to the user message).
- The **SCENE GRAPH** below — the framework's deterministic symbolic model of
  canvas objects, edges, and selection.

Treat the SCENE GRAPH as authoritative; the screenshot is a visual cross-check."""

_INPUTS_TEXT_ONLY = """\
You receive ONE view of the canvas:

- The **SCENE GRAPH** below — the framework's deterministic symbolic model of
  canvas objects, edges, and selection. **This is your ONLY view.** Every
  parameter you emit must trace back to SCENE GRAPH content or the sidebar
  shape list."""


# draw.io behaviours the plan must account for. Kept local to the Planner so
# the executor's prompt stays untouched; the wording mirrors it intentionally.
_QUIRKS = """\
- **`place_shape` always drops at the SAME default canvas position.** A second
  `place_shape` with no move in between lands ON TOP of the first. To place N
  free-standing shapes, after each placement `move_shape` it out of the drop
  zone (e.g. ~160-200 px) before the next `place_shape`. This is the single
  most common planning mistake.
- **`place_shape` auto-enters text-edit mode** on the new shape. Follow it with
  `type_label` then `press_escape`. Do NOT `double_click_node` a fresh shape.
- **Selection is single-shape.** `connect_shapes` selects the source itself —
  you do NOT need to `click_node` / `hover_object` first; just pass the two ids
  or labels.
- **Edges are numbered in creation order** (edge_001, edge_002, …). If you plan
  to `label_edge`, count the connect/extend steps to know the edge id."""


_SYSTEM_TEMPLATE = """\
You are the **Planner** for draw.io. Given a task, you output a COMPLETE,
ordered sequence of tool calls that — run top-to-bottom by the framework —
accomplishes the task. You plan the WHOLE task in ONE response. You are NOT
called once per step, so do not stop early or wait for feedback.

You never specify pixel coordinates. You pick named tools and fill their typed
parameters by reading the SCENE GRAPH, the sidebar shape list, and the fixed
vocabularies below.

# INPUTS YOU RECEIVE
{inputs_block}

# HOW TO FILL THE PARAMETER SPACE
Each tool parameter has a type. Fill it like this:

{type_glossary}

Rules:
- Reference objects that ALREADY exist in the SCENE GRAPH by their `obj_NNN`
  id. Reference objects you CREATE earlier in THIS plan by the **label** you
  give them — their `obj_NNN` id does not exist yet. Keep labels UNIQUE.
- `tool_name` must be one of the sidebar shapes under REFERENCE.
- Pick concrete integers for `amount` / sizes / angles.
- Prefer higher-level tools (L2 compounds like `place_and_label`) when they
  match — they make the plan shorter and more robust.

# PLAN AS IF YOU WERE EXECUTING
Simulate the canvas in your head as the steps run: track where each shape sits
and which one is selected. Respect the drawio quirks below.

# CHECKPOINTS (attach at milestones — strongly recommended)
After steps that produce a verifiable result (finished placing+labelling a
shape, finished a connection, finished the whole layout), attach a
`"checkpoint"` to that step. The framework screenshots the canvas there and
checks these structural assertions against the SCENE GRAPH — no extra cost.

A checkpoint is: `{{"description": "...", "assert": [ <assertion>, ... ]}}`.
Assertions (use the SCENE GRAPH facts you are predicting):
- `{{"check": "objects_count", "op": ">=", "value": 2}}`  (op: == != >= <= > <)
- `{{"check": "edges_count", "op": "==", "value": 1}}`
- `{{"check": "object_exists", "label": "Source"}}`
- `{{"check": "edge_exists", "source": "Source", "target": "Target"}}`
- `{{"check": "selected", "label": "Target"}}`
Prefer `object_exists` / `edge_exists` (robust) over exact counts. Keep 1-3
assertions per checkpoint. Steps without a meaningful result need no checkpoint.

# drawio QUIRKS
{quirks_block}

# AVAILABLE TOOLS (typed params)
{tool_table}

# REFERENCE — sidebar shapes you can place
{element_summary}

# CURRENT STATE — read this before planning
## SCENE GRAPH (canvas objects + edges, deterministic)
{scene_graph_summary}

{active_selection}

# OUTPUT FORMAT
Respond with a SINGLE JSON object — no markdown, no commentary, no code fences.
Attach a "checkpoint" only to steps that produce a verifiable milestone:

{{
  "reasoning": "How the SCENE GRAPH + task map to this sequence of steps.",
  "steps": [
    {{"tool": "place_and_label", "params": {{"tool_name": "Rectangle_Tool", "label": "Source"}},
     "checkpoint": {{"description": "Source placed",
                    "assert": [{{"check": "object_exists", "label": "Source"}}]}}}},
    {{"tool": "<tool_name>", "params": {{ ... }}}}
  ]
}}
"""


def build_prompt(ui_graph: Dict[str, Any], use_screenshot: bool = False) -> str:
    """Build the Planner system prompt.

    Parameters
    ----------
    ui_graph:
        Current UI graph (with ``scene_graph`` + ``selected_handles`` mounted).
    use_screenshot:
        If True, the INPUTS block tells the LLM to expect a screenshot
        alongside the SCENE GRAPH. The caller must attach the image to the
        user message to match — see :func:`plan`. Defaults to text-only, the
        mode the orchestrator is built around.
    """
    sg_data = ui_graph.get("scene_graph") or _sg.load()
    inputs_block = _INPUTS_SCREENSHOT if use_screenshot else _INPUTS_TEXT_ONLY
    return _SYSTEM_TEMPLATE.format(
        inputs_block=inputs_block,
        type_glossary=_param_type_glossary(),
        quirks_block=_QUIRKS,
        tool_table=_typed_tool_table(),
        element_summary=_element_summary(ui_graph),
        scene_graph_summary=_sg.summary_for_prompt(sg_data),
        active_selection=_active_selection_summary(ui_graph),
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(raw: str) -> Any:
    """Pull a JSON value (object or array) from the LLM's raw text output."""
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(text)
    if match:
        return json.loads(match.group(1))
    # First {...} or [...] — whichever appears first.
    candidates = [(text.find("{"), text.rfind("}")), (text.find("["), text.rfind("]"))]
    candidates = [(s, e) for s, e in candidates if s != -1 and e > s]
    if candidates:
        s, e = min(candidates, key=lambda c: c[0])
        return json.loads(text[s:e + 1])
    raise ValueError(f"Could not parse JSON from planner response:\n{raw}")


def _normalize_step(step: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce one raw step into ``{tool, params}`` (accepts 'action' alias)."""
    tool = step.get("tool") or step.get("action")
    params = step.get("params") or step.get("parameters") or {}
    out: Dict[str, Any] = {"tool": tool, "params": params}
    # Carry the model's per-step rationale through if present — useful for the
    # UI/repair phases; run_plan ignores it.
    if "reasoning" in step:
        out["reasoning"] = step["reasoning"]
    # Carry an optional checkpoint through — run_plan evaluates it after the
    # step (see core.checkpoint). Only keep well-formed dicts.
    ckpt = step.get("checkpoint")
    if isinstance(ckpt, dict) and ckpt.get("assert"):
        out["checkpoint"] = ckpt
    return out


def parse_plan_response(raw: str) -> Dict[str, Any]:
    """Parse the planner's raw output into ``{reasoning, steps}``.

    Accepts any of: a top-level JSON array of steps, ``{"steps": [...]}``, or
    ``{"plan": [...]}``. Each step is normalized to ``{tool, params}``.
    """
    data = _extract_json(raw)

    if isinstance(data, list):
        steps_raw, reasoning = data, ""
    elif isinstance(data, dict):
        steps_raw = data.get("steps") or data.get("plan") or []
        reasoning = data.get("reasoning", "")
    else:
        raise ValueError(f"Planner response is neither object nor array: {data!r}")

    if not isinstance(steps_raw, list):
        raise ValueError(f"Planner 'steps' is not a list: {steps_raw!r}")

    steps = [_normalize_step(s) for s in steps_raw if isinstance(s, dict)]
    missing = [i for i, s in enumerate(steps) if not s["tool"]]
    if missing:
        raise ValueError(f"Planner produced step(s) with no 'tool' at index {missing}")

    return {"reasoning": reasoning, "steps": steps}


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def plan(
    task: str,
    ui_graph: Dict[str, Any],
    screenshot_path: Optional[str] = None,
    history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Ask the LLM for a full plan (an ordered list of tool calls).

    Args:
        task:            Natural-language task description.
        ui_graph:        Current UI graph (element names shown, no coords).
        screenshot_path: Path to a PNG to attach. Pass ``None`` (default) for
                         text-only planning (SCENE GRAPH as sole input).
        history:         Optional prior turns — e.g. a prior failed plan + a
                         repair instruction (used by the repair loop later).

    Returns:
        ``{"reasoning": str, "steps": [{"tool", "params"}...]}``. Feed
        ``steps`` straight to :func:`core.orchestrator.run_plan`.
    """
    use_screenshot = screenshot_path is not None
    model = config.llm_model()
    prompt = build_prompt(ui_graph, use_screenshot=use_screenshot)

    messages: List[Dict[str, Any]] = [{"role": "system", "content": prompt}]
    if history:
        messages.extend(history)

    user_msg: Dict[str, Any] = {
        "role": "user",
        "content": f"Task: {task}\n\nOutput the complete plan now as one JSON object.",
    }
    if use_screenshot:
        with open(screenshot_path, "rb") as f:
            user_msg["images"] = [f.read()]
    messages.append(user_msg)

    mode = "screenshot+sg" if use_screenshot else "text-only"
    logger.info("Planning with %s (%s) …", model, mode)
    response = ollama.chat(model=model, messages=messages)
    raw = response["message"]["content"]
    logger.debug("Raw planner response:\n%s", raw)

    result = parse_plan_response(raw)
    logger.info("Planner produced %d step(s): %s",
                len(result["steps"]), [s["tool"] for s in result["steps"]])
    return result


def chat_plan(
    messages: List[Dict[str, Any]],
    ui_graph: Dict[str, Any],
    screenshot_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Conversational planning — refine a plan over a running thread.

    ``messages`` is the full conversation as ``[{role, content}, ...]`` where
    assistant turns hold the model's prior plan JSON (so it sees the current
    plan as context) and the final turn is the user's latest instruction
    ("make the boxes bigger", "add a third one"). The model re-emits the
    COMPLETE updated plan each turn; the caller replaces its steps with it and
    shows ``reasoning`` as the assistant's chat reply.

    Same system prompt as :func:`plan` (catalog, scene graph, quirks,
    checkpoints). Returns ``{"reasoning", "steps"}``.
    """
    if not messages or messages[-1].get("role") != "user":
        raise ValueError("chat_plan: messages must end with a 'user' turn")

    use_screenshot = screenshot_path is not None
    model = config.llm_model()
    prompt = build_prompt(ui_graph, use_screenshot=use_screenshot)

    convo: List[Dict[str, Any]] = [{"role": "system", "content": prompt}]
    # Copy the provided turns; attach the screenshot to the latest user turn.
    turns = [dict(m) for m in messages]
    if use_screenshot:
        with open(screenshot_path, "rb") as f:
            turns[-1]["images"] = [f.read()]
    convo.extend(turns)

    logger.info("Chat-planning with %s (%d turns) …", model, len(messages))
    response = ollama.chat(model=model, messages=convo)
    raw = response["message"]["content"]
    logger.debug("Raw chat-plan response:\n%s", raw)

    result = parse_plan_response(raw)
    logger.info("Chat-plan produced %d step(s)", len(result["steps"]))
    return result


# ---------------------------------------------------------------------------
# Repair — corrective re-plan from the CURRENT scene graph (Phase 3)
# ---------------------------------------------------------------------------

def _format_failures(failed_steps: Optional[List[Dict[str, Any]]]) -> str:
    """Render the flagged/failed steps for the repair user message."""
    if not failed_steps:
        return ("(No specific step was flagged — the result did not match the "
                "task. Inspect the SCENE GRAPH and correct whatever is missing "
                "or wrong.)")
    lines: List[str] = []
    for e in failed_steps:
        n = e.get("step", "?")
        tool = e.get("tool", "?")
        params = e.get("params", {})
        res = e.get("result", {}) or {}
        line = f"- Step {n}: {tool}({json.dumps(params)}) → {res.get('status', '?')}"
        if res.get("error"):
            line += f"; error: {res['error']}"
        cp = e.get("checkpoint")
        if isinstance(cp, dict) and cp.get("passed") is False:
            fails = [r.get("detail") for r in cp.get("results", [])
                     if not r.get("passed")]
            line += f"; checkpoint FAILED: {cp.get('description', '')}"
            if fails:
                line += " [" + "; ".join(str(f) for f in fails) + "]"
        if e.get("flagged_wrong"):
            line += "; USER FLAGGED THIS STEP AS WRONG"
        lines.append(line)
    return "\n".join(lines)


_REPAIR_USER_TEMPLATE = """\
A plan was executed but did NOT fully achieve the task. The SCENE GRAPH in the
system prompt above is the ACTUAL current canvas — plan your fix from there.

# ORIGINAL TASK
{task}

# WHAT WENT WRONG
{failures}
{user_block}
# YOUR JOB
Output a corrective plan (the SAME JSON format: an object with "reasoning" and
"steps"). Continue from the CURRENT SCENE GRAPH to satisfy the ORIGINAL TASK.
Do NOT redo steps that the SCENE GRAPH shows were already done correctly. If a
shape ended up wrong (duplicated, mislabelled, misplaced), fix or remove it.
Attach checkpoints to the corrective steps so the fix can be verified."""


def repair(
    task: str,
    ui_graph: Dict[str, Any],
    *,
    failed_steps: Optional[List[Dict[str, Any]]] = None,
    user_note: str = "",
    screenshot_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Ask the LLM for a corrective plan after a checkpoint failure / user flag.

    Reuses the full Planner system prompt — including the CURRENT scene graph,
    tool catalog, quirks and checkpoint instructions — and adds a user message
    describing the original task, what went wrong, and the user's guidance.

    Args:
        task:            The original natural-language task.
        ui_graph:        Current UI graph (its ``scene_graph`` is authoritative).
        failed_steps:    Trace entries the user/checkpoints flagged as wrong —
                         ``{step, tool, params, result, checkpoint?, flagged_wrong?}``.
        user_note:       Optional free-text instruction ("the box is too small").
        screenshot_path: Attach a screenshot for screenshot+SG repair, else None.

    Returns:
        ``{"reasoning", "steps"}`` — a corrective plan to review and run.
    """
    use_screenshot = screenshot_path is not None
    model = config.llm_model()
    prompt = build_prompt(ui_graph, use_screenshot=use_screenshot)

    user_block = f"\n# USER GUIDANCE\n{user_note.strip()}\n" if user_note.strip() else ""
    user_text = _REPAIR_USER_TEMPLATE.format(
        task=task,
        failures=_format_failures(failed_steps),
        user_block=user_block,
    )

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_text},
    ]
    if use_screenshot:
        with open(screenshot_path, "rb") as f:
            messages[-1]["images"] = [f.read()]

    logger.info("Repairing with %s (%d flagged step(s)) …",
                model, len(failed_steps or []))
    response = ollama.chat(model=model, messages=messages)
    raw = response["message"]["content"]
    logger.debug("Raw repair response:\n%s", raw)

    result = parse_plan_response(raw)
    logger.info("Repair produced %d corrective step(s): %s",
                len(result["steps"]), [s["tool"] for s in result["steps"]])
    return result
