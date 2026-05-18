from __future__ import annotations

import os
import tempfile
import unittest

import cv2
import numpy as np

from core.perception.canvas import annotate_canvas, observe_canvas


class CanvasPerceptionTest(unittest.TestCase):
    def test_empty_canvas_returns_no_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "empty.png")
            _write_grid_canvas(path)

            nodes = observe_canvas(path, region=(0, 0, 500, 300))

        self.assertEqual(nodes, [])

    def test_rectangle_canvas_returns_one_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rectangle.png")
            img = _write_grid_canvas(path)
            cv2.rectangle(img, (120, 90), (300, 170), (40, 40, 40), 2)
            cv2.imwrite(path, img)

            nodes = observe_canvas(path, region=(0, 0, 500, 300))

        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["id"], "Observed_Node_1")
        self.assertGreater(nodes[0]["confidence"], 0)

    def test_dark_empty_canvas_returns_no_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dark_empty.png")
            _write_dark_grid_canvas(path)

            nodes = observe_canvas(path, region=(0, 0, 500, 300))

        self.assertEqual(nodes, [])

    def test_dark_rectangle_canvas_returns_one_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dark_rectangle.png")
            img = _write_dark_grid_canvas(path)
            cv2.rectangle(img, (120, 90), (300, 170), (235, 235, 235), 2)
            cv2.imwrite(path, img)

            nodes = observe_canvas(path, region=(0, 0, 500, 300))

        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["id"], "Observed_Node_1")
        self.assertGreater(nodes[0]["confidence"], 0)

    def test_selected_rectangle_handles_still_returns_one_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "selected.png")
            img = _write_grid_canvas(path)
            cv2.rectangle(img, (120, 90), (300, 170), (40, 40, 40), 2)
            for x, y in [(120, 90), (210, 90), (300, 90), (120, 130),
                         (300, 130), (120, 170), (210, 170), (300, 170)]:
                cv2.circle(img, (x, y), 5, (230, 160, 20), -1)
            cv2.imwrite(path, img)

            nodes = observe_canvas(path, region=(0, 0, 500, 300))

        self.assertEqual(len(nodes), 1)

    def test_text_below_rectangle_does_not_create_extra_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "text_below.png")
            img = _write_grid_canvas(path)
            cv2.rectangle(img, (120, 90), (300, 170), (40, 40, 40), 2)
            cv2.putText(img, "Cache", (175, 205),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 1)
            cv2.imwrite(path, img)

            nodes = observe_canvas(path, region=(0, 0, 500, 300))

        self.assertEqual(len(nodes), 1)

    def test_annotate_canvas_writes_debug_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rectangle.png")
            out = os.path.join(tmp, "annotated.png")
            img = _write_grid_canvas(path)
            cv2.rectangle(img, (120, 90), (300, 170), (40, 40, 40), 2)
            cv2.imwrite(path, img)
            nodes = observe_canvas(path, region=(0, 0, 500, 300))

            result = annotate_canvas(path, nodes, out)

            self.assertEqual(result, out)
            self.assertTrue(os.path.exists(out))
            self.assertGreater(os.path.getsize(out), 0)


def _write_grid_canvas(path: str) -> np.ndarray:
    img = np.full((300, 500, 3), 255, dtype=np.uint8)
    for x in range(0, 500, 20):
        cv2.line(img, (x, 0), (x, 300), (232, 232, 232), 1)
    for y in range(0, 300, 20):
        cv2.line(img, (0, y), (500, y), (232, 232, 232), 1)
    cv2.imwrite(path, img)
    return img


def _write_dark_grid_canvas(path: str) -> np.ndarray:
    img = np.full((300, 500, 3), 24, dtype=np.uint8)
    for x in range(0, 500, 20):
        cv2.line(img, (x, 0), (x, 300), (48, 48, 48), 1)
    for y in range(0, 300, 20):
        cv2.line(img, (0, y), (500, y), (48, 48, 48), 1)
    cv2.imwrite(path, img)
    return img


if __name__ == "__main__":
    unittest.main()
