"""
drawio domain tool loader.

Loads all L1 and L2 tool definitions from state/tools/*.json via
core.tools.loader.  After import, every tool defined in those JSON
files is registered in the live TOOL_CATALOG and accessible via
core.tools.dispatch().
"""

from __future__ import annotations

from pathlib import Path

from core import config
from core.tools.loader import load_tools_from_dir

_tools_dir = Path(config.state_dir()) / "tools"
_nodes = load_tools_from_dir(_tools_dir)
