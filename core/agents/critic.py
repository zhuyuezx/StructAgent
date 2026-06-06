"""
Critic — vision-based checkpoint verification (Phase 3).

The orchestrator pauses at every checkpoint, captures a screenshot, and asks:
*does the canvas actually look the way this step intended?* That question is
answered here, by a **vision model** looking at the screenshot — NOT by the
scene graph.

Why not the scene graph? The scene graph only reflects mutations the framework
itself performed. The moment the real UI drifts from it — a drag that didn't
land, a dialog that stole focus, the user nudging a shape by hand — the graph
silently lies. A screenshot is the ground truth a human would trust, so the
critic (and the human, in manual mode) judge from the pixels.

:func:`verify` returns ``{"passed": bool, "reasoning": str}``; the caller
(``/api/critic``) only continues the plan when ``passed`` is true.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from core import config
from core.agents._common import extract_json

logger = logging.getLogger(__name__)


_SYSTEM = """You are a meticulous visual QA critic for a draw.io automation agent.

You are given:
  - a SCREENSHOT of the draw.io canvas captured right after an automation step, and
  - an EXPECTATION describing, in plain language, what should now be true.

Judge ONLY from what is visible in the screenshot whether the EXPECTATION is
satisfied. Do not assume anything you cannot see. Be strict: if the canvas is
ambiguous, partially correct, empty, or shows an unexpected dialog/state, the
expectation is NOT satisfied.

Reply with STRICT JSON and nothing else:
  {"passed": true|false, "reasoning": "<one or two sentences citing what you see>"}"""


def _build_user_content(description: str, scene_hint: Optional[str]) -> str:
    parts = [f"EXPECTATION:\n{description.strip() or '(no description provided)'}"]
    if scene_hint:
        # Supplied only as a weak hint; the screenshot remains authoritative.
        parts.append(
            "\nFor context only (the framework's symbolic model — may be stale, "
            "trust the screenshot over this):\n" + scene_hint
        )
    parts.append("\nDoes the screenshot satisfy the EXPECTATION? Reply with JSON only.")
    return "\n".join(parts)


def verify(
    screenshot_path: str,
    description: str,
    *,
    scene_hint: Optional[str] = None,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Ask the vision model whether *screenshot_path* satisfies *description*.

    Parameters
    ----------
    screenshot_path:
        Path to the checkpoint PNG to inspect.
    description:
        The checkpoint's natural-language expectation.
    scene_hint:
        Optional scene-graph summary passed as weak context (never the gate).
    model / timeout:
        Overrides; default to :func:`core.config.critic_model` /
        :func:`core.config.critic_timeout`.

    Returns
    -------
    ``{"passed": bool, "reasoning": str, "model": str}``. On any error
    (unreadable image, model/parse failure) returns ``passed=False`` with the
    reason, so the caller fails safe and the user can verify manually.
    """
    import httpx
    import ollama

    model = model or config.critic_model()
    timeout = timeout or config.critic_timeout()

    try:
        with open(screenshot_path, "rb") as f:
            img_bytes = f.read()
    except OSError as e:
        return {"passed": False, "reasoning": f"could not read screenshot: {e}",
                "model": model}

    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user",
         "content": _build_user_content(description, scene_hint),
         "images": [img_bytes]},
    ]

    logger.info("Critic verifying with %s: %r", model, description[:80])
    client = ollama.Client(timeout=httpx.Timeout(timeout, connect=10.0))
    try:
        resp = client.chat(model=model, messages=messages)
        raw = resp["message"]["content"]
    except Exception as e:  # pragma: no cover - network/model dependent
        return {"passed": False, "reasoning": f"critic call failed: {e}",
                "model": model}

    try:
        parsed = extract_json(raw)
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict) or "passed" not in parsed:
        return {"passed": False,
                "reasoning": f"could not parse critic reply: {raw[:200]!r}",
                "model": model}

    return {
        "passed": bool(parsed.get("passed")),
        "reasoning": str(parsed.get("reasoning", "")).strip(),
        "model": model,
    }
