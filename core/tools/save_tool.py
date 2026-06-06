"""
save_tool — persist a successful task trace as a reusable JSON compound tool.

Workflow
────────
1.  Run a task (manually or via the Executor agent).
2.  Collect the list of step results from dispatch().
3.  Call check_trace_success(results) to verify all steps returned 'ok'.
4.  Call save_trace_as_tool(name, steps, ...) to write the JSON definition
    to state/tools/ and register it immediately in the live catalog.

Sanitization
─────────────
Before saving, the trace is automatically sanitized:

  - **Consecutive duplicate steps** are collapsed (the LLM sometimes retries
    the same move when a prior attempt didn't change the scene graph).
  - **Hardcoded scene-graph IDs** (``obj_001``, ``obj_002``, …) in
    ``connect_shapes`` / ``click_node`` / ``hover_object`` are replaced
    with the **label** of the object at the time the trace was recorded,
    so the saved tool works regardless of which IDs objects get at replay
    time.

The LLM can also call save_trace_as_tool directly by including it as a
special tool in its action space — the JSON format it produces is the
same schema that loader.py uses.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config
from core.tools.loader import load_tool_definition

logger = logging.getLogger(__name__)

# Regex matching auto-generated scene-graph IDs like "obj_001", "obj_042".
_OBJ_ID_RE = re.compile(r"^obj_\d+$")


# ===========================================================================
# Helpers
# ===========================================================================

def tools_dir() -> Path:
    """Return (and create) the state/tools/ directory."""
    d = Path(config.state_dir()) / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


def check_trace_success(results: List[Dict[str, Any]]) -> bool:
    """
    Return True if every step in *results* completed with status='ok'.

    Pass the list of dicts returned by successive dispatch() calls, or the
    'steps' list inside a compound tool result.
    """
    return bool(results) and all(r.get("status") == "ok" for r in results)


# ===========================================================================
# Trace sanitization
# ===========================================================================

def _build_id_to_label(trace: List[Dict[str, Any]]) -> Dict[str, str]:
    """Walk the trace and map obj_NNN → label from type_label / place_and_label
    results, so we can replace hardcoded IDs with human-readable labels."""
    mapping: Dict[str, str] = {}

    # Track which object was most recently created / selected so we can
    # attribute a subsequent type_label to it.
    current_id: Optional[str] = None

    for step in trace:
        tool = step.get("tool", "")
        params = step.get("params", {})
        result = step.get("result", {})

        if tool == "place_shape":
            # place_shape result contains scene_object_id
            oid = result.get("scene_object_id")
            if oid:
                current_id = oid

        elif tool == "type_label":
            # type_label gives a label to the currently selected object
            text = params.get("text", "")
            if current_id and text:
                mapping[current_id] = text

        elif tool == "place_and_label":
            # place_and_label combines place + type + escape
            oid = result.get("scene_object_id")
            # Check nested steps for the object ID
            for sub in result.get("steps", []):
                if sub.get("tool") == "place_shape":
                    oid = oid or sub.get("scene_object_id")
            label = params.get("label", "")
            if oid and label:
                mapping[oid] = label

        elif tool in ("click_node", "click_empty_canvas"):
            selected = result.get("selected_object")
            if selected:
                current_id = selected

    return mapping


def _replace_ids_in_params(
    params: Dict[str, Any], mapping: Dict[str, str],
) -> Dict[str, Any]:
    """Replace obj_NNN values in params with labels where possible."""
    out = {}
    for key, val in params.items():
        if isinstance(val, str) and _OBJ_ID_RE.match(val) and val in mapping:
            out[key] = mapping[val]
            logger.debug("  Replaced %s=%s → '%s'", key, val, mapping[val])
        else:
            out[key] = val
    return out


# Keys whose values may contain scene-graph IDs.
_ID_PARAM_KEYS = {"source_id", "target_id", "node_ref", "object_id"}


def sanitize_trace(
    steps: List[Dict[str, Any]],
    trace: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Sanitize a trace before saving as a compound tool.

    Parameters
    ----------
    steps : list
        The step dicts (``{tool, params}``) to save.
    trace : list, optional
        The full trace dicts (``{tool, params, result}``) from the LLM run.
        If provided, used to build ID→label mapping for replacement.

    Returns
    -------
    list
        Cleaned steps with duplicates removed and IDs replaced.
    """
    cleaned = list(steps)

    # ── 1. Deduplicate consecutive identical steps ────────────────────
    deduped: List[Dict[str, Any]] = []
    for step in cleaned:
        if deduped and step == deduped[-1]:
            logger.info("  Sanitize: dropped duplicate step %s(%s)",
                        step["tool"], step.get("params", {}))
            continue
        deduped.append(step)
    cleaned = deduped

    # ── 2. Replace hardcoded obj_NNN IDs with labels ─────────────────
    if trace:
        mapping = _build_id_to_label(trace)
        if mapping:
            logger.info("  Sanitize: ID→label map: %s", mapping)
            result: List[Dict[str, Any]] = []
            for step in cleaned:
                params = step.get("params", {})
                # Only touch params that might contain IDs
                if any(
                    isinstance(params.get(k), str) and _OBJ_ID_RE.match(params[k])
                    for k in _ID_PARAM_KEYS if k in params
                ):
                    new_params = _replace_ids_in_params(params, mapping)
                    result.append({"tool": step["tool"], "params": new_params})
                else:
                    result.append(step)
            cleaned = result

    return cleaned


