"""OpenAI-compatible Chat Completions provider.

Works with OpenAI and servers such as vLLM that expose ``/v1/chat/completions``.
"""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional

from core.config import ModelConfig
from core.llm.types import ChatResponse


def _image_url(path: str) -> str:
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/png;base64,{data}"


def _convert_messages(
    messages: List[Dict[str, Any]], images: Optional[List[str]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for msg in messages:
        copied = {k: v for k, v in msg.items() if k != "images"}
        if "images" in msg:
            msg_images = msg.get("images") or []
        else:
            msg_images = []
        content = copied.get("content", "")
        if msg_images:
            parts: List[Dict[str, Any]] = [{"type": "text", "text": str(content)}]
            for item in msg_images:
                if isinstance(item, (bytes, bytearray)):
                    data = base64.b64encode(bytes(item)).decode("ascii")
                    url = f"data:image/png;base64,{data}"
                else:
                    url = _image_url(str(item))
                parts.append({"type": "image_url", "image_url": {"url": url}})
            copied["content"] = parts
        out.append(copied)
    if images:
        if not out:
            raise ValueError("Cannot attach images without at least one message")
        last = dict(out[-1])
        existing = last.get("content", "")
        if isinstance(existing, list):
            parts = list(existing)
        else:
            parts = [{"type": "text", "text": str(existing)}]
        for path in images:
            parts.append({"type": "image_url", "image_url": {"url": _image_url(path)}})
        last["content"] = parts
        out[-1] = last
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

    base_url = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    payload: Dict[str, Any] = {
        "model": cfg.model,
        "messages": _convert_messages(messages, images),
        "temperature": 0 if cfg.temperature is None else cfg.temperature,
        "max_tokens": cfg.max_tokens or 4096,
    }
    if response_format == "json_object":
        payload["response_format"] = {"type": "json_object"}
    call_timeout = timeout or cfg.timeout or 60
    with httpx.Client(timeout=httpx.Timeout(call_timeout, connect=10.0)) as client:
        resp = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    usage = None
    raw_usage = data.get("usage")
    if isinstance(raw_usage, dict):
        prompt = raw_usage.get("prompt_tokens")
        completion = raw_usage.get("completion_tokens")
        if isinstance(prompt, int) or isinstance(completion, int):
            usage = {
                "prompt_tokens": int(prompt or 0),
                "completion_tokens": int(completion or 0),
                "total_tokens": int(raw_usage.get("total_tokens")
                                    or (prompt or 0) + (completion or 0)),
            }
    return ChatResponse(
        content=data["choices"][0]["message"]["content"],
        model=cfg.model,
        provider=cfg.provider,
        raw=data,
        usage=usage,
    )
