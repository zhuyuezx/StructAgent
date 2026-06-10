import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import core.tools  # noqa: F401  (loads draw.io operations through the registry)
from core.state import scene_graph as sg
from domains.drawio import operations


def _no_live_handles():
    return SimpleNamespace(
        is_valid=lambda: False,
        shape_bbox=None,
        extend={},
    )


def test_place_label_and_move_exits_text_edit_before_drag(monkeypatch):
    graph = sg.empty_graph()
    ui_graph = {"scene_graph": graph, "selected_handles": None}
    events = []

    def fake_place_shape(ui_graph, tool_name):
        obj = sg.add_object(
            ui_graph["scene_graph"],
            type_="Rectangle",
            bbox=[560, 360, 80, 40],
            label="",
            op_name="place_shape",
        )
        sg.set_selected(ui_graph["scene_graph"], obj["id"])
        return {
            "status": "ok",
            "tool": "place_shape",
            "tool_name": tool_name,
            "scene_object_id": obj["id"],
        }

    def fake_type_label(text, ui_graph=None):
        events.append(("type", text))
        selected = sg.get_selected(ui_graph["scene_graph"])
        sg.update_object_label(ui_graph["scene_graph"], selected["id"], text)
        return {"status": "ok", "tool": "type_label", "text": text}

    def fake_press_escape(ui_graph=None):
        events.append(("escape_step",))
        return {"status": "ok", "tool": "press_escape"}

    monkeypatch.setattr(operations, "_fn_place_shape", fake_place_shape)
    monkeypatch.setattr(operations, "_fn_type_label", fake_type_label)
    monkeypatch.setattr(operations, "_fn_press_escape", fake_press_escape)
    monkeypatch.setattr(operations.target_manager, "canvas_center", lambda: (600, 380))
    monkeypatch.setattr(operations, "save_scene", lambda ui_graph: None)
    monkeypatch.setattr(operations, "atom_click_at", lambda x, y, clicks=1, hold=0.08: events.append(("click", x, y, clicks)))
    monkeypatch.setattr(operations, "atom_drag", lambda sx, sy, tx, ty, **kwargs: events.append(("drag", sx, sy, tx, ty)))
    monkeypatch.setattr(operations, "atom_press", lambda key: events.append(("press", key)))
    monkeypatch.setattr(operations.time, "sleep", lambda _: None)

    result = operations._fn_place_label_and_move(
        ui_graph,
        tool_name="Rectangle_Tool",
        label="Source",
        direction="e",
        amount=120,
    )

    assert result["status"] == "ok"
    drag_index = next(i for i, event in enumerate(events) if event[0] == "drag")
    pre_drag_clicks = [event for event in events[:drag_index] if event[0] == "click"]
    assert pre_drag_clicks == [
        ("click", 600, 380, 2),
        ("click", 480, 280, 1),
        ("click", 600, 380, 1),
    ]
    assert events[drag_index] == ("drag", 600, 380, 720, 380)
    assert sg.get_selected(graph) is None


