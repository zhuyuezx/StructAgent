"""
UI graph persistence.

Phase 0: load/save the current state file (schema preserved from prior
``exploration/icons.json``). Phase 1 will introduce a generic schema
(regions / elements / relations).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

from core import config

logger = logging.getLogger(__name__)

# Matches the "_Tool" / "_Tool_3" suffix appended to icon labels, so we can
# recover the shape family from a stored element name.
_TOOL_SUFFIX_RE = re.compile(r"_Tool(?:_\d+)?$")


def _icon_name(label: str) -> str:
    """Canonical element/dispatch name for a shape label (``Rectangle`` →
    ``Rectangle_Tool``)."""
    base = label or "icon"
    return base if base.endswith("_Tool") else f"{base}_Tool"


def save_ui_state(icons: List[Dict[str, Any]], domain: str | None = None) -> str:
    """
    Persist a list of detected+labeled icons as the UI state file.

    Writes to the active interface's ``state/ui_graph.<domain>.json`` (or the
    one named by ``domain``), so each interface keeps its own icon set.

    One icon per shape: the vision labeler often tags several *distinct*
    sidebar cells with the same shape word (e.g. multiple cells read as
    "Rectangle"). Rather than disambiguating them with ``_1 / _2 / …`` — which
    leaves the agent with no reliable way to pick one — we keep only the
    **canonical** icon per label: the top-left-most cell (palette reading
    order), where the basic shape of each kind appears first. Returns the
    output file path.
    """
    out_path = config.ui_graph_path(domain)

    # Palette reading order (top→bottom, left→right) so the canonical (basic)
    # icon of each shape wins.
    ordered = sorted(icons, key=lambda ic: (ic["y"], ic["x"]))

    ui_elements: Dict[str, Dict[str, int]] = {}
    dropped = 0
    for icon in ordered:
        name = _icon_name(icon.get("label", f"icon_{icon['x']}_{icon['y']}"))
        if name in ui_elements:
            dropped += 1
            continue  # keep only the first (canonical) icon per shape
        ui_elements[name] = {
            "x": icon["x"], "y": icon["y"],
            "w": icon["w"], "h": icon["h"],
        }

    with open(out_path, "w") as f:
        json.dump({"ui_elements": ui_elements}, f, indent=2)

    logger.info("Wrote %d elements → %s%s", len(ui_elements), out_path,
                f" (dropped {dropped} same-shape duplicate(s))" if dropped else "")
    return out_path


def dedupe_ui_state(domain: str | None = None) -> Dict[str, int]:
    """Collapse the *already-recorded* ui_elements to one canonical icon per
    shape, applying the same rule :func:`save_ui_state` now enforces.

    For data captured before that rule existed (where duplicates were suffixed
    ``Rectangle_Tool_1 … _6``). Recovers each element's shape from its name,
    then re-saves through :func:`save_ui_state`. Operates on the active
    interface (or the one named by ``domain``). Returns
    ``{"before", "after", "dropped"}``.
    """
    elements = config.load_ui_state(domain).get("ui_elements", {})
    icons = [
        {"label": _TOOL_SUFFIX_RE.sub("", name) or name,
         "x": v["x"], "y": v["y"], "w": v["w"], "h": v["h"]}
        for name, v in elements.items()
    ]
    before = len(elements)
    save_ui_state(icons, domain)
    after = len(config.load_ui_state(domain).get("ui_elements", {}))
    return {"before": before, "after": after, "dropped": before - after}


def load_ui_state(domain: str | None = None) -> Dict[str, Any]:
    """Direct passthrough to ``config.load_ui_state()`` for convenience."""
    return config.load_ui_state(domain)
