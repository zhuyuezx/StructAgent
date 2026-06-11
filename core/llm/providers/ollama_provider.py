"""Ollama chat provider."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.config import ModelConfig
from core.llm.types import ChatResponse


def _with_images(
    messages: List[Dict[str, Any]], images: Optional[List[str]],
) -> List[Dict[str, Any]]:
    out = [dict(m) for m in messages]
    if not images:
        return out
    if not out:
        raise ValueError("Cannot attach images without at least one message")
    payload = []
    for path in images:
        with open(path, "rb") as f:
            payload.append(f.read())
    out[-1]["images"] = payload
    return out


def chat(
    cfg: ModelConfig,
    *,
    messages: List[Dict[str, Any]],
    images: Optional[List[str]] = None,
    response_format: Optional[str] = None,
    timeout: Optional[float] = None,
) -> ChatResponse:
    import httpx
    import ollama

    request_messages = _with_images(messages, images)
    call_timeout = timeout or cfg.timeout
    if call_timeout:
        client = ollama.Client(timeout=httpx.Timeout(call_timeout, connect=10.0))
        resp = client.chat(model=cfg.model, messages=request_messages)
    else:
        resp = ollama.chat(model=cfg.model, messages=request_messages)
    usage = None
    try:
        prompt = resp.get("prompt_eval_count")
        completion = resp.get("eval_count")
    except AttributeError:  # ollama may return a pydantic object
        prompt = getattr(resp, "prompt_eval_count", None)
        completion = getattr(resp, "eval_count", None)
    if isinstance(prompt, int) or isinstance(completion, int):
        usage = {
            "prompt_tokens": int(prompt or 0),
            "completion_tokens": int(completion or 0),
            "total_tokens": int(prompt or 0) + int(completion or 0),
        }
    return ChatResponse(
        content=resp["message"]["content"],
        model=cfg.model,
        provider=cfg.provider,
        raw=resp,
        usage=usage,
    )
