"""Chrome DevTools Protocol target implementation."""

from __future__ import annotations

import base64
import json
import os
import struct
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from core import config
from core.target.base import CaptureController, InputController


class ChromeCdpController(CaptureController, InputController):
    name = "chrome_cdp"

    def __init__(self) -> None:
        self._tab: Optional[Dict[str, Any]] = None
        self._msg_id = 0
        self._last_screenshot_scale = 1.0

    @property
    def _json_url(self) -> str:
        return f"http://127.0.0.1:{config.target_config().debug_port}/json"

    def _tabs(self) -> List[Dict[str, Any]]:
        with urllib.request.urlopen(self._json_url, timeout=2.0) as resp:
            data = resp.read().decode("utf-8")
        tabs = json.loads(data)
        return [t for t in tabs if t.get("type") == "page"]

    def _find_tab(self) -> Optional[Dict[str, Any]]:
        matches = [m.lower() for m in config.target_config().url_match]
        for tab in self._tabs():
            haystack = f"{tab.get('url', '')} {tab.get('title', '')}".lower()
            if any(m in haystack for m in matches):
                return tab
        return None

    def refresh(self) -> Dict[str, Any]:
        self._tab = self._find_tab()
        return self.status()

    def _target_tab(self) -> Dict[str, Any]:
        if not self._tab:
            self._tab = self._find_tab()
        if not self._tab:
            raise RuntimeError("No Chrome tab matching draw.io target was found")
        return self._tab

    def _call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            import websocket
        except ImportError as e:
            raise RuntimeError(
                "Chrome CDP target requires the 'websocket-client' package"
            ) from e
        tab = self._target_tab()
        url = tab.get("webSocketDebuggerUrl")
        if not url:
            raise RuntimeError("Matched Chrome tab has no webSocketDebuggerUrl")
        self._msg_id += 1
        payload = {"id": self._msg_id, "method": method, "params": params or {}}
        # Chrome rejects CDP WebSocket connections from unapproved origins in
        # newer versions. websocket-client sends an Origin header by default;
        # suppress it so local backend access works without requiring
        # --remote-allow-origins on Chrome.
        ws = websocket.create_connection(url, timeout=5, suppress_origin=True)
        try:
            ws.send(json.dumps(payload))
            while True:
                raw = ws.recv()
                data = json.loads(raw)
                if data.get("id") == self._msg_id:
                    if "error" in data:
                        raise RuntimeError(f"CDP {method} failed: {data['error']}")
                    return data.get("result", {})
        finally:
            ws.close()

    def _call_many(self, calls: List[Tuple[str, Dict[str, Any]]]) -> None:
        """Send several CDP commands over one WebSocket connection."""
        try:
            import websocket
        except ImportError as e:
            raise RuntimeError(
                "Chrome CDP target requires the 'websocket-client' package"
            ) from e
        tab = self._target_tab()
        url = tab.get("webSocketDebuggerUrl")
        if not url:
            raise RuntimeError("Matched Chrome tab has no webSocketDebuggerUrl")
        ws = websocket.create_connection(url, timeout=10, suppress_origin=True)
        try:
            for method, params in calls:
                self._msg_id += 1
                msg_id = self._msg_id
                ws.send(json.dumps({
                    "id": msg_id,
                    "method": method,
                    "params": params,
                }))
                while True:
                    raw = ws.recv()
                    data = json.loads(raw)
                    if data.get("id") == msg_id:
                        if "error" in data:
                            raise RuntimeError(f"CDP {method} failed: {data['error']}")
                        break
        finally:
            ws.close()

    def screenshot(self, path: str) -> str:
        self._call("Page.enable")
        metrics = self._call("Page.getLayoutMetrics")
        result = self._call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
        image = base64.b64decode(result["data"])
        with open(path, "wb") as f:
            f.write(image)
        self._last_screenshot_scale = self._measure_screenshot_scale(image, metrics)
        return os.path.abspath(path)

    def screenshot_scale(self) -> float:
        return self._last_screenshot_scale

    @staticmethod
    def _png_size(image: bytes) -> Tuple[int, int]:
        if len(image) < 24 or image[:8] != b"\x89PNG\r\n\x1a\n":
            return 0, 0
        return struct.unpack(">II", image[16:24])

    def _measure_screenshot_scale(self, image: bytes, metrics: Dict[str, Any]) -> float:
        """Return PNG pixels per CDP input coordinate.

        CDP mouse input uses CSS viewport coordinates. Depending on Chrome,
        device scale, and capture options, Page.captureScreenshot may return
        either CSS-sized or device-pixel-sized images. Measuring the saved PNG
        against Page.getLayoutMetrics keeps perception output in the same
        coordinate space as Input.dispatchMouseEvent.
        """
        img_w, img_h = self._png_size(image)
        viewport = metrics.get("layoutViewport") or metrics.get("visualViewport") or {}
        css_w = float(viewport.get("clientWidth") or viewport.get("width") or 0)
        css_h = float(viewport.get("clientHeight") or viewport.get("height") or 0)
        scales = []
        if img_w > 0 and css_w > 0:
            scales.append(img_w / css_w)
        if img_h > 0 and css_h > 0:
            scales.append(img_h / css_h)
        if not scales:
            return 1.0
        # Width can be affected by scrollbars and fractional viewport metrics;
        # averaging both axes is more stable than trusting either one alone.
        return max(0.1, sum(scales) / len(scales))

    def status(self) -> Dict[str, Any]:
        try:
            tab = self._target_tab()
            metrics: Dict[str, Any] = {}
            try:
                metrics = self._call("Page.getLayoutMetrics")
            except Exception:
                metrics = {}
            viewport = metrics.get("layoutViewport") or {}
            return {
                "backend": self.name,
                "connected": True,
                "title": tab.get("title"),
                "url": tab.get("url"),
                "screen_scale": self._last_screenshot_scale,
                "viewport": {
                    "width": viewport.get("clientWidth"),
                    "height": viewport.get("clientHeight"),
                },
            }
        except Exception as e:
            return {"backend": self.name, "connected": False, "error": str(e)}

    def map_point(self, x: int, y: int) -> Tuple[int, int]:
        return x, y

    def move_to(self, x: int, y: int) -> None:
        x, y = self.map_point(x, y)
        self._call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})

    def click_at(self, x: int, y: int, clicks: int = 1, hold: float = 0.08) -> None:
        x, y = self.map_point(x, y)
        for i in range(clicks):
            self._call("Input.dispatchMouseEvent", {
                "type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": i + 1,
            })
            time.sleep(hold)
            self._call("Input.dispatchMouseEvent", {
                "type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": i + 1,
            })
            if i + 1 < clicks:
                time.sleep(0.08)

    def drag(self, sx: int, sy: int, tx: int, ty: int, duration: Optional[float] = None,
             hold_pre: float = 0.1) -> None:
        sx, sy = self.map_point(sx, sy)
        tx, ty = self.map_point(tx, ty)
        duration = duration if duration is not None else config.drag_duration()
        calls: List[Tuple[str, Dict[str, Any]]] = [
            ("Input.dispatchMouseEvent", {
                "type": "mouseMoved", "x": sx, "y": sy,
            }),
            ("Input.dispatchMouseEvent", {
                "type": "mousePressed", "x": sx, "y": sy,
                "button": "left", "clickCount": 1,
            }),
        ]
        time.sleep(hold_pre)
        steps = max(1, min(8, int(duration / 0.08) or 1))
        for i in range(1, steps + 1):
            x = sx + (tx - sx) * i / steps
            y = sy + (ty - sy) * i / steps
            calls.append(("Input.dispatchMouseEvent", {
                "type": "mouseMoved", "x": x, "y": y,
                "button": "left", "buttons": 1,
            }))
        calls.append(("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": tx, "y": ty,
            "button": "left", "clickCount": 1,
        }))
        self._call_many(calls)

    def press(self, key: str) -> None:
        self.hotkey(key)

    def hotkey(self, *keys: str) -> None:
        text_keys = [k for k in keys if len(k) == 1]
        modifiers = 0
        if any(k in {"ctrl", "control"} for k in keys):
            modifiers |= 2
        if any(k in {"alt", "option"} for k in keys):
            modifiers |= 1
        if any(k in {"shift"} for k in keys):
            modifiers |= 8
        if any(k in {"cmd", "command", "meta"} for k in keys):
            modifiers |= 4
        key = text_keys[-1] if text_keys else keys[-1]
        code = key.upper() if len(key) == 1 else key
        self._call("Input.dispatchKeyEvent", {
            "type": "keyDown", "key": key, "code": code, "modifiers": modifiers,
        })
        self._call("Input.dispatchKeyEvent", {
            "type": "keyUp", "key": key, "code": code, "modifiers": modifiers,
        })

    def write(self, text: str, interval: Optional[float] = None) -> None:
        delay = interval if interval is not None else config.type_interval()
        for ch in text:
            self._call("Input.insertText", {"text": ch})
            if delay:
                time.sleep(delay)
