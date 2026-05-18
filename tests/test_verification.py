from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from core.verification import verify_action


class VerificationTest(unittest.TestCase):
    def test_place_passes_when_tracked_count_increases(self) -> None:
        result = _verify(
            "place_shape",
            {},
            _graph([]),
            _graph([_node("Observed_Node_1", 100, 100)], new_tracks=["Observed_Node_1"]),
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["reason"], "observed_canvas_node_count_increased")
        self.assertEqual(result["new_tracks"], ["Observed_Node_1"])

    def test_drag_right_requires_same_node_moved_right(self) -> None:
        result = _verify(
            "move_node_to_zone_and_deselect",
            {"node_ref": "Observed_Node_1", "zone": "right"},
            _graph([_node("Observed_Node_1", 100, 100)]),
            _graph([_node("Observed_Node_1", 180, 100)]),
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["reason"], "target_node_moved_expected_direction")
        self.assertEqual(result["movement_delta"], {"dx": 80, "dy": 0})

    def test_delete_passes_when_target_disappears(self) -> None:
        result = _verify(
            "delete_node",
            {"node_ref": "Observed_Node_1"},
            _graph([_node("Observed_Node_1", 100, 100)]),
            _graph([]),
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["reason"], "target_node_disappeared_after_delete")

    def test_text_action_remains_weak(self) -> None:
        result = _verify(
            "type_label",
            {"text": "Cache"},
            _graph([_node("Observed_Node_1", 100, 100)]),
            _graph([_node("Observed_Node_1", 100, 100)]),
            changed=True,
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["confidence"], "weak")


def _verify(tool, params, before_graph, after_graph, changed=False):
    with tempfile.TemporaryDirectory() as tmp:
        before = os.path.join(tmp, "before.png")
        after = os.path.join(tmp, "after.png")
        _write_canvas(before)
        _write_canvas(after, changed=changed)
        with patch("core.verification.config.canvas_region", return_value=(0, 0, 100, 100)):
            return verify_action(
                tool,
                params,
                before_graph,
                after_graph,
                before,
                after,
                {"status": "ok"},
            )


def _graph(nodes, new_tracks=None):
    return {
        "Canvas_Nodes": nodes,
        "_canvas_tracking": {"new_tracks": new_tracks or []},
    }


def _node(node_id, x, y):
    return {"id": node_id, "x": x, "y": y, "w": 120, "h": 60, "text": ""}


def _write_canvas(path, changed=False):
    img = np.full((100, 100, 3), 255, dtype=np.uint8)
    if changed:
        cv2.rectangle(img, (10, 10), (40, 40), (0, 0, 0), 2)
    cv2.imwrite(path, img)


if __name__ == "__main__":
    unittest.main()
