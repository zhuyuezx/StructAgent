"""
Label — VLM-based labeling for detected icons/regions.

Sends per-element image crops to a vision LLM and tags each with a short
shape/role label.

The labeling prompt is domain-specific.  Pass ``label_prompt`` explicitly, or
let the caller load it from the active domain's ``perception.LABEL_PROMPT``.
A generic fallback is used when no prompt is supplied.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import cv2

from core import config
from core import llm

logger = logging.getLogger(__name__)


_GENERIC_LABEL_PROMPT = (
    "What UI element or icon is shown in this image? "
    "Reply with ONLY a short label — one or two words, underscores for spaces, "
    "no punctuation (e.g. Rectangle, Toggle_Button, Text_Field)."
)


# ---------------------------------------------------------------------------
# LLM labeling
# ---------------------------------------------------------------------------

def label_icons(
    screenshot_path: str,
    icons: List[Dict[str, Any]],
    *,
    label_prompt: Optional[str] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
    scale: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Send each cropped icon to the VLM to identify its type.

    Parameters
    ----------
    screenshot_path:
        Full-screen (or region) capture from which icon crops are extracted.
    icons:
        Each dict must have ``x, y, w, h`` in target input coordinates.
        An optional ``_px`` key provides physical-pixel equivalents; when absent
        the input coords are scaled by ``scale`` or ``config.screen_scale()``.
    label_prompt:
        Domain-specific VLM prompt.  Defaults to a generic fallback.
        Load from ``domains.<name>.perception.LABEL_PROMPT`` for best results.

    Uses the configured provider with a real timeout so hung requests are
    cancelled when the backend supports it.
    """
    img = cv2.imread(screenshot_path)
    explorer_cfg = config.explorer_model_config()
    model = explorer_cfg.model
    scale = float(scale if scale is not None else config.screen_scale())
    timeout = timeout or explorer_cfg.timeout or config.label_timeout()
    max_retries = max_retries or config.label_max_retries()
    prompt = label_prompt or _GENERIC_LABEL_PROMPT

    labeled = []
    total = len(icons)
    skipped = 0

    logger.info("  Model: %s  |  Timeout: %ss  |  Max retries: %d", model, timeout, max_retries)

    for i, icon in enumerate(icons):
        p = icon.get("_px", {
            "x": round(icon["x"] * scale), "y": round(icon["y"] * scale),
            "w": round(icon["w"] * scale), "h": round(icon["h"] * scale),
        })
        pad = 5
        ry1 = max(0, p["y"] - p["h"] // 2 - pad)
        ry2 = min(img.shape[0], p["y"] + p["h"] // 2 + pad)
        rx1 = max(0, p["x"] - p["w"] // 2 - pad)
        rx2 = min(img.shape[1], p["x"] + p["w"] // 2 + pad)
        crop = img[ry1:ry2, rx1:rx2]

        _, buf = cv2.imencode(".png", crop)
        img_bytes = buf.tobytes()

        messages = [{"role": "user", "content": prompt}]

        label = None
        for attempt in range(1, max_retries + 1):
            try:
                import os
                import tempfile
                fd, crop_path = tempfile.mkstemp(suffix=".png")
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(img_bytes)
                    resp = llm.chat(
                        purpose="explorer",
                        messages=messages,
                        images=[crop_path],
                        timeout=timeout,
                    )
                finally:
                    try:
                        os.unlink(crop_path)
                    except OSError:
                        pass
                raw = resp.content.strip().split("\n")[0]
                label = raw.strip(".,!\"'` ").replace(" ", "_")
                break
            except TimeoutError:
                logger.warning("  Icon %2d: ⏱ timeout (%ss) — "
                               "retry %d/%d", i, timeout, attempt, max_retries)
            except Exception as e:
                err = str(e)[:60]
                logger.warning("  Icon %2d: ❌ %s — retry %d/%d", i, err, attempt, max_retries)

        if label is None:
            label = "unknown"
            skipped += 1
            logger.info("  Icon %2d: (%3d, %3d) → "
                        "⚠️ SKIPPED (max retries exceeded)", i, icon['x'], icon['y'])
        else:
            logger.info("  Icon %2d: (%3d, %3d) → %s", i, icon['x'], icon['y'], label)

        labeled.append({**icon, "label": label})

    if skipped:
        logger.warning("⚠️  %d/%d icons skipped (labeled 'unknown')", skipped, total)

    return labeled