def test_connect_shapes_drags_from_source_quick_connect_arrow(monkeypatch):
    graph = sg.empty_graph()
    src = sg.add_object(
        graph,
        type_="Rectangle",
        bbox=[100, 100, 80, 40],
        label="A",
        op_name="setup",
    )
    tgt = sg.add_object(
        graph,
        type_="Rectangle",
        bbox=[260, 100, 80, 40],
        label="B",
        op_name="setup",
    )
    sg.set_selected(graph, src["id"])
    ui_graph = {
        "scene_graph": graph,
        "selected_handles": {
            "shape_bbox": src["bbox"],
            "resize": {"mr": [181, 121]},
            "extend": {"e": [208, 120]},
        },
        "UI_Elements": {},
    }
    events = []

    def fake_click_node(ui_graph, node_ref):
        events.append(("click_node", node_ref))
        if node_ref == "A":
            selected = src
            ui_graph["selected_handles"] = {
                "shape_bbox": src["bbox"],
                "resize": {"mr": [181, 121]},
                "extend": {"e": [208, 120]},
            }
        else:
            selected = tgt
            ui_graph["selected_handles"] = {
                "shape_bbox": tgt["bbox"],
                "resize": {"ml": [259, 121]},
            }
        sg.set_selected(ui_graph["scene_graph"], selected["id"])
        return {"status": "ok", "tool": "click_node"}

    monkeypatch.setattr(operations, "sync_current_bbox", lambda ui_graph: None)
    monkeypatch.setattr(operations, "refresh_handles", lambda *args, **kwargs: _no_live_handles())
    monkeypatch.setattr(operations, "save_scene", lambda ui_graph: None)
    monkeypatch.setattr(operations, "atom_move_to", lambda x, y: events.append(("move", x, y)))
    monkeypatch.setattr(operations, "atom_click_at", lambda x, y, clicks=1, hold=0.08: events.append(("click", x, y, clicks)))
    monkeypatch.setattr(operations, "atom_drag_path", lambda points, **kwargs: events.append(("drag_path", points)))
    monkeypatch.setattr(operations, "atom_press", lambda key: events.append(("press", key)))
    monkeypatch.setattr(operations.time, "sleep", lambda _: None)
    monkeypatch.setattr("core.tools.actions._fn_click_node", fake_click_node)

    result = operations._fn_connect_shapes(
        ui_graph,
        source_id="A",
        target_id="B",
        source_anchor="auto",
    )

    assert result["status"] == "ok"
    assert not any(event[0] == "click_node" for event in events)
    drag_index = next(i for i, event in enumerate(events) if event[0] == "drag_path")
    assert events[:drag_index] == [
        ("move", 140, 120),
        ("click", 140, 120, 1),
        ("move", 208, 120),
    ]
    assert ("drag_path", [(208, 120), (236, 120), (260, 120)]) in events
    assert result["source_anchor"] == "e"
    assert result["target_anchor"] == "w"
    assert result["from"] == [208, 120]
    assert result["approach"] == [236, 120]
    assert result["to"] == [260, 120]


def test_connect_shapes_uses_bbox_when_cached_arrow_is_not_visible(monkeypatch):
    graph = sg.empty_graph()
    src = sg.add_object(
        graph,
        type_="Rectangle",
        bbox=[100, 100, 80, 40],
        label="A",
        op_name="setup",
    )
    sg.add_object(
        graph,
        type_="Rectangle",
        bbox=[260, 100, 80, 40],
        label="B",
        op_name="setup",
    )
    sg.set_selected(graph, src["id"])
    ui_graph = {
        "scene_graph": graph,
        "selected_handles": None,
        "UI_Elements": {},
    }
    events = []

    def fake_click_node(ui_graph, node_ref):
        events.append(("click_node", node_ref))
        sg.set_selected(ui_graph["scene_graph"], src["id"])
        ui_graph["selected_handles"] = {
            "shape_bbox": src["bbox"],
            "extend": {"e": [208, 120]},
        }
        return {"status": "ok", "tool": "click_node"}

    monkeypatch.setattr(operations, "sync_current_bbox", lambda ui_graph: None)
    monkeypatch.setattr(operations, "refresh_handles", lambda *args, **kwargs: _no_live_handles())
    monkeypatch.setattr(operations, "save_scene", lambda ui_graph: None)
    monkeypatch.setattr(operations, "atom_move_to", lambda x, y: events.append(("move", x, y)))
    monkeypatch.setattr(operations, "atom_click_at", lambda x, y, clicks=1, hold=0.08: events.append(("click", x, y, clicks)))
    monkeypatch.setattr(operations, "atom_drag_path", lambda points, **kwargs: events.append(("drag_path", points)))
    monkeypatch.setattr(operations, "atom_press", lambda key: events.append(("press", key)))
    monkeypatch.setattr(operations.time, "sleep", lambda _: None)
    monkeypatch.setattr("core.tools.actions._fn_click_node", fake_click_node)

    result = operations._fn_connect_shapes(
        ui_graph,
        source_id="A",
        target_id="B",
        source_anchor="auto",
    )

    assert result["status"] == "ok"
    assert not any(event[0] == "click_node" for event in events)
    assert events[:3] == [
        ("move", 140, 120),
        ("click", 140, 120, 1),
        ("move", 208, 120),
    ]
    assert ("move", 208, 120) in events
    assert ("drag_path", [(208, 120), (236, 120), (260, 120)]) in events


