from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault("pyautogui", types.SimpleNamespace(
    FAILSAFE=True,
    PAUSE=0,
    click=lambda *args, **kwargs: None,
    typewrite=lambda *args, **kwargs: None,
    hotkey=lambda *args, **kwargs: None,
    moveTo=lambda *args, **kwargs: None,
    mouseDown=lambda *args, **kwargs: None,
    mouseUp=lambda *args, **kwargs: None,
    screenshot=lambda *args, **kwargs: None,
))

import domains.drawio.tools as drawio_tools
import core.tools.primitives as primitives


class DrawioCompoundToolTest(unittest.TestCase):
    def test_place_shape_then_edit_label_sequence(self) -> None:
        calls = []

        def fake(name):
            def _inner(*args, **kwargs):
                calls.append(name)
                return {"status": "ok", "tool": name}
            return _inner

        with patch.object(drawio_tools, "_fn_place_shape", fake("place_shape")):
            with patch.object(drawio_tools, "_fn_press_escape", fake("press_escape")):
                with patch.object(drawio_tools, "_fn_press_enter", fake("press_enter")):
                    with patch.object(drawio_tools, "_fn_select_all", fake("select_all")):
                        with patch.object(drawio_tools, "_fn_type_label", fake("type_label")):
                            with patch.object(drawio_tools, "_fn_click_empty_canvas",
                                              fake("click_empty_canvas")):
                                result = drawio_tools.place_shape_then_edit_label(
                                    {"UI_Elements": {}}, "Rectangle_Tool", "Cache",
                                )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(calls, [
            "place_shape",
            "press_escape",
            "press_enter",
            "select_all",
            "type_label",
            "press_escape",
            "click_empty_canvas",
        ])

    def test_drag_node_to_zone_resolves_named_zone(self) -> None:
        captured = {}

        def fake_drag(ui_graph, node_ref, target_x, target_y):
            captured["args"] = (ui_graph, node_ref, target_x, target_y)
            return {"status": "ok", "tool": "drag_node"}

        with patch.object(primitives.config, "canvas_region",
                          return_value=(100, 100, 900, 700)):
            with patch.object(primitives.config, "screen_scale", return_value=2):
                with patch.object(primitives, "_fn_drag_node", fake_drag):
                    result = primitives.drag_node_to_zone(
                        {"Canvas_Nodes": [{"id": "Observed_Node_1", "x": 50, "y": 50}]},
                        "Observed_Node_1",
                        "right",
                    )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["tool"], "drag_node_to_zone")
        self.assertEqual(result["zone"], "right")
        self.assertEqual(captured["args"][1:], ("Observed_Node_1", 350, 200))

    def test_move_node_to_zone_and_deselect_sequence(self) -> None:
        calls = []

        def fake(name):
            def _inner(*args, **kwargs):
                calls.append(name)
                return {"status": "ok", "tool": name}
            return _inner

        with patch.object(drawio_tools, "_fn_drag_node_to_zone",
                          fake("drag_node_to_zone")):
            with patch.object(drawio_tools, "_fn_click_empty_canvas",
                              fake("click_empty_canvas")):
                result = drawio_tools.move_node_to_zone_and_deselect(
                    {"Canvas_Nodes": []}, "Observed_Node_1", "right",
                )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(calls, ["drag_node_to_zone", "click_empty_canvas"])


if __name__ == "__main__":
    unittest.main()
