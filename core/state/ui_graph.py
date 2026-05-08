"""
UI graph persistence.

Phase 0: load/save the current state file (schema preserved from prior
``exploration/icons.json``). Phase 1 will introduce a generic schema
(regions / elements / relations).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from core import config


def save_ui_state(icons: List[Dict[str, Any]]) -> str:
    """
    Persist a list of detected+labeled icons as the UI state file.
    Returns the output file path.
    """
    out_path = config.ui_graph_path()

    ui_elements = {}
    seen: Dict[str, int] = {}
    for icon in icons:
        base = icon.get("label", f"icon_{icon['x']}_{icon['y']}")
        if not base.endswith("_Tool"):
            base = f"{base}_Tool"
        if base in seen:
            seen[base] += 1
            name = f"{base}_{seen[base]}"
        else:
            seen[base] = 0
            name = base
        ui_elements[name] = {
            "x": icon["x"], "y": icon["y"],
            "w": icon["w"], "h": icon["h"],
        }

    with open(out_path, "w") as f:
        json.dump({"ui_elements": ui_elements}, f, indent=2)

    print(f"[STATE] Wrote {len(ui_elements)} elements → {out_path}")
    return out_path


def load_ui_state() -> Dict[str, Any]:
    """Direct passthrough to ``config.load_ui_state()`` for convenience."""
    return config.load_ui_state()
