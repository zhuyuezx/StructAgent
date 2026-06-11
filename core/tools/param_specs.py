"""
Param specs — typed, described parameters for every tool param.

This is the input half of the "typed inputs/outputs on tools" work
(ORCHESTRATOR.md, Phase 0) and the foundation for the Planner: every tool
parameter gets a **type**, a **description**, and (where applicable) a fixed
**enum** or a **source** telling the Planner where to read valid values
(sidebar shapes, scene-graph objects, scene-graph edges). With this the LLM
can fill the param space deterministically from the SCENE GRAPH instead of
guessing — see ``core/agents/planner.py``.

Two sources, merged by :func:`spec_for` (the tool override wins):

  1. :data:`PARAM_SPECS` — a central map keyed by the *canonical param name*.
     The codebase names params consistently (``direction``, ``amount``,
     ``tool_name``, ``source_id`` …), so one entry here describes that param
     across every tool that uses it. New tools with conventional param names
     get typed params for free.
  2. A tool's own JSON ``param_specs`` (optional) — for the rare param whose
     meaning is specific to one tool. Loaded onto ``ToolNode.param_specs``.

A ParamSpec is a plain dict::

    {
      "type": "string"|"int"|"direction"|"anchor"
            |"tool_name"|"scene_object"|"scene_edge"|"keys",
      "description": str,
      "enum":   [...],      # optional — a fixed vocabulary of valid values
      "source": "sidebar_shapes"|"scene_objects"|"scene_edges",  # optional
    }
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Compass-direction vocabularies shared by several specs.
_DIR4 = ["n", "s", "e", "w"]
_DIR8 = ["n", "s", "e", "w", "ne", "nw", "se", "sw"]


# ===========================================================================
# Central spec map — keyed by canonical param name
# ===========================================================================

PARAM_SPECS: Dict[str, Dict[str, Any]] = {
    # ── shape placement ───────────────────────────────────────────────
    "tool_name": {
        "type": "tool_name", "source": "sidebar_shapes",
        "description": "Sidebar shape to place — must be one of the listed "
                       "sidebar shapes.",
    },
    # ── text / labels ─────────────────────────────────────────────────
    "text": {
        "type": "string",
        "description": "Text to type into the currently focused shape or "
                       "edge label.",
    },
    "label": {
        "type": "string",
        "description": "Label to assign. Keep it UNIQUE within the plan so "
                       "later steps can reference this object by its label.",
    },
    # ── directions / geometry ─────────────────────────────────────────
    "direction": {
        "type": "direction", "enum": _DIR8,
        "description": "Compass direction. move/resize accept all 8; "
                       "extend accepts n/s/e/w only.",
    },
    "amount": {
        "type": "int",
        "description": "Distance in logical pixels — a fraction of the "
                       "shape's size (typically 100-200).",
    },
    "angle_degrees": {
        "type": "int",
        "description": "Rotation angle in degrees about the shape center.",
    },
    "new_width": {"type": "int", "description": "New width in logical pixels."},
    "new_height": {"type": "int", "description": "New height in logical pixels."},
    # ── object / edge references ──────────────────────────────────────
    "source_id": {
        "type": "scene_object", "source": "scene_objects",
        "description": "Edge source — a SCENE GRAPH object id (obj_NNN) or the "
                       "label of an object created earlier in this plan.",
    },
    "target_id": {
        "type": "scene_object", "source": "scene_objects",
        "description": "Edge target — a SCENE GRAPH object id (obj_NNN) or the "
                       "label of an object created earlier in this plan.",
    },
    "source_anchor": {
        "type": "anchor", "enum": ["n", "s", "e", "w", "auto"],
        "description": "Side of the source the edge leaves from. 'auto' lets "
                       "the framework pick the side facing the target.",
    },
    "target_anchor": {
        "type": "anchor", "enum": ["n", "s", "e", "w", "auto"],
        "description": "Side of the target the edge connects to. 'auto' lets "
                       "the framework pick the side facing the source.",
    },
    "edge_id": {
        "type": "scene_edge", "source": "scene_edges",
        "description": "Edge to act on — an edge id (edge_NNN) from the SCENE "
                       "GRAPH. Edges are numbered in creation order from "
                       "edge_001.",
    },
    "node_ref": {
        "type": "scene_object", "source": "scene_objects",
        "description": "Canvas node to click — an object id (obj_NNN) or its "
                       "label.",
    },
    "object_id": {
        "type": "scene_object", "source": "scene_objects",
        "description": "Canvas object to act on — an object id (obj_NNN) or "
                       "its label.",
    },
    "reference_node": {
        "type": "scene_object", "source": "scene_objects",
        "description": "Node to position relative to — id (obj_NNN) or label.",
    },
    # ── misc ──────────────────────────────────────────────────────────
    "clicks": {
        "type": "int", "enum": [1, 2],
        "description": "Click count — 1 selects, 2 enters text-edit mode.",
    },
    "keys": {
        "type": "keys",
        "description": "Key chord as a list, e.g. [\"command\", \"z\"].",
    },
    "key": {
        "type": "string",
        "description": "Single key name, e.g. 'Return', 'Escape', 'BackSpace'.",
    },
    "offset_x": {"type": "int", "description": "X offset from the reference node (logical px)."},
    "offset_y": {"type": "int", "description": "Y offset from the reference node (logical px)."},
    # Raw L0 coordinate params — the Planner should avoid these (they need
    # pixel coords it does not have); kept typed for completeness.
    "x": {"type": "int", "description": "Absolute screen x (logical px) — L0 only."},
    "y": {"type": "int", "description": "Absolute screen y (logical px) — L0 only."},
    "sx": {"type": "int", "description": "Drag start x — L0 only."},
    "sy": {"type": "int", "description": "Drag start y — L0 only."},
    "tx": {"type": "int", "description": "Drag end x — L0 only."},
    "ty": {"type": "int", "description": "Drag end y — L0 only."},
    "target_x": {"type": "int", "description": "Absolute canvas x (logical px)."},
    "target_y": {"type": "int", "description": "Absolute canvas y (logical px)."},
}

# Spec used when a param name is unknown to PARAM_SPECS and the tool gives no
# override — keeps rendering total so a new param never crashes the prompt.
_FALLBACK: Dict[str, Any] = {
    "type": "string",
    "description": "(no spec — pass a literal value)",
}


# ===========================================================================
# Lookup + rendering
# ===========================================================================

def spec_for(
    param_name: str,
    override: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return the merged ParamSpec for *param_name*.

    A per-tool *override* (``ToolNode.param_specs``) is layered on top of the
    central :data:`PARAM_SPECS` entry; keys present in the override win. Always
    returns a dict (never ``None``) so callers can render unconditionally.
    """
    base = dict(PARAM_SPECS.get(param_name, _FALLBACK))
    if override and param_name in override:
        base.update(override[param_name])
    return base


def format_param(
    param_name: str,
    override: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    """Render one param as ``name:type`` (with ``∈{enum}`` when constrained).

    Used inline in the Planner's tool table. Longer descriptions live in the
    prompt's "how to fill parameters" section, keyed by type.
    """
    s = spec_for(param_name, override)
    seg = f"{param_name}:{s.get('type', 'string')}"
    enum = s.get("enum")
    if enum:
        seg += "∈{" + "|".join(str(v) for v in enum) + "}"
    return seg
