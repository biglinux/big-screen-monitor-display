"""Design Studio editor state (no window needed)."""

import pytest

pytest.importorskip("gi")
try:
    import kojiro_editor
except (ImportError, ValueError) as error:      # GTK 4 / pycairo not installed
    pytest.skip(f"GTK editor unavailable: {error}", allow_module_level=True)

from bsmd.kojiro import model, presets


@pytest.fixture
def state():
    changes = []
    editor = kojiro_editor.EditorState(presets.build("cyberpunk"), changes.append)
    editor.target = (800, 480)
    editor.changes = changes
    return editor


def test_select_move_undo_redo(state):
    state.select("cpu-1")
    x, y, w, h = state.box(state.primary())
    state.set_boxes({"cpu-1": (x + 40, y + 10, w, h)})
    assert state.box(state.primary())[0] == pytest.approx(x + 40)
    assert state.undo() and state.box(state.widget("cpu-1"))[0] == pytest.approx(x)
    assert state.redo() and state.box(state.widget("cpu-1"))[0] == pytest.approx(x + 40)


def test_edits_coalesce_into_one_undo_step(state):
    state.select("cpu-1")
    for glow in range(10, 60, 10):
        state.set_prop("cpu-1", "glow", glow)
    assert len(state.undo_stack) == 1
    state.undo()
    assert state.widget("cpu-1")["glow"] == presets.build("cyberpunk")["layouts"]["landscape"][2]["glow"]


def test_add_duplicate_delete(state):
    added = state.add("battery")
    assert added["id"] == "battery-1" and state.selection == ["battery-1"]
    box = state.box(added)
    assert box[0] + box[2] / 2 == pytest.approx(400, abs=1)        # centred
    state.duplicate()
    assert len([w for w in state.widgets() if w["type"] == "battery"]) == 2
    state.delete()
    assert len([w for w in state.widgets() if w["type"] == "battery"]) == 1


def test_group_moves_and_selects_together(state):
    state.select_many(["ram-1", "swap-1"])
    state.group()
    state.select(None)
    state.select("ram-1")
    assert set(state.selection) == {"ram-1", "swap-1"}
    before = {wid: state.box(state.widget(wid)) for wid in state.selection}
    state.nudge(5, 0)
    for wid, box in before.items():
        assert state.box(state.widget(wid))[0] == pytest.approx(box[0] + 5)


def test_locked_widgets_do_not_move(state):
    state.select("clock-1")
    state.set_prop("clock-1", "locked", True)
    before = state.box(state.widget("clock-1"))
    state.nudge(10, 10)
    assert state.box(state.widget("clock-1")) == pytest.approx(before)


def test_align_restack_and_style_clipboard(state):
    state.select_many(["cpu-1", "gpu-1"])
    state.align("top")
    assert state.box(state.widget("cpu-1"))[1] == pytest.approx(state.box(state.widget("gpu-1"))[1])
    state.restack("top")
    assert [w["id"] for w in state.widgets()][-2:] == ["cpu-1", "gpu-1"]
    state.select("disk-1")
    state.copy_style()
    state.select("net-up-1")
    state.paste_style()
    assert state.widget("net-up-1")["color"] == state.widget("disk-1")["color"]


def test_portrait_layout_is_materialised_on_first_edit(state):
    state.portrait = True
    state.target = (480, 800)
    assert state.portrait_is_auto()
    state.select("cpu-1")
    state.nudge(3, 0)
    assert not state.portrait_is_auto()
    state.reset_portrait()
    assert state.portrait_is_auto()


def test_presets_and_recolour_are_undoable(state):
    state.apply_preset("matrix")
    assert state.config["preset"] == "matrix"
    state.recolor(["#123456"])
    assert all(w["color"] == "#123456" for w in state.widgets())
    state.undo()
    state.undo()
    assert state.config["preset"] == "cyberpunk"


def test_rebase_keeps_pixels(state):
    state.target = (1024, 600)
    before = {w["id"]: state.box(w) for w in state.widgets()}
    state.rebase()
    assert tuple(state.config["ref"]) == (1024, 600)
    for widget in state.widgets():
        assert state.box(widget) == pytest.approx(before[widget["id"]], abs=1e-6)
    clean, problems = model.validate(state.config)
    assert not problems
