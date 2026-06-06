"""
draw.io domain perception module.

Separates draw.io-specific perception from the generic core:

  - LABEL_PROMPT   The VLM prompt for labeling sidebar icons in draw.io.
  - detect_handles Re-exported from core.perception.handles (cyan-handle
                   detection is entirely draw.io specific and lives there).

Any new domain (e.g. iMovie) provides its own ``domains/<name>/perception.py``
implementing the same interface.  ``core.tools.reconcile`` and the explore API
load it lazily via :func:`core.perception.domain_perception`.

Interface contract for a domain perception module
--------------------------------------------------
LABEL_PROMPT : str (optional)
    Prompt passed to the icon-labeling VLM.  If absent, label.py uses a
    generic fallback.

detect_handles(screenshot_path: str) -> SelectionHandles | None (optional)
    Called by reconcile after geometry operations to read selection chrome.
    Return None (or omit the function) for apps that have no handle concept.
"""

from core.perception.handles import detect_handles, SelectionHandles  # noqa: F401

LABEL_PROMPT = (
    "This is a small icon from draw.io's shape sidebar. "
    "What shape does it represent? Reply with ONLY a short label like: "
    "Rectangle, Ellipse, Rounded_Rectangle, Diamond, Triangle, Arrow, "
    "Text, Cylinder, Cloud, Hexagon, Parallelogram, etc. "
    "One or two words, use underscores for spaces. No punctuation."
)