# ===========================================================================
# Core save function
# ===========================================================================

def save_trace_as_tool(
    name: str,
    steps: List[Dict[str, Any]],
    description: str = "",
    params: Optional[List[str]] = None,
    needs_ui_graph: bool = True,
    overwrite: bool = False,
    save_dir: Optional[Path] = None,
    trace: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Save a sequence of tool steps as a reusable JSON compound tool.

    Parameters
    ──────────
    name          Tool name (used as the filename: ``<name>.json``).
    steps         List of step dicts::
                      [{"tool": "place_shape",
                        "params": {"tool_name": "$tool_name"}}, ...]
                  Values starting with ``$`` are parameter references
                  resolved at call-time from the caller's kwargs.
    description   Human-readable description shown in the tool catalog.
    params        Names of the ``$``-referenced parameters (ordered).
                  Omit or pass [] for a no-parameter tool that always
                  does the exact same thing.
    needs_ui_graph  Pass True (default) if any step needs the scene graph.
    overwrite     Replace an existing JSON file with the same name.
    save_dir      Override the default state/tools/ directory.
    trace         The full trace (with results) from the LLM run.
                  Enables ID→label replacement sanitization.

    Returns
    ───────
    The JSON definition dict that was written.  The tool is also
    registered immediately in the live TOOL_CATALOG.

    Example — save a verbatim trace (no parameters)
    ────────────────────────────────────────────────
    >>> save_trace_as_tool(
    ...     name="setup_source_target",
    ...     steps=[
    ...         {"tool": "place_shape",  "params": {"tool_name": "Rectangle_Tool"}},
    ...         {"tool": "type_label",   "params": {"text": "Source"}},
    ...         {"tool": "press_escape", "params": {}},
    ...         {"tool": "place_shape",  "params": {"tool_name": "Rectangle_Tool"}},
    ...         {"tool": "type_label",   "params": {"text": "Target"}},
    ...         {"tool": "press_escape", "params": {}},
    ...     ],
    ...     description="Place two rectangles labelled Source and Target.",
    ... )
    """
    if params is None:
        params = []

    # ── Sanitize before saving ────────────────────────────────────────
    clean_steps = sanitize_trace(steps, trace=trace)

    if len(clean_steps) != len(steps):
        logger.info("  Sanitized %d steps → %d steps",
                    len(steps), len(clean_steps))

    # ── Reject self-reference ─────────────────────────────────────────
    # A compound that lists itself as a step recurses forever at dispatch
    # and makes its auto-computed level grow on every reload. This guard is
    # checked BEFORE the file is written, so a bad trace (e.g. one where the
    # LLM happened to call this very tool) can never overwrite a known-good
    # definition already on disk.
    self_refs = [i for i, s in enumerate(clean_steps) if s.get("tool") == name]
    if self_refs:
        raise ValueError(
            f"Refusing to save tool '{name}': step index {self_refs} call the "
            f"tool being defined, which would recurse infinitely when "
            f"dispatched. Remove the self-referential step(s) from the trace."
        )

    defn: Dict[str, Any] = {
        "name": name,
        "description": description,
        "params": params,
        "needs_ui_graph": needs_ui_graph,
        "steps": clean_steps,
    }

    out_dir = Path(save_dir) if save_dir else tools_dir()
    out_path = out_dir / f"{name}.json"

    if out_path.exists() and not overwrite:
        raise FileExistsError(
            f"Tool '{name}' already exists at {out_path}. "
            "Pass overwrite=True to replace it."
        )

    out_path.write_text(json.dumps(defn, indent=2))
    node = load_tool_definition(defn)
    logger.info("[save_trace_as_tool] '%s' saved → %s  (L%s)", name, out_path, node.level)
    return defn
