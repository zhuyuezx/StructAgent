from __future__ import annotations

import os
import tempfile
import unittest

import cv2
import numpy as np

from core.perception.canvas import observe_canvas


class CanvasPerceptionTest(unittest.TestCase):
    def test_empty_canvas_returns_no_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "empty.png")
            _write_canvas(path)

            nodes = observe_canvas(path, region=(0, 0, 500, 300))

        self.assertEqual(nodes, [])

    def test_rectangle_canvas_returns_one_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rectangle.png")
            img = _write_canvas(path)
            cv2.rectangle(img, (120, 90), (300, 170), (40, 40, 40), 2)
            cv2.imwrite(path, img)

            nodes = observe_canvas(path, region=(0, 0, 500, 300))

        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["id"], "Observed_Node_1")
        self.assertGreater(nodes[0]["confidence"], 0)


def _write_canvas(path: str) -> np.ndarray:
    img = np.full((300, 500, 3), 255, dtype=np.uint8)
    cv2.imwrite(path, img)
    return img


if __name__ == "__main__":
    unittest.main()
