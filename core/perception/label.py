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
import re
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

_DRAWIO_LABELS = {
    "Rectangle",
    "Rounded_Rectangle",
    "Ellipse",
    "Circle",
    "Diamond",
    "Triangle",
    "Arrow",
    "Text",
    "Cylinder",
    "Cloud",
    "Hexagon",
    "Parallelogram",
    "Table",
    "Box",
    "Wave",
    "Document",
    "Person",
    "Speech_Bubble",
}

_LABEL_ALIASES = {
    "roundedrectangle": "Rounded_Rectangle",
    "rounded_rect": "Rounded_Rectangle",
    "round_rectangle": "Rounded_Rectangle",
    "oval": "Ellipse",
    "rhombus": "Diamond",
    "database": "Cylinder",
    "data_store": "Cylinder",
    "speechbubble": "Speech_Bubble",
    "speech_balloon": "Speech_Bubble",
    "callout": "Speech_Bubble",
    "actor": "Person",
}

_BAD_PREFIXES = (
    "the_user_wants",
    "i_need",
    "i_should",
    "this_image",
    "the_image",
    "it_looks",
    "it_seems",
    "based_on",
)


def _normalize_label_token(text: str) -> str:
    token = text.strip().strip(".,:;!?\"'`[](){}")
    token = re.sub(r"[\s\-]+", "_", token)
    token = re.sub(r"[^A-Za-z0-9_]", "", token)
    token = re.sub(r"_+", "_", token).strip("_")
    return token


def _canonical_label(token: str) -> Optional[str]:
    if not token:
        return None
    compact = token.lower().replace("_", "")
    alias_key = token.lower()
    if alias_key in _LABEL_ALIASES:
        return _LABEL_ALIASES[alias_key]
    if compact in _LABEL_ALIASES:
        return _LABEL_ALIASES[compact]
    for label in _DRAWIO_LABELS:
        if compact == label.lower().replace("_", ""):
            return label
    return None


def _parse_label_response(raw: str) -> Optional[str]:
    """Extract one usable icon label from a VLM response."""
    text = re.sub(r"<think>.*?</think>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    text = text.strip()
    if not text:
        return None

    first_line = text.splitlines()[0]
    direct = _normalize_label_token(first_line)
    direct_word_count = len(re.findall(r"[A-Za-z][A-Za-z0-9_-]*", first_line))
    if direct.lower().startswith(_BAD_PREFIXES) or len(direct) > 40 or direct_word_count > 2:
        direct = ""
    canonical = _canonical_label(direct)
    if canonical:
        return canonical
    if direct and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", direct):
        return direct

    for match in re.finditer(r"[A-Za-z][A-Za-z0-9_\- ]{1,40}", text):
        candidate = _normalize_label_token(match.group(0))
        canonical = _canonical_label(candidate)
        if canonical:
            return canonical
    words = [_normalize_label_token(w) for w in re.findall(r"[A-Za-z][A-Za-z0-9_-]*", text)]
    for size in (2, 1):
        for i in range(0, max(0, len(words) - size + 1)):
            candidate = "_".join(w for w in words[i:i + size] if w)
            canonical = _canonical_label(candidate)
            if canonical:
                return canonical
    return None

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

        label = None
        for attempt in range(1, max_retries + 1):
            try:
                strict_prompt = (
                    f"{prompt}\n\n"
                    "Return exactly ONE label token and nothing else. "
                    "Do not explain. Do not mention the user or your reasoning."
                )
                if attempt > 1:
                    strict_prompt += (
                        "\nYour previous answer was not a valid label. "
                        "Answer with one shape name only."
                    )
                messages = [{"role": "user", "content": strict_prompt}]
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
                raw = resp.content.strip()
                label = _parse_label_response(raw)
                if label is None:
                    raise ValueError(f"invalid label response: {raw[:120]!r}")
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