def test_connect_shapes_falls_back_to_bbox_based_quick_connect_offset(monkeypatch):
    graph = sg.empty_graph()
    sg.add_object(
        graph,
        type_="Rectangle",
        bbox=[100, 100, 80, 40],
        label="A",
        op_name="setup",
    )
    sg.add_object(
        graph,
        type_="Rectangle",
        bbox=[260, 100, 80, 40],
        label="B",
        op_name="setup",
    )
    ui_graph = {
        "scene_graph": graph,
        "selected_handles": {"extend": {}},
        "UI_Elements": {},
    }
    events = []

    def fake_click_node(ui_graph, node_ref):
        events.append(("click_node", node_ref))
        ui_graph["selected_handles"] = {"extend": {}}
        return {"status": "ok", "tool": "click_node"}

    monkeypatch.setattr(operations, "sync_current_bbox", lambda ui_graph: None)
    monkeypatch.setattr(operations, "refresh_handles", lambda *args, **kwargs: _no_live_handles())
    monkeypatch.setattr(operations, "save_scene", lambda ui_graph: None)
    monkeypatch.setattr(operations, "atom_move_to", lambda x, y: events.append(("move", x, y)))
    monkeypatch.setattr(operations, "atom_click_at", lambda x, y, clicks=1, hold=0.08: events.append(("click", x, y, clicks)))
    monkeypatch.setattr(operations, "atom_drag_path", lambda points, **kwargs: events.append(("drag_path", points)))
    monkeypatch.setattr(operations, "atom_press", lambda key: events.append(("press", key)))
    monkeypatch.setattr(operations.time, "sleep", lambda _: None)
    monkeypatch.setattr("core.tools.actions._fn_click_node", fake_click_node)

    result = operations._fn_connect_shapes(
        ui_graph,
        source_id="A",
        target_id="B",
        source_anchor="e",
    )

    assert result["status"] == "ok"
    assert result["from"] == [208, 120]
    assert result["approach"] == [236, 120]
    assert result["to"] == [260, 120]
    assert ("move", 140, 120) in events
    assert ("click", 140, 120, 1) in events
    assert ("move", 208, 120) in events
    assert ("drag_path", [(208, 120), (236, 120), (260, 120)]) in events


def test_connect_shapes_uses_explicit_target_anchor(monkeypatch):
    graph = sg.empty_graph()
    sg.add_object(
        graph,
        type_="Rectangle",
        bbox=[100, 100, 80, 40],
        label="A",
        op_name="setup",
    )
    sg.add_object(
        graph,
        type_="Rectangle",
        bbox=[260, 100, 80, 40],
        label="B",
        op_name="setup",
    )
    ui_graph = {
        "scene_graph": graph,
        "selected_handles": {"extend": {"s": [140, 168]}},
        "UI_Elements": {},
    }
    events = []

    monkeypatch.setattr(operations, "sync_current_bbox", lambda ui_graph: None)
    monkeypatch.setattr(operations, "refresh_handles", lambda *args, **kwargs: _no_live_handles())
    monkeypatch.setattr(operations, "save_scene", lambda ui_graph: None)
    monkeypatch.setattr(operations, "atom_move_to", lambda x, y: events.append(("move", x, y)))
    monkeypatch.setattr(operations, "atom_click_at", lambda x, y, clicks=1, hold=0.08: events.append(("click", x, y, clicks)))
    monkeypatch.setattr(operations, "atom_drag_path", lambda points, **kwargs: events.append(("drag_path", points)))
    monkeypatch.setattr(operations, "atom_press", lambda key: events.append(("press", key)))
    monkeypatch.setattr(operations.time, "sleep", lambda _: None)

    result = operations._fn_connect_shapes(
        ui_graph,
        source_id="A",
        target_id="B",
        source_anchor="e",
        target_anchor="n",
    )

    assert result["status"] == "ok"
    assert result["source_anchor"] == "e"
    assert result["target_anchor"] == "n"
    assert result["from"] == [208, 120]
    assert result["approach"] == [300, 76]
    assert result["to"] == [300, 100]
    assert ("drag_path", [(208, 120), (300, 76), (300, 100)]) in events


