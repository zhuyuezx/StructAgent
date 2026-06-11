"""Abstract target interfaces."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


class CaptureController:
    name = "base"

    def screenshot(self, path: str) -> str:
        raise NotImplementedError

    def status(self) -> Dict[str, Any]:
        return {"backend": self.name, "connected": False}

    def refresh(self) -> Dict[str, Any]:
        return self.status()

    def screenshot_scale(self) -> float:
        """Screenshot pixels per input-coordinate point."""
        return 1.0

    def canvas_center(self) -> Tuple[int, int]:
        """Best known center of the interactive canvas/input area."""
        return (0, 0)


class InputController:
    name = "base"

    def map_point(self, x: int, y: int) -> Tuple[int, int]:
        return x, y

    def move_to(self, x: int, y: int) -> None:
        raise NotImplementedError

    def click_at(self, x: int, y: int, clicks: int = 1, hold: float = 0.08) -> None:
        raise NotImplementedError

    def drag(self, sx: int, sy: int, tx: int, ty: int, duration: Optional[float] = None,
             hold_pre: float = 0.1) -> None:
        raise NotImplementedError

    def drag_path(self, points: List[Tuple[int, int]], duration: Optional[float] = None,
                  hold_pre: float = 0.1) -> None:
        if len(points) < 2:
            return
        sx, sy = points[0]
        tx, ty = points[-1]
        self.drag(sx, sy, tx, ty, duration=duration, hold_pre=hold_pre)

    def press(self, key: str) -> None:
        raise NotImplementedError

    def hotkey(self, *keys: str) -> None:
        raise NotImplementedError

    def write(self, text: str, interval: Optional[float] = None) -> None:
        raise NotImplementedError
