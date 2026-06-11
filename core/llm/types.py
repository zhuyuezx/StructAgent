"""Shared LLM client types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ChatResponse:
    content: str
    model: str
    provider: str
    raw: Optional[Dict[str, Any]] = None
    # Normalized token accounting: {prompt_tokens, completion_tokens,
    # total_tokens}. None when the provider does not report usage.
    usage: Optional[Dict[str, int]] = None
