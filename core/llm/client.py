"""Provider-dispatching chat client."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core import config
from core.llm.types import ChatResponse


def chat(
    *,
    purpose: str,
    messages: List[Dict[str, Any]],
    images: Optional[List[str]] = None,
    response_format: Optional[str] = None,
    timeout: Optional[float] = None,
) -> ChatResponse:
    cfg = config.model_config(purpose)
    provider = cfg.provider.lower()
    if provider in {"ollama", "local_ollama"}:
        from core.llm.providers.ollama_provider import chat as provider_chat
    elif provider in {"openai", "openai_compatible", "vllm"}:
        from core.llm.providers.openai_compatible import chat as provider_chat
    else:
        raise ValueError(f"Unknown LLM provider '{cfg.provider}' for {purpose}")
    return provider_chat(
        cfg,
        messages=messages,
        images=images,
        response_format=response_format,
        timeout=timeout,
    )
