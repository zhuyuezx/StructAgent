"""PyAutoGUI target implementation."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

import pyautogui

from core import config
from core.target.base import CaptureController, InputController


class PyAutoGuiController(CaptureController, InputController):
    name = "pyautogui"

    def screenshot(self, path: str) -> str:
        pyautogui.screenshot().save(path)
        return os.path.abspath(path)

    def status(self) -> Dict[str, Any]:
        return {
            "backend": self.name,
            "connected": True,
            "mode": "full_screen",
            "screen_scale": float(config.screen_scale()),
            "canvas_center": list(self.canvas_center()),
        }

    def screenshot_scale(self) -> float:
        return float(config.screen_scale())

    def canvas_center(self) -> tuple[int, int]:
        return config.empty_canvas_point()

    def move_to(self, x: int, y: int) -> None:
        pyautogui.moveTo(x, y)

    def click_at(self, x: int, y: int, clicks: int = 1, hold: float = 0.08) -> None:
        pyautogui.moveTo(x, y)
        time.sleep(0.05)
        for i in range(clicks):
            pyautogui.mouseDown()
            time.sleep(hold)
            pyautogui.mouseUp()
            if i + 1 < clicks:
                time.sleep(0.08)

    def drag(self, sx: int, sy: int, tx: int, ty: int, duration: Optional[float] = None,
             hold_pre: float = 0.1) -> None:
        if duration is None:
            duration = config.drag_duration()
        pyautogui.moveTo(sx, sy)
        time.sleep(0.05)
        pyautogui.mouseDown()
        time.sleep(hold_pre)
        pyautogui.moveTo(tx, ty, duration=duration)
        pyautogui.mouseUp()

    def drag_path(self, points: List[Tuple[int, int]], duration: Optional[float] = None,
                  hold_pre: float = 0.1) -> None:
        if len(points) < 2:
            return
        if duration is None:
            duration = config.drag_duration()
        per_leg = duration / max(1, len(points) - 1)
        pyautogui.moveTo(*points[0])
        time.sleep(0.05)
        pyautogui.mouseDown()
        time.sleep(hold_pre)
        for x, y in points[1:]:
            pyautogui.moveTo(x, y, duration=per_leg)
        pyautogui.mouseUp()

    def press(self, key: str) -> None:
        pyautogui.hotkey(key)

    def hotkey(self, *keys: str) -> None:
        pyautogui.hotkey(*keys)

    def write(self, text: str, interval: Optional[float] = None) -> None:
        pyautogui.write(text, interval=interval if interval is not None else config.type_interval())
