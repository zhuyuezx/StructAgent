"""
save_tool — persist a successful task trace as a reusable JSON compound tool.

Workflow
────────
1.  Run a task (manually or via the Executor agent).
2.  Collect the list of step results from dispatch().
3.  Call check_trace_success(results) to verify all steps returned 'ok'.
4.  Call save_trace_as_tool(name, steps, ...) to write the JSON definition
    to state/tools/ and register it immediately in the live catalog.

The LLM can also call save_trace_as_tool directly by including it as a
special tool in its action space — the JSON format it produces is the
same schema that loader.py uses.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config
from core.tools.loader import load_tool_definition
from core.tools.registry import TOOL_CATALOG


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

    defn: Dict[str, Any] = {
        "name": name,
        "description": description,
        "params": params,
        "needs_ui_graph": needs_ui_graph,
        "steps": steps,
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
    print(f"  [save_trace_as_tool] '{name}' saved → {out_path}  (L{node.level})")
    return defn
