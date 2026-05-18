from __future__ import annotations

import unittest

from core.perception.tracker import CanvasTracker


class CanvasTrackerTest(unittest.TestCase):
    def test_same_rectangle_keeps_id(self) -> None:
        tracker = CanvasTracker()

        first = tracker.update([_node(100, 100)], step=1)
        second = tracker.update([_node(102, 101)], step=2)

        self.assertEqual(first[0]["id"], "Observed_Node_1")
        self.assertEqual(second[0]["id"], "Observed_Node_1")
        self.assertEqual(second[0]["track_status"], "matched")

    def test_moved_rectangle_keeps_id_and_records_motion(self) -> None:
        tracker = CanvasTracker()

        tracker.update([_node(100, 100)], step=1)
        moved = tracker.update([_node(260, 100)], step=2)

        self.assertEqual(moved[0]["id"], "Observed_Node_1")
        self.assertEqual(moved[0]["motion_from"]["x"], 100)
        self.assertGreater(moved[0]["x"], moved[0]["motion_from"]["x"])

    def test_deleted_rectangle_is_reported(self) -> None:
        tracker = CanvasTracker()

        tracker.update([_node(100, 100)], step=1)
        current = tracker.update([], step=2)

        self.assertEqual(current, [])
        self.assertEqual(
            tracker.last_diagnostics["deleted_tracks"][0]["track_id"],
            "Observed_Node_1",
        )

    def test_new_second_rectangle_does_not_rename_first(self) -> None:
        tracker = CanvasTracker()

        tracker.update([_node(100, 100)], step=1)
        current = tracker.update([_node(102, 101), _node(300, 100)], step=2)

        self.assertEqual(
            sorted(n["id"] for n in current),
            ["Observed_Node_1", "Observed_Node_2"],
        )


def _node(x: int, y: int) -> dict:
    return {
        "id": "Raw_Node_1",
        "raw_detection_id": "Raw_Node_1",
        "x": x,
        "y": y,
        "w": 120,
        "h": 60,
        "confidence": 0.8,
        "source": "test",
    }


if __name__ == "__main__":
    unittest.main()
