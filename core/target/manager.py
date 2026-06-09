"""Target controller selection and fallback."""

from __future__ import annotations

import logging
from typing import Any, Dict

from core import config
from core.target.base import CaptureController, InputController
from core.target.pyautogui_target import PyAutoGuiController

logger = logging.getLogger(__name__)

_PRIMARY: CaptureController | None = None
_FALLBACK = PyAutoGuiController()


def _build_primary() -> CaptureController:
    backend = config.target_config().backend.lower()
    if backend == "chrome_cdp":
        from core.target.chrome_cdp import ChromeCdpController
        return ChromeCdpController()
    return PyAutoGuiController()


def controller() -> CaptureController:
    global _PRIMARY
    if _PRIMARY is None:
        _PRIMARY = _build_primary()
    return _PRIMARY


def refresh() -> Dict[str, Any]:
    global _PRIMARY
    _PRIMARY = _build_primary()
    return controller().refresh()


def status() -> Dict[str, Any]:
    return controller().status()


def capture_controller() -> CaptureController:
    return controller()


def input_controller() -> InputController:
    ctrl = controller()
    if isinstance(ctrl, InputController):
        return ctrl
    return _FALLBACK


def screenshot(path: str) -> str:
    ctrl = capture_controller()
    try:
        return ctrl.screenshot(path)
    except Exception as e:
        if config.target_config().fallback == "pyautogui" and ctrl.name != "pyautogui":
            logger.warning("Target screenshot via %s failed: %s; falling back to pyautogui",
                           ctrl.name, e)
            return _FALLBACK.screenshot(path)
        raise


def screenshot_scale() -> float:
    """Screenshot pixels per input-coordinate point for the active target."""
    ctrl = capture_controller()
    try:
        return float(ctrl.screenshot_scale())
    except Exception:
        return float(config.screen_scale())
