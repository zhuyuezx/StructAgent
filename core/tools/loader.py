"""
JSON Tool Loader — register tools from JSON definition files.

Two tool kinds (distinguished by which key is present in the JSON):

  "python_fn"  →  L1 tools with a real Python implementation.
                   JSON declares the interface (params, children,
                   description); execution delegates to the named function.
  "steps"      →  L2+ compound tools defined as a sequence of dispatch()
                   calls.  No custom Python required; the LLM can write these.

JSON schema
───────────
{
  "name":           str,
  "description":    str,
  "params":         [str, ...],
  "needs_ui_graph": bool,

  // exactly one of:
  "children":  [tool_name, ...],          // for python_fn tools
  "python_fn": "module.path:fn_name",     // for python_fn tools

  "steps": [                              // for compound tools
    { "tool": str,
      "params": { str: value | "$param_name" }
    }
  ]
}

Parameter substitution
──────────────────────
Step param values beginning with "$" are replaced at call-time with the
matching kwarg. E.g. "$tool_name" → kwargs["tool_name"].
"""
from __future__ import annotations

import importlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.tools.registry import ToolNode, register, TOOL_CATALOG

logger = logging.getLogger(__name__)

_STEP_PAUSE = 0.3


# ===========================================================================
# Internal helpers
# ===========================================================================

def _import_fn(python_fn_ref: str):
    """Import 'module.path:function_name' and return the callable."""
    module_path, fn_name = python_fn_ref.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, fn_name)


def _make_compound_executor(name: str, steps: List[Dict]):
    """Return a callable that executes *steps* via dispatch()."""

    # node_ref lets the executor print the correct auto-computed level.
    node_ref: List[Optional[ToolNode]] = [None]

    def fn(**kwargs):
        from core.tools.registry import dispatch as _dispatch

        ui_graph = kwargs.get("ui_graph")
        lvl = node_ref[0].level if node_ref[0] else "?"
        logger.info("  [L%s] %s", lvl, name)
        results = []
        for step in steps:
            tool = step["tool"]
            resolved = {
                k: (kwargs.get(v[1:]) if isinstance(v, str) and v.startswith("$") else v)
                for k, v in step.get("params", {}).items()
            }
            r = _dispatch(tool, resolved, ui_graph=ui_graph)
            results.append(r)
            if r.get("status") == "error":
                return {
                    "status": "error", "tool": name,
                    "failed_step": tool, "error": r.get("error"),
                }
            time.sleep(_STEP_PAUSE)

        ok = all(r.get("status") == "ok" for r in results)
        return {"status": "ok" if ok else "partial", "tool": name,
                "steps": results}

    fn.__name__ = f"_fn_{name}"
    return fn, node_ref


# ===========================================================================
# Public API
# ===========================================================================

def load_tool_definition(defn: Dict[str, Any]) -> ToolNode:
    """Parse one JSON definition dict, create a ToolNode, register it."""
    name = defn["name"]
    params = defn.get("params", [])
    needs_ui_graph = defn.get("needs_ui_graph", True)
    description = defn.get("description", "")

    if "python_fn" in defn:
        # ── Python-backed L1 tool ─────────────────────────────────────
        fn = _import_fn(defn["python_fn"])
        children = [TOOL_CATALOG[c] for c in defn.get("children", [])
                    if c in TOOL_CATALOG]
        node = ToolNode(
            name=name, fn=fn,
            params=params, needs_ui_graph=needs_ui_graph,
            description=description,
            children=children,
        )

    elif "steps" in defn:
        # ── Compound tool (pure JSON composition) ─────────────────────
        steps = defn["steps"]
        fn, node_ref = _make_compound_executor(name, steps)
        children = []
        seen: set = set()
        for step in steps:
            t = step["tool"]
            if t in TOOL_CATALOG and t not in seen:
                children.append(TOOL_CATALOG[t])
                seen.add(t)
        node = ToolNode(
            name=name, fn=fn,
            params=params, needs_ui_graph=needs_ui_graph,
            description=description,
            children=children,
        )
        node_ref[0] = node

    else:
        raise ValueError(
            f"Tool definition '{name}' must have either 'python_fn' or 'steps'."
        )

    register(node)
    return node


def load_tools_from_dir(tools_dir: Path) -> List[ToolNode]:
    """
    Load every *.json file in *tools_dir* as a tool definition.

    Two-pass loading: python_fn tools (L1) are loaded before compound step
    tools (L2+) so that children are fully resolved when compounds are built.
    Within each pass files are sorted alphabetically.
    """
    tools_dir = Path(tools_dir)
    all_defns: List[Dict[str, Any]] = []
    for path in sorted(tools_dir.glob("*.json")):
        with open(path) as f:
            all_defns.append(json.load(f))

    python_defns = [d for d in all_defns if "python_fn" in d]
    compound_defns = [d for d in all_defns if "steps" in d]

    nodes: List[ToolNode] = []
    for defn in python_defns + compound_defns:
        nodes.append(load_tool_definition(defn))
    return nodes