def test_connect_shapes_prefers_detected_west_quick_connect_handle(monkeypatch):
    graph = sg.empty_graph()
    sg.add_object(
        graph,
        type_="Rectangle",
        bbox=[200, 100, 80, 40],
        label="A",
        op_name="setup",
    )
    sg.add_object(
        graph,
        type_="Rectangle",
        bbox=[0, 100, 80, 40],
        label="B",
        op_name="setup",
    )
    ui_graph = {
        "scene_graph": graph,
        "selected_handles": None,
        "UI_Elements": {},
    }
    events = []

    handles = SimpleNamespace(
        is_valid=lambda: True,
        shape_bbox=(200, 100, 80, 40),
        extend={"w": (152, 120)},
    )

    monkeypatch.setattr(operations, "sync_current_bbox", lambda ui_graph: None)
    monkeypatch.setattr(operations, "refresh_handles", lambda *args, **kwargs: handles)
    monkeypatch.setattr(operations, "save_scene", lambda ui_graph: None)
    monkeypatch.setattr(operations, "atom_move_to", lambda x, y: events.append(("move", x, y)))
    monkeypatch.setattr(operations, "atom_click_at", lambda x, y, clicks=1, hold=0.08: events.append(("click", x, y, clicks)))
    monkeypatch.setattr(operations, "atom_drag_path", lambda points, **kwargs: events.append(("drag_path", points)))
    monkeypatch.setattr(operations, "atom_press", lambda key: events.append(("press", key)))
    monkeypatch.setattr(operations.time, "sleep", lambda _: None)

    result = operations._fn_connect_shapes(
        ui_graph,
        source_id="A",
        target_id="B",
        source_anchor="w",
        target_anchor="e",
    )

    assert result["status"] == "ok"
    assert result["source_anchor"] == "w"
    assert result["target_anchor"] == "e"
    assert result["from"] == [152, 120]
    assert result["approach"] == [104, 120]
    assert result["to"] == [80, 120]
    assert ("drag_path", [(152, 120), (104, 120), (80, 120)]) in events


def test_connect_shapes_overrides_anchor_that_points_away_from_target(monkeypatch):
    graph = sg.empty_graph()
    sg.add_object(
        graph,
        type_="Rectangle",
        bbox=[100, 100, 80, 40],
        label="Rect1",
        op_name="setup",
    )
    sg.add_object(
        graph,
        type_="Rectangle",
        bbox=[100, 300, 80, 40],
        label="Rect3",
        op_name="setup",
    )
    ui_graph = {
        "scene_graph": graph,
        "selected_handles": {"extend": {}},
        "UI_Elements": {},
    }
    events = []

    def fake_click_node(ui_graph, node_ref):
        events.append(("click_node", node_ref))
        ui_graph["selected_handles"] = {"extend": {}}
        return {"status": "ok", "tool": "click_node"}

    monkeypatch.setattr(operations, "sync_current_bbox", lambda ui_graph: None)
    monkeypatch.setattr(operations, "refresh_handles", lambda *args, **kwargs: _no_live_handles())
    monkeypatch.setattr(operations, "save_scene", lambda ui_graph: None)
    monkeypatch.setattr(operations, "atom_move_to", lambda x, y: events.append(("move", x, y)))
    monkeypatch.setattr(operations, "atom_click_at", lambda x, y, clicks=1, hold=0.08: events.append(("click", x, y, clicks)))
    monkeypatch.setattr(operations, "atom_drag_path", lambda points, **kwargs: events.append(("drag_path", points)))
    monkeypatch.setattr(operations, "atom_press", lambda key: events.append(("press", key)))
    monkeypatch.setattr(operations.time, "sleep", lambda _: None)
    monkeypatch.setattr("core.tools.actions._fn_click_node", fake_click_node)

    result = operations._fn_connect_shapes(
        ui_graph,
        source_id="Rect3",
        target_id="Rect1",
        source_anchor="w",
    )

    assert result["status"] == "ok"
    assert result["source_anchor"] == "n"
    assert result["target_anchor"] == "s"
    assert result["from"] == [140, 272]
    assert result["approach"] == [140, 164]
    assert result["to"] == [140, 140]
    assert ("drag_path", [(140, 272), (140, 164), (140, 140)]) in events


def test_scene_graph_bbox_exposes_eight_connection_points():
    graph = sg.empty_graph()
    obj = sg.add_object(
        graph,
        type_="Rectangle",
        bbox=[100, 100, 80, 40],
        label="A",
        op_name="setup",
    )

    assert obj["anchors"] == {
        "n": [140, 100],
        "s": [140, 140],
        "e": [180, 120],
        "w": [100, 120],
        "nw": [100, 100],
        "ne": [180, 100],
        "sw": [100, 140],
        "se": [180, 140],
    }
