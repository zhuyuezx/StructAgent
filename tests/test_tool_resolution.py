import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.tools.registry import resolve_tool


def test_resolve_tool_accepts_legacy_numbered_shape_alias():
    ui_graph = {
        "UI_Elements": {
            "Rectangle_Tool": {"x": 36, "y": 290, "w": 30, "h": 16},
        }
    }

    assert resolve_tool(ui_graph, "Rectangle_Tool") == (36, 290)
    assert resolve_tool(ui_graph, "Rectangle1_Tool") == (36, 290)
    assert resolve_tool(ui_graph, " Rectangle1_Tool ") == (36, 290)
