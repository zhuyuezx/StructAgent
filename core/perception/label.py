"""
Label — VLM-based labeling for detected icons/regions.

Sends per-element image crops to a vision LLM and tags each with a short
shape/role label.
"""

from __future__ import annotations

from typing import Any, Dict, List

import cv2

from core import config


# ---------------------------------------------------------------------------
# LLM labeling
# ---------------------------------------------------------------------------

def label_icons(
    screenshot_path: str,
    icons: List[Dict[str, Any]],
    timeout: float | None = None,
    max_retries: int | None = None,
) -> List[Dict[str, Any]]:
    """
    Send each cropped icon to the VLM to identify its shape type.

    Uses ``ollama.Client`` with a real HTTP timeout so hung requests
    are actually cancelled.
    """
    import httpx
    import ollama

    img = cv2.imread(screenshot_path)
    model = config.explorer_model()
    scale = config.screen_scale()
    timeout = timeout or config.label_timeout()
    max_retries = max_retries or config.label_max_retries()

    client = ollama.Client(timeout=httpx.Timeout(timeout, connect=10.0))

    labeled = []
    total = len(icons)
    skipped = 0

    print(f"  Model: {model}  |  Timeout: {timeout}s  |  Max retries: {max_retries}")

    for i, icon in enumerate(icons):
        p = icon.get("_px", {
            "x": icon["x"] * scale, "y": icon["y"] * scale,
            "w": icon["w"] * scale, "h": icon["h"] * scale,
        })
        pad = 5
        ry1 = max(0, p["y"] - p["h"] // 2 - pad)
        ry2 = min(img.shape[0], p["y"] + p["h"] // 2 + pad)
        rx1 = max(0, p["x"] - p["w"] // 2 - pad)
        rx2 = min(img.shape[1], p["x"] + p["w"] // 2 + pad)
        crop = img[ry1:ry2, rx1:rx2]

        _, buf = cv2.imencode(".png", crop)
        img_bytes = buf.tobytes()

        messages = [{
            "role": "user",
            "content": (
                "This is a small icon from draw.io's shape sidebar. "
                "What shape does it represent? Reply with ONLY a short "
                "label like Rectangle, Ellipse, Rounded_Rectangle, Diamond, "
                "Triangle, Arrow, Text, Cylinder, Cloud, etc. "
                "One or two words, use underscores."
            ),
            "images": [img_bytes],
        }]

        label = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = client.chat(model=model, messages=messages)
                raw = resp["message"]["content"].strip().split("\n")[0]
                label = raw.strip(".,!\"'` ").replace(" ", "_")
                break
            except httpx.TimeoutException:
                print(f"  Icon {i:>2}: ⏱ timeout ({timeout}s) — "
                      f"retry {attempt}/{max_retries}")
            except Exception as e:
                err = str(e)[:60]
                print(f"  Icon {i:>2}: ❌ {err} — retry {attempt}/{max_retries}")

        if label is None:
            label = "unknown"
            skipped += 1
            print(f"  Icon {i:>2}: ({icon['x']:>3}, {icon['y']:>3}) → "
                  f"⚠️ SKIPPED (max retries exceeded)")
        else:
            print(f"  Icon {i:>2}: ({icon['x']:>3}, {icon['y']:>3}) → {label}")

        labeled.append({**icon, "label": label})

    if skipped:
        print(f"\n  ⚠️  {skipped}/{total} icons skipped (labeled 'unknown')")

    return labeled
