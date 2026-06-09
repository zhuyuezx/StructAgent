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
    return ChatResponse(
        content=resp["message"]["content"],
        model=cfg.model,
        provider=cfg.provider,
        raw=resp,
    )
