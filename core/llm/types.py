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
