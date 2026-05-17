from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import cv2
import numpy as np

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
sys.modules.setdefault("ollama", types.SimpleNamespace(
    chat=lambda *args, **kwargs: None,
))

from core.pipeline import run


class PipelineRescanTest(unittest.TestCase):
    def test_request_rescan_uses_fresh_canvas_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty = os.path.join(tmp, "empty.png")
            rect = os.path.join(tmp, "rect.png")
            _write_canvas(empty)
            img = _write_canvas(rect)
            cv2.rectangle(img, (120, 90), (300, 170), (40, 40, 40), 2)
            cv2.imwrite(rect, img)

            observed_counts = []

            def fake_infer(task, ui_graph, screenshot_path, history=None):
                observed_counts.append(len(ui_graph["Canvas_Nodes"]))
                if len(observed_counts) == 1:
                    return {"reasoning": "need fresh screen", "tool": "request_rescan", "params": {}}
                return {"reasoning": "done", "tool": "task_complete", "params": {}}

            with patch("core.pipeline.screenshot", side_effect=[empty, rect]):
                with patch("core.pipeline.infer", side_effect=fake_infer):
                    with patch("core.perception.canvas.config.canvas_region",
                               return_value=(0, 0, 500, 300)):
                        log = run("test", ui_graph={"UI_Elements": {}, "Canvas_Edges": []}, dry_run=True)

        self.assertEqual(observed_counts, [0, 1])
        self.assertEqual([entry["tool"] for entry in log], ["request_rescan", "task_complete"])


def _write_canvas(path: str) -> np.ndarray:
    img = np.full((300, 500, 3), 255, dtype=np.uint8)
    cv2.imwrite(path, img)
    return img


if __name__ == "__main__":
    unittest.main()
