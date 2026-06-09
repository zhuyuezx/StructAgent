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
import re
from typing import Any, Dict, Optional

from core import config
from core import llm
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


def _infer_passed_from_text(text: str) -> Optional[bool]:
    """Best-effort repair for small local models that omit ``passed``."""
    t = text.lower()
    negative = [
        "not satisfied", "does not satisfy", "doesn't satisfy",
        "not visible", "cannot see", "can't see", "missing",
        "incorrect", "wrong", "empty", "ambiguous", "not placed",
        "no second", "no rectangle", "no shape", "only a single",
        "only one", "only 1", "there is no",
    ]
    positive = [
        "satisfies", "satisfied", "clearly shows", "is visible",
        "has been placed", "placed on", "matches the expectation",
        "directly satisfies",
    ]
    if any(p in t for p in negative):
        return False
    if any(p in t for p in positive):
        return True
    match = re.search(r"\bpassed?\s*[:=]\s*(true|false|yes|no)\b", t)
    if match:
        return match.group(1) in {"true", "yes"}
    return None


def _coerce_passed(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "yes", "pass", "passed"}:
            return True
        if v in {"false", "no", "fail", "failed"}:
            return False
    return None


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
    critic_cfg = config.critic_model_config()
    model = model or critic_cfg.model
    timeout = timeout or critic_cfg.timeout or config.critic_timeout()

    try:
        with open(screenshot_path, "rb"):
            pass
    except OSError as e:
        return {"passed": False, "reasoning": f"could not read screenshot: {e}",
                "model": model}

    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user",
         "content": _build_user_content(description, scene_hint)},
    ]

    logger.info("Critic verifying with %s: %r", model, description[:80])
    try:
        resp = llm.chat(
            purpose="critic",
            messages=messages,
            images=[screenshot_path],
            response_format="json_object",
            timeout=timeout,
        )
        raw = resp.content
    except Exception as e:  # pragma: no cover - network/model dependent
        return {"passed": False, "reasoning": f"critic call failed: {e}",
                "model": model}

    try:
        parsed = extract_json(raw)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        reasoning = str(parsed.get("reasoning", "")).strip()
        if "passed" in parsed:
            passed = _coerce_passed(parsed.get("passed"))
            if passed is None:
                passed = _infer_passed_from_text(str(parsed.get("passed")) + " " + reasoning)
            if passed is None:
                passed = False
            return {
                "passed": passed,
                "reasoning": reasoning,
                "model": model,
            }
        inferred = _infer_passed_from_text(reasoning or raw)
        if inferred is not None:
            return {
                "passed": inferred,
                "reasoning": reasoning or "critic omitted passed; inferred from reply",
                "model": model,
            }

    inferred = _infer_passed_from_text(raw)
    if inferred is not None:
        return {
            "passed": inferred,
            "reasoning": "critic omitted strict JSON; inferred from reply: " + raw[:180],
            "model": model,
        }
    return {"passed": False,
            "reasoning": f"could not parse critic reply: {raw[:200]!r}",
            "model": model}
