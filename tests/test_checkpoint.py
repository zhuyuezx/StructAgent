"""
test_checkpoint — checkpoint DSL + run_plan integration (Phase 2), offline.

No GUI, no LLM, no draw.io. The integration test registers a fake tool that
mutates the scene graph in-memory and injects a fake screenshot capturer, so
the full run_plan → screenshot → evaluate path is exercised without touching
the screen.

    python tests/test_checkpoint.py            # run every check
    python tests/test_checkpoint.py --eval     # evaluator unit checks only
    python tests/test_checkpoint.py --run       # run_plan integration only
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import checkpoint as ck
from core.state import scene_graph as sg
from core.tools.registry import ToolNode, register, TOOL_CATALOG


def _sample_scene():
    return {
        "objects": [
            {"id": "obj_001", "label": "Source", "selected": False},
            {"id": "obj_002", "label": "Target", "selected": True},
        ],
        "edges": [{"id": "edge_001", "source": "obj_001", "target": "obj_002"}],
        "metadata": {"last_op": "connect_shapes"},
    }


def test_eval() -> None:
    scene = _sample_scene()

    # Every supported check, in a passing configuration.
    passing = {
        "objects_count":  {"check": "objects_count", "op": "==", "value": 2},
        "edges_count":    {"check": "edges_count", "op": ">=", "value": 1},
        "object_exists":  {"check": "object_exists", "label": "Source"},
        "object_by_id":   {"check": "object_exists", "id": "obj_002"},
        "edge_exists":    {"check": "edge_exists", "source": "Source", "target": "Target"},
        "edge_reversed":  {"check": "edge_exists", "source": "Target", "target": "Source"},
        "selected":       {"check": "selected", "label": "Target"},
        "selected_any":   {"check": "selected"},
        "last_op":        {"check": "last_op", "value": "connect_shapes"},
    }
    for name, a in passing.items():
        ok, detail = ck._eval_assertion(a, scene)
        assert ok, f"expected PASS for {name}: {detail}"
    print(f"  ✓ {len(passing)} passing assertions all passed")

    # Failing configurations.
    failing = {
        "count_too_high": {"check": "objects_count", "op": ">=", "value": 5},
        "missing_obj":    {"check": "object_exists", "label": "Ghost"},
        "missing_edge":   {"check": "edge_exists", "source": "Target", "target": "Ghost"},
        "directed_rev":   {"check": "edge_exists", "source": "Target",
                           "target": "Source", "directed": True},
        "wrong_selected": {"check": "selected", "label": "Source"},
        "wrong_last_op":  {"check": "last_op", "value": "place_shape"},
        "unknown_kind":   {"check": "does_not_exist"},
    }
    for name, a in failing.items():
        ok, detail = ck._eval_assertion(a, scene)
        assert not ok, f"expected FAIL for {name}: {detail}"
    print(f"  ✓ {len(failing)} failing assertions all failed")

    spaced_scene = {
        "objects": [
            {"id": "obj_001", "label": "Rect1", "bbox": [0, 0, 80, 40]},
            {"id": "obj_002", "label": "Rect2", "bbox": [110, 0, 80, 40]},
        ],
        "edges": [],
        "metadata": {},
    }
    touching_scene = {
        "objects": [
            {"id": "obj_001", "label": "Rect1", "bbox": [0, 0, 80, 40]},
            {"id": "obj_002", "label": "Rect2", "bbox": [80, 0, 80, 40]},
        ],
        "edges": [],
        "metadata": {},
    }
    no_overlap = {"check": "no_overlap", "labels": ["Rect1", "Rect2"], "min_gap": 12}
    ok, detail = ck._eval_assertion(no_overlap, spaced_scene)
    assert ok, f"expected PASS for no_overlap: {detail}"
    ok, detail = ck._eval_assertion(no_overlap, touching_scene)
    assert not ok, f"expected FAIL for touching no_overlap: {detail}"

    # evaluate() aggregation + empty-checkpoint vacuous pass.
    r = ck.evaluate({"description": "d", "assert": list(passing.values())}, scene)
    assert r["passed"] is True and len(r["results"]) == len(passing)
    r2 = ck.evaluate({"assert": [passing["selected"], failing["missing_obj"]]}, scene)
    assert r2["passed"] is False
    assert ck.evaluate({"assert": []}, scene)["passed"] is True
    print("  ✓ evaluate() aggregation + vacuous-true on empty checkpoint")
    print("eval: OK")


def test_run() -> None:
    from core.orchestrator import run_plan, plan_succeeded, checkpoints_passed

    # A fake tool that mutates the in-memory scene graph (no GUI).
    def _fn_fake_add(ui_graph, label):
        g = ui_graph["scene_graph"]
        obj = sg.add_object(g, type_="Rectangle", bbox=[0, 0, 10, 10],
                            label=label, op_name="fake_add")
        sg.set_selected(g, obj["id"])
        return {"status": "ok", "tool": "fake_add", "scene_object_id": obj["id"]}

    register(ToolNode(name="fake_add", fn=_fn_fake_add, params=["label"],
                      needs_ui_graph=True, description="test-only shape add"))
    assert "fake_add" in TOOL_CATALOG

    shots = []  # record injected screenshot calls instead of touching the screen
    def fake_shot(name: str) -> str:
        shots.append(name)
        return f"/tmp/{name}"

    graph = {"scene_graph": sg.empty_graph()}
    steps = [
        {"tool": "fake_add", "params": {"label": "Source"},
         "checkpoint": {"description": "Source exists",
                        "assert": [{"check": "object_exists", "label": "Source"}]}},
        {"tool": "fake_add", "params": {"label": "Target"},
         "checkpoint": {"description": "two objects, Target selected",
                        "assert": [{"check": "objects_count", "op": "==", "value": 2},
                                   {"check": "selected", "label": "Target"}]}},
        {"tool": "fake_add", "params": {"label": "Extra"},
         "checkpoint": {"description": "this should FAIL (expects 5)",
                        "assert": [{"check": "objects_count", "op": ">=", "value": 5}]}},
    ]

    trace = run_plan(steps, graph, screenshot_fn=fake_shot, step_cooldown=0)

    assert len(trace) == 3, trace
    assert plan_succeeded(trace), "all dispatches should be ok"
    assert trace[0]["checkpoint"]["passed"] is True
    assert trace[1]["checkpoint"]["passed"] is True
    assert trace[2]["checkpoint"]["passed"] is False, "step 3 checkpoint must fail"
    assert not checkpoints_passed(trace), "one checkpoint failed → overall fail"
    # Screenshot captured at each checkpoint via the injected capturer.
    assert shots == ["_checkpoint_step01.png", "_checkpoint_step02.png",
                     "_checkpoint_step03.png"], shots
    assert trace[0]["checkpoint"]["screenshot"] == "/tmp/_checkpoint_step01.png"
    print(f"  ✓ 3 steps ran; checkpoints pass/pass/FAIL; {len(shots)} screenshots captured")

    # stop_on_checkpoint_fail halts after the failing checkpoint.
    graph2 = {"scene_graph": sg.empty_graph()}
    trace2 = run_plan(steps, graph2, screenshot_fn=fake_shot,
                      step_cooldown=0, stop_on_checkpoint_fail=True)
    assert len(trace2) == 3 and trace2[-1]["checkpoint"]["passed"] is False
    print("  ✓ stop_on_checkpoint_fail halts at the failing checkpoint")
    print("run: OK")


def main() -> None:
    p = argparse.ArgumentParser(description="Checkpoint tests (offline).")
    p.add_argument("--eval", action="store_true", help="evaluator unit checks only")
    p.add_argument("--run", action="store_true", help="run_plan integration only")
    args = p.parse_args()
    do_eval = args.eval or not args.run
    do_run = args.run or not args.eval
    if do_eval:
        print("== evaluator =="); test_eval()
    if do_run:
        print("== run_plan integration =="); test_run()
    print("\nALL CHECKPOINT TESTS PASSED")


if __name__ == "__main__":
    main()
