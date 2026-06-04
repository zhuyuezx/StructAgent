"""
Checkpoint — structural assertions over the scene graph (Phase 2).

A checkpoint is attached to a plan step and verified AFTER that step runs. It
pairs two things:

  - a small set of **structural assertions** over ``scene_graph`` — evaluated
    deterministically, with NO LLM, and
  - a **screenshot** taken at that point (for a human to eyeball; captured by
    the orchestrator, not here).

This is the cheap verification ORCHESTRATOR.md is built around: because the
scene graph is deterministic ground truth, we compare graph facts instead of
asking the model to validate. Checkpoints can be authored by the Planner
(auto-generated from intent) or by the user (in the Studio), and edited freely.

Checkpoint schema — a dict attached to a step under the ``"checkpoint"`` key::

    {
      "description": "human-readable expectation",   # optional
      "screenshot": true,                             # default true
      "assert": [ <assertion>, ... ]                  # may be empty
    }

Assertion kinds (the ``"check"`` field selects one)::

    {"check": "objects_count", "op": ">=", "value": 2}
    {"check": "edges_count",   "op": "==", "value": 1}
    {"check": "object_exists", "label": "Source"}          # or "id": "obj_001"
    {"check": "edge_exists",   "source": "Source", "target": "Target"}  # labels or ids
    {"check": "selected",      "label": "Target"}          # label optional
    {"check": "last_op",       "value": "connect_shapes"}

``op`` is one of ``== != >= <= > <`` (default ``==``). ``edge_exists`` is
direction-tolerant unless ``"directed": true`` is set.

:func:`evaluate` returns a result dict the orchestrator stores on the trace and
the frontend renders as pass/fail badges; :func:`summarize` gives a one-liner.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

# Comparison operators allowed in count checks.
_OPS: Dict[str, Callable[[Any, Any], bool]] = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}

# The assertion kinds this evaluator understands — exported so the API / UI
# can advertise them and the Planner prompt can stay in sync.
CHECK_KINDS = (
    "objects_count",
    "edges_count",
    "object_exists",
    "edge_exists",
    "selected",
    "last_op",
)


# ===========================================================================
# Scene-graph lookup helpers
# ===========================================================================

def _objects(sg: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sg.get("objects", []) or []


def _edges(sg: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sg.get("edges", []) or []


def _find_object(
    sg: Dict[str, Any], *, id: Optional[str] = None, label: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    objs = _objects(sg)
    if id:
        return next((o for o in objs if o.get("id") == id), None)
    if label is not None:
        return next((o for o in objs if o.get("label") == label), None)
    return None


def _resolve_id(sg: Dict[str, Any], ref: Optional[str]) -> Optional[str]:
    """Resolve a ref (object id OR label) to an object id, or None."""
    if not ref:
        return None
    obj = _find_object(sg, id=ref) or _find_object(sg, label=ref)
    return obj["id"] if obj else None


def _cmp(got: Any, op: str, want: Any) -> bool:
    fn = _OPS.get(op)
    return bool(fn(got, want)) if fn else False


# ===========================================================================
# Single-assertion evaluation
# ===========================================================================

def _eval_assertion(a: Dict[str, Any], sg: Dict[str, Any]) -> Tuple[bool, str]:
    """Return ``(passed, human_detail)`` for one assertion against *sg*."""
    check = a.get("check")

    if check == "objects_count":
        op, want, got = a.get("op", "=="), a.get("value"), len(_objects(sg))
        return _cmp(got, op, want), f"objects_count: {got} {op} {want}"

    if check == "edges_count":
        op, want, got = a.get("op", "=="), a.get("value"), len(_edges(sg))
        return _cmp(got, op, want), f"edges_count: {got} {op} {want}"

    if check == "object_exists":
        ref = a.get("id") or a.get("label")
        obj = _find_object(sg, id=a.get("id"), label=a.get("label"))
        return obj is not None, (
            f"object '{ref}': {'found ' + obj['id'] if obj else 'NOT found'}"
        )

    if check == "edge_exists":
        s_ref, t_ref = a.get("source"), a.get("target")
        src, tgt = _resolve_id(sg, s_ref), _resolve_id(sg, t_ref)
        found = False
        if src and tgt:
            found = any(
                e.get("source") == src and e.get("target") == tgt for e in _edges(sg)
            )
            if not found and not a.get("directed", False):
                found = any(
                    e.get("source") == tgt and e.get("target") == src
                    for e in _edges(sg)
                )
        return found, f"edge {s_ref}→{t_ref}: {'found' if found else 'NOT found'}"

    if check == "selected":
        sel = next((o for o in _objects(sg) if o.get("selected")), None)
        if "label" in a:
            ok = sel is not None and sel.get("label") == a["label"]
            cur = f"'{sel['label']}'" if sel else "none"
            return ok, f"selected: {cur}, want '{a['label']}'"
        return sel is not None, (
            f"selected: {sel['id'] if sel else 'none'}"
        )

    if check == "last_op":
        got = (sg.get("metadata") or {}).get("last_op")
        want = a.get("value")
        return got == want, f"last_op: {got!r}, want {want!r}"

    return False, f"unknown check '{check}'"


# ===========================================================================
# Public API
# ===========================================================================

def evaluate(checkpoint: Dict[str, Any], scene_graph: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate every assertion in *checkpoint* against *scene_graph*.

    Returns::

        {
          "passed": bool,               # all assertions passed (vacuously true
                                        #   if there are none)
          "description": str,
          "results": [ {"check", "passed", "detail", "spec"}, ... ],
        }
    """
    asserts = checkpoint.get("assert") or []
    results: List[Dict[str, Any]] = []
    for a in asserts:
        if not isinstance(a, dict):
            results.append({"check": None, "passed": False,
                            "detail": f"malformed assertion {a!r}", "spec": a})
            continue
        passed, detail = _eval_assertion(a, scene_graph)
        results.append({"check": a.get("check"), "passed": passed,
                        "detail": detail, "spec": a})
    passed_all = all(r["passed"] for r in results) if results else True
    return {
        "passed": passed_all,
        "description": checkpoint.get("description", ""),
        "results": results,
    }


def summarize(result: Dict[str, Any]) -> str:
    """One-line summary of an :func:`evaluate` result."""
    n = len(result.get("results", []))
    n_pass = sum(1 for r in result.get("results", []) if r.get("passed"))
    mark = "✓" if result.get("passed") else "✗"
    desc = result.get("description") or ""
    head = f"{mark} checkpoint {n_pass}/{n} assertions passed"
    return f"{head} — {desc}" if desc else head
