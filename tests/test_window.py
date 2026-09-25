"""The window: drawing, picking, transforms, and what an export admits to.

Offscreen, so it runs anywhere, and never `exec()`s a dialog - a test that
reaches a modal event loop hangs rather than fails, which is the worst shape
a test problem can take. Menus are BUILT and inspected instead.
"""

import os

import numpy as np
import pytest

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QMenu

from dscpanel.core import export, loader, model, units


@pytest.fixture
def window(qapp, sample):
    """A window with BOTH segments of the test file on the plot.

    A file now opens with its first heating scan alone (Christian's default
    for stacked figures), so a test that wants two curves ticks the second
    one on the way the outliner does.
    """
    from dscpanel.ui.window import MainWindow
    win = MainWindow()
    win.resize(900, 560)
    win._sample_loaded(sample)
    win.toggle_segment(sample, 1, True)
    win.undo.clear()
    return win


@pytest.fixture
def fresh_window(qapp, sample):
    """A window exactly as opening one file leaves it."""
    from dscpanel.ui.window import MainWindow
    win = MainWindow()
    win.resize(900, 560)
    win._sample_loaded(sample)
    return win


def _press(widget, pos, button=Qt.LeftButton, modifiers=Qt.NoModifier):
    return QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(*pos),
                       QPointF(*pos), button, button, modifiers)


def _move(widget, pos, buttons=Qt.LeftButton):
    return QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(*pos),
                       QPointF(*pos), Qt.NoButton, buttons, Qt.NoModifier)


def _release(widget, pos, button=Qt.LeftButton):
    return QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(*pos),
                       QPointF(*pos), button, button, Qt.NoModifier)


def _double(widget, pos, button=Qt.LeftButton):
    return QMouseEvent(QMouseEvent.Type.MouseButtonDblClick, QPointF(*pos),
                       QPointF(*pos), button, button, Qt.NoModifier)


def _double_drag(plot, start, end, release=True, second_press=True):
    """A double-click-drag: the first click, the second press, the moves and
    the release.

    Qt can deliver the second press TWICE - as a press and then as a
    double-click - or as the double-click alone, depending on the version and
    the path the input took. The plot has to be right either way, so the
    default here is the harder of the two, and one test runs the other.
    """
    plot.mousePressEvent(_press(plot, start))
    plot.mouseReleaseEvent(_release(plot, start))
    if second_press:
        plot.mousePressEvent(_press(plot, start))
    plot.mouseDoubleClickEvent(_double(plot, start))
    middle = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    plot.mouseMoveEvent(_move(plot, middle))
    plot.mouseMoveEvent(_move(plot, end))
    if release:
        plot.mouseReleaseEvent(_release(plot, end))


def test_a_file_opens_with_its_first_heating_scan_only(fresh_window):
    """The default for a stacked figure: one curve per file, whichever file
    it is. Everything else is one tick away in the outliner."""
    assert len(fresh_window.doc.scans) == 1
    assert fresh_window.doc.scans[0].direction() == "up"
    fresh_window.plot.grab()                 # paints without raising


def test_every_segment_is_reachable_in_the_outliner(fresh_window, sample):
    tree = fresh_window.outliner
    row = tree.topLevelItem(0)
    assert row.childCount() == sample.segment_count()
    names = [row.child(i).text(1) for i in range(row.childCount())]
    assert "not shown" in names               # the segment that is not drawn
    fresh_window.toggle_segment(sample, 1, True)
    assert len(fresh_window.doc.scans) == 2
    assert fresh_window.undo.can_undo()
    fresh_window.undo.undo()
    assert len(fresh_window.doc.scans) == 1


def test_the_window_draws_every_chosen_segment(window):
    assert len(window.doc.scans) == 2
    assert len(window.plot.traces) == 2
    window.plot.grab()                       # paints without raising
    assert window.plot.traces[0].px is not None


def test_no_shortcut_is_claimed_twice(window):
    assert window.ops.duplicate_keys() == {}


def test_every_operator_is_reachable_and_safe_to_ask_about(window):
    for op in window.ops.all():
        op.enabled(window)                   # a predicate must not raise


def test_a_cooling_scan_is_drawn_although_x_runs_backwards(window):
    cooling = window.doc.scans[1]
    assert cooling.direction() == "down"
    trace = [t for t in window.plot.traces if t.scan is cooling][0]
    window.plot.grab()
    assert trace.px is not None and len(trace.px) > 10
    # ...and the drawn points span the whole visible temperature range
    assert float(trace.px.max() - trace.px.min()) > 0.5 * window.plot.width()


def test_dragging_a_curve_never_moves_it(window):
    """Christian: a scan moves with select > G and with nothing else. A drag
    that starts on a curve marks an interval on it instead."""
    plot = window.plot
    plot.grab()
    trace = plot.traces[0]
    start = (float(trace.px[len(trace.px) // 2]),
             float(trace.py[len(trace.py) // 2]))
    end = (start[0] + 30, start[1] - 40)
    asked = _answer(window, None)
    plot.mousePressEvent(_press(plot, start))
    plot.mouseMoveEvent(_move(plot, end))
    plot.mouseReleaseEvent(_release(plot, end))
    assert len(asked) == 1                    # an interval, and it asked
    assert [s.offset for s in window.doc.scans] == [0.0, 0.0]
    assert window.undo.depth() == 0


def test_grab_takes_a_typed_number(window):
    plot = window.plot
    window.doc.select_only([window.doc.scans[0]])
    assert plot.start_grab()
    for character in "0.25":
        plot._move["typed"] += character
    plot._update_move(plot._move["start"])
    plot._finish_move()
    assert window.doc.scans[0].offset == pytest.approx(0.25)
    assert window.undo.undo_label().startswith("move")


def test_escape_puts_a_grab_back(window):
    plot = window.plot
    window.doc.select_only([window.doc.scans[0]])
    plot.start_grab()
    plot._move["typed"] = "5"
    plot._update_move(plot._move["start"])
    assert window.doc.scans[0].offset == pytest.approx(5.0)
    plot._finish_move(cancel=True)
    assert window.doc.scans[0].offset == 0.0
    assert window.undo.depth() == 0


def test_a_scan_without_m_is_a_placeholder_and_blinks(window):
    window.set_unit(units.UNIT_W_MOL)
    trace = window.plot.traces[0]
    assert trace.missing == "molar mass"
    assert trace.x is None
    window.plot.grab()                       # draws the placeholder
    assert window.plot._blink_timer.isActive()
    window.doc.samples[0].molar_mass = 150.0
    window._live_change()
    assert window.plot.traces[0].missing is None
    assert not window.plot._blink_timer.isActive()


def test_the_alarm_stops_while_a_gesture_is_live(window):
    window.set_unit(units.UNIT_W_MOL)
    window.plot._blink = 0
    assert window.plot.blink_lit()
    window.doc.select_only([window.doc.scans[0]])
    window.plot.start_grab()
    assert not window.plot.blink_lit()


def test_an_export_says_what_is_missing(window, tmp_path):
    window.set_unit(units.UNIT_W_MOL)
    warnings = export.warnings_for(window.doc)
    assert any("NO MOLAR MASS" in line for line in warnings)
    window.doc.samples[0].molar_mass = 150.0
    window._live_change()
    assert not [line for line in export.warnings_for(window.doc)
                if "MOLAR MASS" in line]
    # the synthetic sample states no exotherm direction, so that warning
    # stays - and it should: it is the one that cannot be inferred
    assert any("EXO DIRECTION ASSUMED" in line
               for line in export.warnings_for(window.doc))


def test_exports_write_something_readable(window, tmp_path):
    csv = window.export_csv(str(tmp_path / "curves.csv"))
    assert csv and os.path.getsize(csv) > 100
    driver = window.export_driver(str(tmp_path / "DSC_Plotter.py"))
    text = open(driver, encoding="utf-8").read()
    assert "add_line(ax, datas, (0, 0)" in text
    image = window.export_image(str(tmp_path / "figure.png"))
    assert image and os.path.getsize(image) > 1000


def test_relabelling_the_arrow_does_not_flip_the_figure(window):
    before = window.doc.exo
    window.relabel_arrow()
    assert window.doc.arrow.word == units.WORD_ENDO
    assert window.doc.exo == before          # endo up IS exo down
    window.flip_arrow()
    assert window.doc.exo != before


def test_stack_then_align_then_undo(window):
    window.select_all(True)
    window.stack_selected()
    offsets = [s.offset for s in window.doc.scans]
    assert offsets[1] > offsets[0]
    window.align_selected()
    assert [s.offset for s in window.doc.scans] != offsets
    window.undo.undo()
    assert [s.offset for s in window.doc.scans] == offsets


def test_the_outliner_lists_what_is_there(window):
    window.refresh()
    tree = window.outliner
    # the sample, the legend and the arrow
    assert tree.topLevelItemCount() == 3
    sample_row = tree.topLevelItem(0)
    assert sample_row.childCount() == 2
    assert "no M" in sample_row.text(1)


def test_context_menus_are_built_without_being_shown(window):
    from PySide6.QtWidgets import QMenu
    menu = QMenu(window)
    window._scan_menu(menu, window.doc.scans[0])
    labels = [a.text() for a in menu.actions() if a.text()]
    assert any("Settings for" in text for text in labels)
    assert any("molar mass" in text.lower() for text in labels)


def test_drop_accepts_tri_and_sessions(window):
    from dscpanel import branding
    assert loader.looks_readable(__file__) is False
    assert branding.SESSION_EXT == ".dscpanel"


# ------------------------------------------- what Christian reported broken
def test_the_arrow_moves_with_the_cursor_and_not_against_it(window):
    """Dragging the arrow DOWN must move it down. The y fraction is measured
    from the top of the plot, so the sign was inverted."""
    plot = window.plot
    plot.grab()
    arrow = window.doc.arrow
    before_y, before_x = arrow.y, arrow.x
    start = plot._arrow_rect().center()
    _double_drag(plot, (start.x(), start.y()),
                 (start.x() + 60, start.y() + 50))
    assert arrow.y > before_y                 # down on screen is a bigger y
    assert arrow.x > before_x                 # and an artist moves in x too
    assert window.undo.undo_label() == "move arrow"
    window.undo.undo()
    assert arrow.y == pytest.approx(before_y)
    assert arrow.x == pytest.approx(before_x)


def test_a_scan_has_no_x_freedom_to_lock(window):
    plot = window.plot
    window.doc.select_only([window.doc.scans[0]])
    plot.start_grab()
    assert plot.is_artist(window.doc.arrow)
    assert not plot.is_artist(window.doc.scans[0])
    # X is offered for artists only; a scan's grab stays a y move.
    plot._move["axis"] = None
    plot._update_move(QPointF(plot.width() / 2, plot.height() / 2))
    assert window.doc.scans[0].offset != 0.0
    plot._finish_move(cancel=True)


def test_a_drag_on_empty_space_is_a_box_select(window):
    plot = window.plot
    plot.grab()
    corner = (plot.plot_rect().left() + 4, plot.plot_rect().top() + 4)
    far = (plot.plot_rect().right() - 4, plot.plot_rect().bottom() - 4)
    plot.mousePressEvent(_press(plot, corner))
    assert plot._box is not None
    plot.mouseMoveEvent(_move(plot, far))
    plot.mouseReleaseEvent(_release(plot, far))
    assert plot._box is None
    assert len(window.doc.selected_scans()) == 2       # everything drawn
    # ...and a box over nothing clears it again
    empty = (plot.plot_rect().left() + 2, plot.plot_rect().top() + 2)
    plot.mousePressEvent(_press(plot, empty))
    plot.mouseMoveEvent(_move(plot, (empty[0] + 6, empty[1] + 6)))
    plot.mouseReleaseEvent(_release(plot, (empty[0] + 6, empty[1] + 6)))
    assert window.doc.selected_scans() == []


def test_removing_a_file_can_be_undone(window, sample):
    assert len(window.doc.scans) == 2
    window.remove_sample(sample)
    assert window.doc.scans == []
    assert sample in window.doc.samples        # the file stays open
    window.undo.undo()
    assert len(window.doc.scans) == 2
    assert window.doc.scans[0].sample is sample


def test_the_keys_are_the_ones_he_asked_for(window):
    keys = {op.id: op.key for op in window.ops.all()}
    assert keys["select.all"] == "Ctrl+A"
    assert keys["arrange.reset"] == "R"
    assert keys["transform.grab"] == "G"


def test_r_resets_the_selection_then_everything(window):
    for scan in window.doc.scans:
        scan.offset = 2.0
    window.doc.select_only([window.doc.scans[0]])
    window.run_op("arrange.reset")
    assert window.doc.scans[0].offset == 0.0
    assert window.doc.scans[1].offset == 2.0
    window.select_all(False)
    window.run_op("arrange.reset")
    assert all(s.offset == 0.0 for s in window.doc.scans)


def test_the_theme_changes_what_is_drawn(window):
    from dscpanel.ui import plot as plot_module
    window.set_theme(plot_module.THEME_LIGHT)
    assert window.doc.theme == plot_module.THEME_LIGHT
    assert plot_module._BG.lightness() > 200
    window.plot.grab()
    window.set_theme(plot_module.THEME_DARK)
    assert plot_module._BG.lightness() < 80
    # an export is light whatever the screen is
    with plot_module.paper_palette(window.plot, True):
        assert plot_module._BG.lightness() > 200
    assert plot_module._BG.lightness() < 80


def _wheel(pixels=(0, 0), angles=(0, 0), mods=Qt.NoModifier, at=(200, 200)):
    from PySide6.QtGui import QWheelEvent
    return QWheelEvent(QPointF(*at), QPointF(*at), QPoint(*pixels),
                       QPoint(*angles), Qt.NoButton, mods,
                       Qt.NoScrollPhase, False)


def test_a_plain_swipe_scales_the_y_axis(window):
    """The gesture that is used constantly on a stack: two fingers, no
    modifier, and the y axis opens or closes about the cursor."""
    plot = window.plot
    plot.grab()
    before_x = plot.view_x()
    span_before = plot.view_y()[1] - plot.view_y()[0]
    plot.wheelEvent(_wheel(pixels=(0, 40)))
    assert plot.view_y()[1] - plot.view_y()[0] != span_before   # scaled
    assert plot.view_x() == before_x                            # x untouched


def test_shift_turns_the_swipe_into_an_omnidirectional_pan(window):
    plot = window.plot
    plot.grab()
    before_x, before_y = plot.view_x(), plot.view_y()
    span_x = before_x[1] - before_x[0]
    span_y = before_y[1] - before_y[0]
    plot.wheelEvent(_wheel(pixels=(30, 40), mods=Qt.ShiftModifier))
    assert plot.view_x() != before_x and plot.view_y() != before_y
    # a pan moves the framing and keeps the spans, which is the whole point
    assert plot.view_x()[1] - plot.view_x()[0] == pytest.approx(span_x)
    assert plot.view_y()[1] - plot.view_y()[0] == pytest.approx(span_y)


def test_ctrl_is_the_pinch_and_zooms_both_axes(window):
    plot = window.plot
    plot.grab()
    span_x = plot.view_x()[1] - plot.view_x()[0]
    span_y = plot.view_y()[1] - plot.view_y()[0]
    plot.wheelEvent(_wheel(angles=(0, 120), mods=Qt.ControlModifier))
    assert plot.view_x()[1] - plot.view_x()[0] < span_x
    assert plot.view_y()[1] - plot.view_y()[0] < span_y


# ------------------------------------------------- analyses as objects
def test_analyses_are_off_until_they_are_ticked(window):
    """A run carries a dozen stored analyses; a figure wants one or two."""
    scan = window.doc.scans[0]
    scan._analyses = None
    scan.sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C #1": {
            "Onset point": [{"segment": 1, "Onset x": "61,08 °C",
                             "Onset cursor x": "53,40 °C"}],
            "Glass transition": [{"segment": 1, "Midpoint": "78,91 °C",
                                  "Onset cursor x": "63,19 °C"}]}}
    analyses = scan.analysis_objects
    assert len(analyses) == 2
    assert not any(a.visible for a in analyses)
    assert window.plot.traces and not window.doc.visible_analyses()
    window.plot.grab()
    assert window.plot._analysis_boxes == []
    analyses[0].visible = True
    window.refresh()
    window.plot.grab()
    assert len(window.plot._analysis_boxes) == 1


def test_an_analysis_says_how_sure_its_attribution_is(window):
    scan = window.doc.scans[0]
    scan._analyses = None
    scan.sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C": {           # no segment: a .txt export
            "Onset point": [{"Onset x": "61,08 °C"}]}}
    analysis = scan.analysis_objects[0]
    assert analysis.attribution == "by step name"
    assert not analysis.certain
    assert analysis.summary().startswith("Onset 61.1")


def test_an_analysis_can_be_moved_to_another_scan(window):
    first, second = window.doc.scans[0], window.doc.scans[1]
    first._analyses = None
    first.sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C": {
            "Onset point": [{"Onset x": "61,08 °C"}]}}
    analysis = first.analysis_objects[0]
    analysis.reassign(second)
    assert analysis.scan is second
    assert analysis in second.analysis_objects
    assert analysis not in first.analysis_objects
    assert analysis.attribution == "moved by hand"


def test_show_and_hide_every_analysis_is_one_undo_step(window):
    scan = window.doc.scans[0]
    scan._analyses = None
    scan.sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C #1": {
            "Onset point": [{"segment": 1, "Onset x": "61,08 °C"}],
            "Peak Integration (enthalpy)": [
                {"segment": 1, "Peak temperature": "88,84 °C",
                 "Enthalpy (normalized)": "13,26 J/g"}]}}
    window.doc.select_only([scan])
    window.run_op("analysis.show")
    assert all(a.visible for a in scan.analysis_objects)
    assert window.undo.depth() == 1
    window.undo.undo()
    assert not any(a.visible for a in scan.analysis_objects)


def test_the_session_remembers_which_analyses_were_on(window, tmp_path,
                                                      sample):
    from dscpanel.core import session
    scan = window.doc.scans[0]
    scan._analyses = None
    scan.sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C #1": {
            "Onset point": [{"segment": 1, "Onset x": "61,08 °C",
                             "Onset cursor x": "53,40 °C"}]}}
    scan.analysis_objects[0].visible = True
    scan.analysis_objects[0].label = "the one that matters"
    path = tmp_path / "figure.dscpanel"
    session.save(window.doc, str(path))
    reopened, problems = session.load(
        str(path), lambda _p: model.Sample(sample.path, sample.data))
    assert not problems
    restored = reopened.scans[0].analysis_objects[0]
    assert restored.visible
    assert restored.label == "the one that matters"


def test_the_y_scale_knob_is_gone(window):
    scan = window.doc.scans[0]
    assert not hasattr(scan, "y_scale")
    assert not hasattr(scan, "is_scaled")
    assert not hasattr(window.doc, "scaled_scans")


def test_a_touchpad_that_reports_notches_behaves_the_same(window):
    """This machine's touchpad sends wheel notches rather than pixel deltas.
    Reading those as "a mouse wheel" is what made Shift+swipe zoom instead of
    panning, so the two paths have to agree."""
    plot = window.plot
    plot.grab()
    before_x, before_y = plot.view_x(), plot.view_y()
    span_y = before_y[1] - before_y[0]
    plot.wheelEvent(_wheel(angles=(0, 120), mods=Qt.ShiftModifier))
    assert plot.view_y() != before_y
    assert plot.view_y()[1] - plot.view_y()[0] == pytest.approx(span_y)
    assert plot.view_x() == before_x        # nothing horizontal was sent
    # ...and without the modifier the same event scales y instead
    span_y = plot.view_y()[1] - plot.view_y()[0]
    plot.wheelEvent(_wheel(angles=(0, 120)))
    assert plot.view_y()[1] - plot.view_y()[0] != pytest.approx(span_y)


def test_a_not_shown_segment_row_is_safe_to_select(fresh_window):
    """The crash Christian hit: hide the only visible scan, then click a
    segment that is not on the plot.

    Those rows carry a three-part key, `("segment", sample id, seg)`, and
    `_object` unpacked it into two - a ValueError raised inside a Qt slot,
    which PySide6 turns into an abort with no traceback. Every path that
    touches a row has to tolerate all three key shapes.
    """
    window = fresh_window
    # the state he was in: the only shown scan hidden, one segment not shown
    window.doc.scans[0].visible = False
    tree = window.outliner
    tree.refill()
    row = tree.topLevelItem(0)
    keys = [tree._key(row.child(i)) for i in range(row.childCount())]
    assert any(key[0] == "segment" for key in keys)
    for i in range(row.childCount()):
        item = row.child(i)
        assert tree._object(item) is not None or tree._key(item)[0] == "segment"
        item.setSelected(True)
        tree._selection_changed()            # the slot that aborted
        # NOT `tree._menu(...)`: that shows a QMenu, and a modal exec in a
        # test hangs rather than fails. The window builds menus separately
        # for exactly this reason - see `_context_menu`.
        window._scan_menu(QMenu(window), window.doc.scans[0])


# ----------------------------------------- the figure, as the plotter draws it
def test_no_grid_and_the_template_captions_by_default(window):
    from dscpanel.ui import plot as plot_module
    doc = window.doc
    assert doc.axes["x"].show_grid is False
    assert doc.axes["y"].show_grid is False
    assert doc.axes["x"].minor_ticks and doc.axes["x"].ticks_inward
    # `*` marks italic: the quantity symbol is cursive, the unit is not
    from dscpanel.ui.plot import markup_runs
    runs = markup_runs(doc.axes["x"].caption(doc))
    assert runs[0] == ("T", True, False)       # italic, not a subscript
    assert any(part.strip().endswith("°C") for part, _i, _s in runs)
    assert doc.axes["y"].caption(doc).startswith("Heat Flow")
    assert "W/g" in doc.axes["y"].caption(doc)
    window.plot.grab()
    assert plot_module.THEME                      # painted without raising


def test_an_axis_caption_cannot_be_dragged_onto_the_data(window):
    plot = window.plot
    plot.grab()
    axis = window.doc.axes["y"]
    axis.label_gap = 10000.0                      # shove it at the plot
    axis.label_along = 5.0
    box = plot.axis_label_rect(axis)
    assert box.right() <= plot.plot_rect().left()
    assert box.top() >= -1


def test_an_axis_caption_is_a_double_click_target(window):
    plot = window.plot
    plot.grab()
    axis = window.doc.axes["x"]
    centre = plot.axis_label_rect(axis).center()
    assert plot.object_at(centre) is axis
    # The window's own handler opens a MODAL dialog, which would hang the
    # test, so it is taken off for the duration - the point here is that the
    # double-click finds the axis and asks for it to be opened.
    plot.activated.disconnect(window.edit_object)
    seen = []
    plot.activated.connect(seen.append)
    plot.mouseDoubleClickEvent(_press(plot, (centre.x(), centre.y())))
    plot.mouseReleaseEvent(_release(plot, (centre.x(), centre.y())))
    assert seen == [axis]
    plot.activated.connect(window.edit_object)


def test_dragging_an_analysis_moves_only_its_label_vertically(window):
    scan = window.doc.scans[0]
    scan._analyses = None
    scan.sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C #1": {
            "Onset point": [{"segment": 1, "Onset x": "120,0 °C"}]}}
    analysis = scan.analysis_objects[0]
    analysis.visible = True
    window.refresh()
    plot = window.plot
    plot.grab()
    assert plot._analysis_boxes, "the label has to be drawn to be dragged"
    box = plot._analysis_boxes[0][1]
    assert analysis.label_dy is None          # the automatic side, so far
    before = plot.effective_label_dy(analysis)
    start = (box.center().x(), box.center().y())
    _double_drag(plot, start, (start[0] + 80, start[1] - 30))
    assert analysis.label_dy == pytest.approx(before - 30)   # vertical only
    assert window.undo.can_undo()
    window.undo.undo()
    assert plot.effective_label_dy(analysis) == pytest.approx(before)


def test_an_integration_is_shaded(window):
    scan = window.doc.scans[0]
    scan._analyses = None
    scan.sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C #1": {
            "Peak Integration (enthalpy)": [
                {"segment": 1, "Peak temperature": "120,0 °C",
                 "Enthalpy (normalized)": "13,3 J/g",
                 "Baseline cursor x": "80,0 °C",
                 "Baseline cursor x1": "160,0 °C"}]}}
    analysis = scan.analysis_objects[0]
    assert analysis.shade
    analysis.visible = True
    window.refresh()
    window.plot.grab()                    # the shading path runs
    assert window.plot._analysis_boxes


def test_a_label_is_an_object_you_add_move_and_keep(window, tmp_path, sample):
    from dscpanel.core import session
    label = window.add_label("first heating", at=QPointF(300, 200))
    assert label in window.doc.labels
    assert window.undo.can_undo()
    window.plot.grab()
    assert any(item[0] is label for item in window.plot._text_boxes)
    box = [b for lb, b in window.plot._text_boxes if lb is label][0]
    start = (box.center().x(), box.center().y())
    plot = window.plot
    before = (label.x, label.y)
    _double_drag(plot, start, (start[0] + 40, start[1] + 25))
    assert label.x > before[0] and label.y > before[1]
    path = tmp_path / "with-label.dscpanel"
    session.save(window.doc, str(path))
    reopened, _problems = session.load(
        str(path), lambda _p: model.Sample(sample.path, sample.data))
    assert [lb.text for lb in reopened.labels] == ["first heating"]


def test_typing_a_number_moves_the_selection_without_g(window):
    plot = window.plot
    from PySide6.QtGui import QKeyEvent
    window.doc.select_only([window.doc.scans[0]])
    for text, key in (("0", Qt.Key_0), (".", Qt.Key_Period), ("4", Qt.Key_4)):
        plot.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key,
                                     Qt.NoModifier, text))
    assert plot.moving()
    plot._finish_move()
    assert window.doc.scans[0].offset == pytest.approx(0.4)


def test_trace_names_appear_only_on_hover_or_selection(window):
    plot = window.plot
    window.select_all(False)
    plot._cursor = None
    plot.grab()
    assert plot._label_boxes == []
    window.doc.scans[0].selected = True
    plot.grab()
    assert len(plot._label_boxes) == 1


def test_the_trace_menu_stays_short(window):
    """Settings, the molar mass, and adding a label to this line. Nothing
    else: everything else lives in the outliner, the menus or F3."""
    from PySide6.QtWidgets import QMenu
    menu = QMenu(window)
    window._scan_menu(menu, window.doc.scans[0])
    labels = [a.text() for a in menu.actions() if a.text()]
    assert len(labels) == 3
    assert any("Settings for" in text for text in labels)
    assert any("molar mass" in text.lower() for text in labels)
    assert any("label" in text.lower() for text in labels)


# ------------------------------------------- measuring inside the panel
def test_the_gizmo_flow_places_two_cursors_and_asks(window):
    """Click, click, Enter - the TRIOS gesture, with a quick-select at the
    end instead of a dialog full of tabs."""
    plot = window.plot
    plot.grab()
    scan = window.doc.scans[0]
    window.doc.select_only([scan])
    assert plot.start_measure()
    state = plot.measuring()
    assert state["scan"] is scan and state["cursors"] == []
    rect = plot.plot_rect()
    plot.measure_place(QPointF(rect.left() + 60, rect.center().y()))
    plot.measure_place(QPointF(rect.left() + 200, rect.center().y()))
    assert len(plot.measuring()["cursors"]) == 2
    # The window answers this signal with a MODAL palette, which would hang
    # the test, so it is taken off for the duration.
    plot.measure_ready.disconnect(window._measure_ready)
    asked = []
    plot.measure_ready.connect(lambda *args: asked.append(args))
    plot.measure_confirm()
    assert len(asked) == 1
    scan_out, x0, x1, editing = asked[0]
    assert scan_out is scan and editing is None and x0 < x1
    plot.grab()                                   # the crosshairs draw


def test_escape_walks_back_through_the_measurement(window):
    plot = window.plot
    plot.grab()
    window.doc.select_only([window.doc.scans[0]])
    plot.start_measure()
    plot.measure_place(value=80.0)
    plot.measure_place(value=120.0)
    plot.measuring()["typed"] = "13"
    plot.measure_back()
    assert plot.measuring()["typed"] == ""        # the number first
    plot.measure_back()
    assert len(plot.measuring()["cursors"]) == 1  # then a cursor
    plot.measure_back()
    assert plot.measuring()["cursors"] == []
    plot.measure_back()
    assert plot.measuring() is None               # then the gesture itself


def test_a_typed_temperature_is_read_in_the_axis_unit(window):
    from dscpanel.core import units as core_units
    plot = window.plot
    window.doc.select_only([window.doc.scans[0]])
    window.set_x_unit(core_units.TEMP_K)
    plot.start_measure()
    plot.measure_place(value=400.0)               # 400 K
    assert plot.measuring()["cursors"][0] == pytest.approx(126.85, abs=0.01)
    window.set_x_unit(core_units.TEMP_C)


def test_measuring_reproduces_what_trios_computed(real_tri):
    """The panel's own integration against the one in the file: same cursors,
    same arithmetic, so the numbers have to agree."""
    from dscpanel.core import loader as core_loader, measure
    sample = core_loader.read_sample(real_tri)
    doc = model.Document()
    doc.add_sample(sample, list(range(sample.segment_count())))
    for scan in doc.scans:
        for entry in scan.analyses():
            if "Integration" not in str(entry.get("Model", "")):
                continue
            stored = model.number(entry.get("Enthalpy (normalized)"))
            x0 = model.number(entry.get("Baseline cursor x"))
            x1 = model.number(entry.get("Baseline cursor x1"))
            if None in (stored, x0, x1):
                continue
            made = measure.run("Peak Integration (enthalpy)", scan, x0, x1)
            assert made is not None
            assert made.source == "panel"
            assert made.attribution == "measured here"
            assert model.number(
                made.fields["Enthalpy (normalized)"]) == pytest.approx(
                    stored, rel=0.02)
            return
    pytest.skip("no decoded integration in this file")


def test_double_clicking_a_measured_analysis_reopens_its_cursors(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    window.doc.select_only([scan])
    analysis = measure.run("Peak Integration (enthalpy)", scan, 60.0, 180.0)
    assert analysis is not None
    window.refresh()
    plot = window.plot
    plot.grab()
    box = [b for a, b in plot._analysis_boxes if a is analysis]
    assert box, "a measured analysis is drawn like any other"
    centre = box[0].center()
    # Opening an analysis also opens its settings, which is modal - off for
    # the test, since what is checked here is that the cursors come back.
    plot.activated.disconnect(window.edit_object)
    # The cursors come back on the RELEASE of a double-click that did not
    # move - a double-click-DRAG moves the label instead.
    plot.mouseDoubleClickEvent(_double(plot, (centre.x(), centre.y())))
    plot.mouseReleaseEvent(_release(plot, (centre.x(), centre.y())))
    plot.activated.connect(window.edit_object)
    state = plot.measuring()
    assert state is not None and state["editing"] is analysis
    assert len(state["cursors"]) == 2


def test_the_x_axis_can_be_kelvin_or_fahrenheit(window):
    from dscpanel.core import units as core_units
    scan = window.doc.scans[0]
    x_c = scan.curve(window.doc.x_axis, window.doc.y_unit, window.doc.exo)[0]
    window.set_x_unit(core_units.TEMP_K)
    x_k = scan.curve(window.doc.x_axis, window.doc.y_unit, window.doc.exo,
                     core_units.TEMP_K)[0]
    assert x_k[0] == pytest.approx(x_c[0] + 273.15)
    assert "K" in window.doc.axes["x"].caption(window.doc)
    window.set_x_unit(core_units.TEMP_F)
    x_f = scan.curve(window.doc.x_axis, window.doc.y_unit, window.doc.exo,
                     core_units.TEMP_F)[0]
    assert x_f[0] == pytest.approx(x_c[0] * 9.0 / 5.0 + 32.0)
    window.set_x_unit(core_units.TEMP_C)


def test_bigger_numbers_widen_the_margin_instead_of_being_cut_off(window):
    plot = window.plot
    plot.grab()
    narrow = plot.margins()[0]
    window.doc.axes["y"].tick_size = 22.0
    window.doc.axes["y"].label_size = 22.0
    plot.invalidate()
    plot.grab()
    assert plot.margins()[0] > narrow
    assert plot.plot_rect().left() == plot.margins()[0]


def test_a_downward_peak_labels_from_below(window):
    """A negative integral must not have its arrow crossing the shading."""
    scan = window.doc.scans[0]
    scan._analyses = None
    scan.sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C #1": {
            "Peak Integration (enthalpy)": [
                {"segment": 1, "Peak temperature": "120,0 °C",
                 "Enthalpy (normalized)": "13,3 J/g",
                 "Baseline cursor x": "80,0 °C",
                 "Baseline cursor x1": "160,0 °C"}]}}
    analysis = scan.analysis_objects[0]
    analysis.visible = True
    window.refresh()
    plot = window.plot
    plot.grab()
    trace = [t for t in plot.traces if t.scan is scan][0]
    up = plot.peak_points_up(analysis, trace)
    offset = plot.label_offset(analysis, trace, plot.plot_rect())
    assert (offset < 0) == up          # label on the side the peak is not


# --------------------------------------------- round 5: the reported faults
def test_enter_is_not_stolen_by_the_settings_dialog(window):
    """Christian's catch: a window-level QAction on Return fired before the
    plot saw the key, so confirming a measurement opened the scan settings."""
    keys = {op.id: op.key for op in window.ops.all()}
    assert keys["object.settings"] == ""
    assert "Return" not in window.ops.duplicate_keys()
    for op in window.ops.all():
        assert op.key not in ("Return", "Enter")


def test_f3_can_run_the_analysis_once_both_cursors_are_down(window):
    op = window.ops.get("measure.apply")
    assert op is not None
    assert not op.enabled(window)                 # nothing measured yet
    window.doc.select_only([window.doc.scans[0]])
    window.plot.start_measure()
    window.plot.measure_place(value=60.0)
    assert not op.enabled(window)                 # one cursor is not enough
    window.plot.measure_place(value=120.0)
    assert op.enabled(window)
    assert window.ops.get("measure.cancel").enabled(window)


def test_tick_numbers_get_the_room_their_font_needs(window):
    plot = window.plot
    plot.grab()
    small = plot.margins()
    window.doc.axes["x"].tick_size = 20.0
    window.doc.axes["y"].tick_size = 20.0
    plot.invalidate()
    plot.grab()
    big = plot.margins()
    assert big[0] > small[0]        # left, for the y numbers
    assert big[3] > small[3]        # bottom, for the x numbers


def test_the_spine_opens_the_axis_and_the_caption_opens_the_caption(window):
    plot = window.plot
    plot.grab()
    axis = window.doc.axes["x"]
    caption = plot.axis_label_rect(axis).center()
    assert plot.object_at(caption) is axis
    assert plot.axis_hit() == "caption"
    spine = plot.axis_spine_rect("x").center()
    assert plot.object_at(spine) is axis
    assert plot.axis_hit() == "spine"
    # ...and the spine band never reaches into the plot itself
    assert plot.axis_spine_rect("y").right() < plot.plot_rect().left()
    assert plot.axis_spine_rect("x").top() > plot.plot_rect().bottom()


def test_a_measured_analysis_arrives_with_a_label(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    made = measure.run("Onset point", scan, 60.0, 120.0)
    assert made is not None
    assert made.label and "=" in made.label
    from dscpanel.ui.plot import markup_runs
    runs = markup_runs(made.label)
    assert ("T", True, False) in runs             # italic quantity symbol
    assert any(subscript for _t, _i, subscript in runs)   # and a subscript


def test_the_quick_list_shows_short_names(window):
    from dscpanel.core import measure
    titles = [entry.title for entry in measure.MODELS]
    assert "Onset" in titles and "Integration" in titles
    assert "Peak Integration (enthalpy)" not in titles
    # ...while the model string is what is stored
    assert measure.by_name("Peak Integration (enthalpy)") is not None


def test_nothing_is_drawn_outside_the_axes(window, tmp_path):
    """Zooming in leaves points off both sides; they must be clipped, not
    painted over the numbers and the caption."""
    plot = window.plot
    plot.grab()
    lo, hi = plot.view_x()
    plot.set_view_x(lo + 0.4 * (hi - lo), lo + 0.5 * (hi - lo))
    image = plot.grab().toImage()
    rect = plot.plot_rect()
    ratio = image.devicePixelRatio() or 1.0
    background = image.pixelColor(int(4 * ratio), int(2 * ratio))
    # the strip ABOVE the axes carries nothing at all, so a curve drawn past
    # the frame shows up here and nowhere else
    for x in range(rect.left() + 5, rect.right() - 5, 23):
        pixel = image.pixelColor(int(x * ratio), int(2 * ratio))
        assert pixel == background


# ------------------------------------------------- round 6: artists, cursors
def test_every_artist_carries_a_position_and_an_anchor(window):
    from dscpanel.core import model as core_model
    arrow = window.doc.arrow
    label = window.add_label("note")
    for artist in (arrow, label):
        assert isinstance(artist, core_model.Artist)
        assert artist.space == core_model.SPACE_RELATIVE
        assert artist.anchor in core_model.ANCHORS
        assert artist.anchor_offsets() == (0.5, 0.5)
    # the capabilities are per kind, and the dialogs read them
    assert label.can_scale and not label.can_rotate
    assert not arrow.can_scale and not arrow.can_rotate


def test_an_artist_keeps_its_place_when_the_space_changes(window):
    from dscpanel.core import model as core_model
    plot = window.plot
    plot.grab()
    label = window.add_label("note")
    label.set_position(0.3, 0.4)
    before = plot.artist_point(label)
    plot.convert_artist_space(label, core_model.SPACE_DATA)
    assert label.space == core_model.SPACE_DATA
    after = plot.artist_point(label)
    assert after[0] == pytest.approx(before[0], abs=1.0)
    assert after[1] == pytest.approx(before[1], abs=1.0)
    # ...and a data-space artist follows the view, which is the point
    lo, hi = plot.view_x()
    plot.set_view_x(lo, lo + 0.5 * (hi - lo))
    assert plot.artist_point(label)[0] != pytest.approx(after[0], abs=1.0)


def test_an_anchor_moves_where_the_artist_is_drawn(window):
    plot = window.plot
    label = window.add_label("note")
    label.set_position(0.5, 0.5)
    window.refresh()
    plot.grab()
    centred = [b for lb, b in plot._text_boxes if lb is label][0]
    label.anchor = "left"
    plot.invalidate()
    plot.grab()
    left = [b for lb, b in plot._text_boxes if lb is label][0]
    assert left.left() > centred.left()


def test_a_measure_cursor_can_be_picked_up_and_dragged(window):
    plot = window.plot
    plot.grab()
    window.doc.select_only([window.doc.scans[0]])
    plot.start_measure()
    plot.measure_place(value=80.0)
    plot.measure_place(value=140.0)
    plot.grab()
    rect = plot.plot_rect()
    x = plot.x_to_px(80.0, rect)
    index = plot.cursor_at(QPointF(x, rect.center().y()))
    assert index == 0
    plot.start_cursor_drag(index, QPointF(x, rect.center().y()))
    plot.drag_cursor(QPointF(x + 40, rect.center().y()))
    plot.end_cursor_drag()
    assert plot.measuring()["cursors"][0] > 80.0
    assert plot.measuring()["cursors"][1] == pytest.approx(140.0)


def test_re_measuring_keeps_the_model_and_needs_no_palette(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    window.doc.select_only([scan])
    first = measure.run("Onset point", scan, 60.0, 120.0)
    window.refresh()
    # the window is handed the analysis being edited, so it does not ask
    again = window._measure_ready(scan, 65.0, 125.0, first)
    assert again is not None
    assert again.model_name == first.model_name
    assert first not in scan.analysis_objects
    assert again in scan.analysis_objects


def test_delete_removes_a_selected_analysis_not_its_scan(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    analysis = measure.run("Onset point", scan, 60.0, 120.0)
    window.refresh()
    window.doc.select_only([analysis])
    assert window.ops.get("object.remove").enabled(window)
    window.run_op("object.remove")
    assert analysis not in scan.analysis_objects
    assert scan in window.doc.scans            # the curve is untouched
    window.undo.undo()
    assert analysis in scan.analysis_objects


def test_an_analysis_marks_its_interval_unless_told_not_to(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    analysis = measure.run("Peak Integration (enthalpy)", scan, 70.0, 150.0)
    assert analysis.show_interval
    window.refresh()
    plot = window.plot
    plot.grab()                                 # draws them
    analysis.show_interval = False
    plot.invalidate()
    plot.grab()                                 # and does not


def test_the_plain_cursor_is_a_reticle_not_a_line(window):
    plot = window.plot
    rect = plot.plot_rect()
    plot._cursor = QPointF(rect.center())
    image = plot.grab().toImage()
    ratio = image.devicePixelRatio() or 1.0
    centre = rect.center()
    # a ring: the pixels well above and below the centre differ from the ones
    # immediately around it, and nothing is drawn at the top of the plot
    top = image.pixelColor(int(centre.x() * ratio), int((rect.top() + 3) * ratio))
    background = image.pixelColor(int((rect.left() + 3) * ratio),
                                 int((rect.top() + 3) * ratio))
    assert top == background          # the old dashed line ran the full height


# ------------------------------------------------ round 7: labels on a line
def test_a_label_can_belong_to_a_line(window, tmp_path, sample):
    from dscpanel.core import session
    scan = window.doc.scans[0]
    scan.colour = "#ff8800"
    label = window.add_label("second heating", at=QPointF(400, 300),
                             scan=scan)
    assert label.scan is scan
    assert window.doc.labels_for(scan) == [label]
    # an owned label wears its line's colour while its own is automatic
    assert window.plot.label_colour(label).name() == "#ff8800"
    label.colour = "#00ff00"
    assert window.plot.label_colour(label).name() == "#00ff00"
    # ...and it is listed under the scan in the outliner
    window.refresh()
    row = window.outliner.topLevelItem(0).child(0)
    texts = [row.child(i).text(0) for i in range(row.childCount())]
    assert "second heating" in texts
    # ...and survives a save and reopen, still attached
    path = tmp_path / "owned.dscpanel"
    session.save(window.doc, str(path))
    reopened, _problems = session.load(
        str(path), lambda _p: model.Sample(sample.path, sample.data))
    restored = reopened.labels[0]
    assert restored.text == "second heating"
    assert restored.scan is not None and restored.scan.seg == scan.seg


def test_removing_a_line_takes_its_labels_and_undo_brings_them_back(window):
    scan = window.doc.scans[0]
    label = window.add_label("note", at=QPointF(400, 300), scan=scan)
    window.remove_scans([scan])
    assert label not in window.doc.labels
    window.undo.undo()
    assert label in window.doc.labels
    assert label.scan is scan


def test_the_interval_marker_sits_on_the_curve(window):
    """Not two dashed lines down to the axis: a short bracket on the line."""
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    analysis = measure.run("Peak Integration (enthalpy)", scan, 70.0, 150.0)
    window.refresh()
    plot = window.plot
    image = plot.grab().toImage()
    ratio = image.devicePixelRatio() or 1.0
    rect = plot.plot_rect()
    background = image.pixelColor(int((rect.left() + 3) * ratio),
                                 int((rect.bottom() - 3) * ratio))
    # just above the x axis, between the cursors, nothing is drawn any more
    x = plot.x_to_px(plot.to_axis(70.0), rect)
    pixel = image.pixelColor(int(x * ratio), int((rect.bottom() - 4) * ratio))
    assert pixel == background
    assert analysis.show_interval


def test_the_settings_dialogs_do_not_block_the_plot(window):
    from dscpanel.ui.dialogs import ScanSettings
    dialog = ScanSettings(window, window.doc.scans[0], window.doc.y_unit)
    assert not dialog.isModal()
    dialog.close()


def test_the_pointer_is_hidden_where_the_reticle_is(window):
    plot = window.plot
    rect = plot.plot_rect()
    plot._cursor = QPointF(rect.center())
    plot._sync_pointer()
    assert plot.cursor().shape() == Qt.BlankCursor
    plot._cursor = QPointF(2, 2)                  # out in the margin
    plot._sync_pointer()
    assert plot.cursor().shape() == Qt.ArrowCursor
    plot.set_mode("zoom_h")                       # a mode brings its own
    assert plot.cursor().shape() != Qt.BlankCursor
    plot.set_mode(None)


# ------------------------------------------------------- the legend artist
def test_the_legend_is_an_artist_that_starts_off(window):
    from dscpanel.core import model as core_model
    legend = window.doc.legend
    assert isinstance(legend, core_model.Artist)
    assert legend.visible is False
    assert legend.can_scale and not legend.can_rotate
    assert legend.anchor == "bottom left"
    # ...and it is in the outliner, ticked off
    window.refresh()
    rows = [window.outliner.topLevelItem(i).text(0)
            for i in range(window.outliner.topLevelItemCount())]
    assert "Legend" in rows


def test_the_legend_names_the_scans_that_are_drawn(window):
    legend = window.doc.legend
    doc = window.doc
    assert [text for _scan, text in legend.entries(doc)] == [
        scan.display_name() for scan in doc.visible_scans()]
    # a renamed scan renames its entry, which is the point of using its label
    doc.scans[0].label = "second heating"
    assert "second heating" in [t for _s, t in legend.entries(doc)]
    doc.scans[0].visible = False
    assert len(legend.entries(doc)) == len(doc.scans) - 1


def test_the_legend_draws_moves_and_is_picked(window):
    plot = window.plot
    window.run_op("legend.toggle")
    assert window.doc.legend.visible
    assert window.undo.can_undo()
    plot.grab()
    box = plot.legend_rect()
    assert box is not None and box.width() > 20
    assert plot.object_at(box.center()) is window.doc.legend
    # double-click-dragged like any artist, and the drag is one undo step
    start = (box.center().x(), box.center().y())
    _double_drag(plot, start, (start[0] + 60, start[1] - 40))
    assert window.doc.legend.x != pytest.approx(0.02)
    window.undo.undo()
    assert window.doc.legend.x == pytest.approx(0.02)


def test_the_legend_is_kept_in_the_session(window, tmp_path, sample):
    from dscpanel.core import session
    legend = window.doc.legend
    legend.visible = True
    legend.size = 12.5
    legend.show_frame = False
    legend.set_position(0.7, 0.2)
    path = tmp_path / "legend.dscpanel"
    session.save(window.doc, str(path))
    reopened, _problems = session.load(
        str(path), lambda _p: model.Sample(sample.path, sample.data))
    assert reopened.legend.visible
    assert reopened.legend.size == pytest.approx(12.5)
    assert reopened.legend.show_frame is False
    assert reopened.legend.x == pytest.approx(0.7)


# ------------------------------- round 8: one press selects, two act on it
def _on_the_heating_curve(window, fractions=(0.3, 0.6)):
    """Two points ON the first scan's drawn curve, with the second scan moved
    well out of the way so picking cannot land on it."""
    plot = window.plot
    window.doc.scans[1].offset = 5.0
    window.refresh()
    plot.grab()
    trace = [t for t in plot.traces if t.scan is window.doc.scans[0]][0]
    points = []
    for fraction in fractions:
        index = int(len(trace.px) * fraction)
        points.append((float(trace.px[index]), float(trace.py[index])))
    return points


def _answer(window, chosen):
    """Stand in for the quick list, which is modal and would hang a test."""
    asked = []

    def ask(x0, x1):
        asked.append((x0, x1))
        return chosen
    window.ask_analysis = ask
    return asked


def test_a_double_click_drag_on_a_curve_marks_an_interval_and_asks(window):
    plot = window.plot
    start, end = _on_the_heating_curve(window)
    # the hand wanders off the line while dragging; only x counts
    end = (end[0], end[1] + 25)
    plot.measure_ready.disconnect(window._measure_ready)
    asked = []

    def ready(*args):
        asked.append(args)
    plot.measure_ready.connect(ready)
    try:
        _double_drag(plot, start, end, release=False)
        assert plot.interval() is not None
        assert plot.measuring()["gesture"]
        plot.grab()                          # the span and crosshairs draw
        assert asked == []                   # nothing is asked mid-drag
        plot.mouseReleaseEvent(_release(plot, end))
    finally:
        plot.measure_ready.disconnect(ready)
        plot.measure_ready.connect(window._measure_ready)
    assert len(asked) == 1
    scan, x0, x1, editing = asked[0]
    assert scan is window.doc.scans[0] and editing is None
    assert x0 == pytest.approx(plot._celsius_at(start[0]))
    assert x1 == pytest.approx(plot._celsius_at(end[0]))
    # ...and the curve did not move: marking is not dragging
    assert window.doc.scans[0].offset == 0.0
    assert window.undo.depth() == 0


@pytest.mark.parametrize("second_press", [True, False])
def test_letting_go_of_the_interval_finishes_the_analysis(window,
                                                          second_press):
    plot = window.plot
    scan = window.doc.scans[0]
    before = list(scan.analysis_objects)
    # Cleared FIRST: clearing refreshes the plot, and picking reads the
    # points of the last paint, which `_on_the_heating_curve` provides.
    window.undo.clear()
    start, end = _on_the_heating_curve(window)
    asked = _answer(window, "Peak Integration (enthalpy)")
    _double_drag(plot, start, end, second_press=second_press)
    assert len(asked) == 1
    made = [a for a in scan.analysis_objects if a not in before]
    assert len(made) == 1
    assert made[0].visible and made[0].source == "panel"
    assert "Integration" in made[0].model_name
    # nothing is left to confirm: no cursors, no interval, one undo step
    assert plot.measuring() is None
    assert plot.interval() is None
    assert window.undo.depth() == 1
    window.undo.undo()
    assert made[0] not in scan.analysis_objects


def test_cancelling_the_list_drops_the_interval(window):
    plot = window.plot
    scan = window.doc.scans[0]
    before = list(scan.analysis_objects)
    window.undo.clear()
    start, end = _on_the_heating_curve(window)
    asked = _answer(window, None)
    _double_drag(plot, start, end)
    assert len(asked) == 1                    # it was asked, and said no
    assert plot.measuring() is None
    assert list(scan.analysis_objects) == before
    assert window.undo.depth() == 0


def test_a_double_click_on_a_curve_that_does_not_move_opens_it(window):
    plot = window.plot
    start, _end = _on_the_heating_curve(window)
    plot.activated.disconnect(window.edit_object)
    seen = []

    def opened(obj):
        seen.append(obj)
    plot.activated.connect(opened)
    try:
        plot.mousePressEvent(_press(plot, start))
        plot.mouseReleaseEvent(_release(plot, start))
        plot.mouseDoubleClickEvent(_double(plot, start))
        plot.mouseReleaseEvent(_release(plot, start))
    finally:
        plot.activated.disconnect(opened)
        plot.activated.connect(window.edit_object)
    assert seen == [window.doc.scans[0]]
    assert plot.measuring() is None


def test_escape_drops_an_interval_mid_drag(window):
    from PySide6.QtGui import QKeyEvent
    plot = window.plot
    start, end = _on_the_heating_curve(window)
    asked = _answer(window, "Onset point")
    _double_drag(plot, start, end, release=False)
    plot.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape,
                                 Qt.NoModifier))
    assert plot.interval() is None and plot.measuring() is None
    plot.mouseReleaseEvent(_release(plot, end))
    assert asked == []


def test_a_click_on_a_selected_curve_only_selects_it(window):
    """It used to start a measurement, which made a plain click mean two
    different things depending on what was already selected."""
    plot = window.plot
    start, _end = _on_the_heating_curve(window)
    scan = window.doc.scans[0]
    window.doc.select_only([scan])
    plot.mousePressEvent(_press(plot, start))
    plot.mouseReleaseEvent(_release(plot, start))
    assert plot.measuring() is None
    assert window.doc.selected_scans() == [scan]


def test_a_click_inside_a_selection_makes_it_the_only_one(window):
    plot = window.plot
    start, _end = _on_the_heating_curve(window)
    window.select_all(True)
    plot.mousePressEvent(_press(plot, start))
    plot.mouseReleaseEvent(_release(plot, start))
    assert window.doc.selected() == [window.doc.scans[0]]


def test_a_single_drag_on_the_arrow_moves_it(window):
    """Round 9: a drag that starts NEAR something acts on it - which is what
    a trackpad's tap-and-drag delivers, as one press."""
    plot = window.plot
    plot.grab()
    arrow = window.doc.arrow
    before = (arrow.x, arrow.y)
    start = plot._arrow_rect().center()
    end = (start.x() + 60, start.y() + 50)
    plot.mousePressEvent(_press(plot, (start.x(), start.y())))
    plot.mouseMoveEvent(_move(plot, end))
    plot.mouseReleaseEvent(_release(plot, end))
    assert arrow.x > before[0] and arrow.y > before[1]
    assert window.undo.undo_label() == "move arrow"


def test_a_measured_analysis_label_can_be_double_click_dragged(window):
    """Every new analysis is a panel one, and a panel analysis used to open
    its cursors on the double-click PRESS - so its label was the one label
    that could not be moved."""
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    analysis = measure.run("Peak Integration (enthalpy)", scan, 60.0, 180.0)
    window.refresh()
    plot = window.plot
    plot.grab()
    box = [b for a, b in plot._analysis_boxes if a is analysis][0]
    start = (box.center().x(), box.center().y())
    before = plot.effective_label_dy(analysis)
    _double_drag(plot, start, (start[0] + 20, start[1] - 30))
    assert analysis.label_dy == pytest.approx(before - 30)
    assert plot.measuring() is None           # it moved, so it did not open


def test_a_data_space_artist_follows_the_drag(window):
    """Its x and y are a temperature and a heat flow, and the drag clamped
    them into 0..1 as if they were fractions of the plot."""
    plot = window.plot
    plot.grab()                               # the plot at its real size
    label = window.add_label("note", at=QPointF(300, 200))
    plot.grab()
    plot.convert_artist_space(label, model.SPACE_DATA)
    window.refresh()
    plot.grab()
    before = plot.artist_point(label)
    box = [b for lb, b in plot._text_boxes if lb is label][0]
    start = (box.center().x(), box.center().y())
    _double_drag(plot, start, (start[0] + 40, start[1] + 25))
    after = plot.artist_point(label)
    assert after[0] == pytest.approx(before[0] + 40, abs=1.5)
    assert after[1] == pytest.approx(before[1] + 25, abs=1.5)


def test_no_interval_is_marked_on_a_time_axis(window):
    """The analyses take temperatures; a cursor on a time axis would be read
    as degrees and give a plausible nonsense."""
    plot = window.plot
    window.set_axis(model.AXIS_TIME)
    plot.grab()
    trace = plot.traces[0]
    index = len(trace.px) // 3
    start = (float(trace.px[index]), float(trace.py[index]))
    asked = _answer(window, "Onset point")
    _double_drag(plot, start, (start[0] + 80, start[1]))
    assert asked == [] and plot.measuring() is None


# ------------------------------------------------ flush, from DSC_Plotter
def test_flush_decides_which_edge_of_the_label_sits_on_its_arrow(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    analysis = measure.run("Peak Integration (enthalpy)", scan, 70.0, 150.0)
    window.refresh()
    plot = window.plot

    def drawn():
        plot.invalidate()
        plot.grab()
        return [b for a, b in plot._analysis_boxes if a is analysis][0]
    centred = drawn()
    x = plot.x_to_px(plot.to_axis(analysis.value()), plot.plot_rect())
    # an integral centres over its arrow, as `add_integral` does
    assert plot.analysis_flush(analysis) == "center"
    assert abs(centred.center().x() - x) <= 2
    analysis.flush = "left"                    # the text STARTS on the arrow
    assert abs(drawn().left() + 3 - x) <= 2
    analysis.flush = "right"                   # ...or ends on it
    assert abs(drawn().right() - 3 - x) <= 2


def test_a_tangent_construction_flushes_left_by_default(window):
    """`auto` is the template's own choice per artist: add_tangent and
    add_glass_transition flush left, add_integral centres."""
    from dscpanel.core import measure, style
    scan = window.doc.scans[0]
    onset = measure.run("Onset point", scan, 60.0, 120.0)
    assert onset.flush is None
    assert window.plot.analysis_flush(onset) == "left"
    window.doc.style.analysis_flush = style.FLUSH_RIGHT     # this figure
    assert window.plot.analysis_flush(onset) == "right"
    onset.flush = style.FLUSH_CENTER                        # this analysis
    assert window.plot.analysis_flush(onset) == "center"


def test_re_measuring_keeps_the_flush(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    first = measure.run("Onset point", scan, 60.0, 120.0)
    first.flush = "right"
    first.label_size = 12.0
    again = window._measure_ready(scan, 65.0, 125.0, first)
    assert again.flush == "right" and again.label_size == 12.0


# ---------------------------------------------- the house style, in a window
def test_the_settings_page_changes_the_default_live(window):
    from dscpanel.core import style
    from dscpanel.ui.settings import SettingsDialog
    plot = window.plot
    axis = window.doc.axes["y"]
    plot.grab()
    narrow = plot.margins()[0]
    dialog = SettingsDialog(window)
    assert not dialog.isModal()
    dialog.set_default("tick_size", 20.0)
    assert style.value(window.doc, axis, "tick_size") == 20.0
    plot.grab()
    assert plot.margins()[0] > narrow          # the plot follows at once
    dialog.reject()                            # Cancel puts it back
    assert style.preference("tick_size") == 8.0


def test_the_settings_page_saves_the_defaults_and_undoes_the_figure(
        window, own_preferences):
    from dscpanel.core import style
    from dscpanel.ui.settings import SettingsDialog
    dialog = SettingsDialog(window)
    dialog.set_default("analysis_size", 11.0)
    dialog.figure["legend_size"].box.setValue(14.0)     # typed: this figure
    assert window.doc.style.legend_size == 14.0
    window.undo.clear()
    dialog.accept()
    # the default is on disk, where the next start will find it
    style.restore_preferences({})
    style.load_preferences(own_preferences)
    assert style.preference("analysis_size") == 11.0
    # the figure's own choice is one undo step
    assert window.doc.style.legend_size == 14.0
    assert window.undo.depth() == 1
    window.undo.undo()
    assert window.doc.style.legend_size is None


def test_an_object_dialog_can_give_a_size_back_to_the_default(window):
    from dscpanel.core import style
    from dscpanel.ui.dialogs import LegendSettings
    legend = window.doc.legend
    dialog = LegendSettings(window, legend)
    assert dialog.size.value() is None                  # following
    assert "default" in dialog.size.box.suffix()
    dialog.size.box.setValue(13.0)
    assert legend.size == 13.0                          # its own now
    style.set_preference("legend_size", 6.0)
    assert style.value(window.doc, legend, "size") == 13.0   # still its own
    dialog.size.reset.click()
    assert legend.size is None
    assert style.value(window.doc, legend, "size") == 6.0
    dialog.reject()


def test_the_settings_operator_is_registered(window):
    op = window.ops.get("app.settings")
    assert op is not None and op.key == "Ctrl+,"
    assert window.ops.duplicate_keys() == {}


# ------------------------- round 9: near an object acts, far draws a box
def test_a_drag_near_a_curve_marks_it_and_far_from_it_draws_a_box(window):
    """Christian: the box should only start when the press is NOT within the
    pick distance of anything. His tap-and-drag arrives as one press."""
    from dscpanel.core import style
    plot = window.plot
    (on_curve, _end) = _on_the_heating_curve(window)
    near = (on_curve[0], on_curve[1] - 8)          # inside 14 px
    far = (on_curve[0], on_curve[1] - 60)
    assert plot.drag_target(QPointF(*near))[0] == "interval"
    assert plot.drag_target(QPointF(*far)) is None
    asked = _answer(window, None)
    plot.mousePressEvent(_press(plot, near))
    plot.mouseMoveEvent(_move(plot, (near[0] + 90, near[1])))
    plot.mouseReleaseEvent(_release(plot, (near[0] + 90, near[1])))
    assert len(asked) == 1
    plot.mousePressEvent(_press(plot, far))
    assert plot._box is not None
    plot.mouseMoveEvent(_move(plot, (far[0] + 90, far[1] + 90)))
    plot.mouseReleaseEvent(_release(plot, (far[0] + 90, far[1] + 90)))
    assert len(asked) == 1                         # a box asks nothing
    # the distance is the user's: tighter, and 8 px is no longer near
    style.set_preference("pick_radius", 4.0)
    assert plot.drag_target(QPointF(*near)) is None


def test_shift_drag_on_a_curve_is_always_a_box(window):
    plot = window.plot
    (on_curve, end) = _on_the_heating_curve(window)
    asked = _answer(window, "Onset point")
    plot.mousePressEvent(_press(plot, on_curve, modifiers=Qt.ShiftModifier))
    assert plot._box is not None and plot._box["add"]
    plot.mouseMoveEvent(_move(plot, (end[0], end[1] + 40)))
    plot.mouseReleaseEvent(_release(plot, (end[0], end[1] + 40)))
    assert asked == []


def test_the_nearest_object_wins(window):
    """Within the pick distance of a label AND a curve, the closer one is
    meant - not whichever kind used to be checked first."""
    plot = window.plot
    (on_curve, _end) = _on_the_heating_curve(window)
    label = window.add_label("note", at=QPointF(on_curve[0] + 200,
                                                on_curve[1] - 120))
    plot.grab()
    assert plot.object_at(QPointF(*on_curve)) is window.doc.scans[0]
    box = [b for lb, b in plot._text_boxes if lb is label][0]
    assert plot.object_at(QPointF(box.center())) is label


def test_the_pick_distance_is_a_setting_with_no_figure_column(window,
                                                              own_preferences):
    import json
    from dscpanel.core import style
    from dscpanel.ui.settings import SettingsDialog
    assert not hasattr(window.doc.style, "pick_radius")
    dialog = SettingsDialog(window)
    assert "pick_radius" in dialog.defaults
    assert "pick_radius" not in dialog.figure
    dialog.set_default("pick_radius", 22.0)
    assert window.plot.pick_radius() == 22.0
    dialog.accept()
    with open(own_preferences, encoding="utf-8") as fh:
        stored = json.load(fh)
    assert stored["handling"] == {"pick_radius": 22.0}
    assert "pick_radius" not in stored["style"]


# --------------------------------------------- round 9: zoom is undoable
def _pinch(plot, centre, notches=1, modifiers=Qt.ControlModifier):
    from PySide6.QtGui import QWheelEvent
    return QWheelEvent(QPointF(centre), QPointF(centre), QPoint(0, 0),
                       QPoint(0, int(120 * notches)), Qt.NoButton, modifiers,
                       Qt.NoScrollPhase, False)


def test_zooming_in_twice_comes_back_out_with_two_undos(window):
    """Christian: zoom in on a feature a few times, Ctrl+Z walks back."""
    from PySide6.QtTest import QTest
    from dscpanel.ui import plot as plot_module
    plot = window.plot
    window.undo.clear()
    plot.grab()
    centre = plot.plot_rect().center()
    plot.wheelEvent(_pinch(plot, centre))
    plot.wheelEvent(_pinch(plot, centre))          # the same burst
    QTest.qWait(plot_module.VIEW_SETTLE_MS + 150)  # the fingers settle
    assert window.undo.depth() == 1
    once = (plot.view_x(), plot.view_y())
    plot.wheelEvent(_pinch(plot, centre))
    plot.commit_view()
    assert window.undo.depth() == 2
    assert plot.view_x()[1] - plot.view_x()[0] < once[0][1] - once[0][0]
    window.undo_step()
    assert plot.view_x() == pytest.approx(once[0])
    window.undo_step()
    assert plot._view_x is None and plot._view_y is None     # home again
    window.redo_step()
    assert plot.view_x() == pytest.approx(once[0])


def test_undo_during_a_zoom_undoes_the_zoom(window):
    """Pressed while the zoom is still settling, Ctrl+Z must take back the
    zoom - not the step before it, with the zoom then landing on top and
    throwing the redo away."""
    plot = window.plot
    scan = window.doc.scans[0]
    window.undo.set_props([(scan, "offset", 0.5)], "move 1 scan(s)")
    plot.grab()
    centre = plot.plot_rect().center()
    plot.wheelEvent(_pinch(plot, centre))          # not settled yet
    assert window.ops.get("edit.undo").enabled(window)
    window.undo_step()
    assert plot._view_x is None and plot._view_y is None
    assert scan.offset == 0.5                      # the move is untouched
    assert window.undo.can_redo()


def test_a_zoom_box_and_a_fit_are_one_step_each(window):
    plot = window.plot
    window.undo.clear()
    plot.grab()
    rect = plot.plot_rect()
    plot.set_mode("zoom_box")
    a = (rect.left() + 100, rect.top() + 60)
    b = (rect.left() + 300, rect.top() + 200)
    plot.mousePressEvent(_press(plot, a))
    plot.mouseMoveEvent(_move(plot, b))
    plot.mouseReleaseEvent(_release(plot, b))
    plot.set_mode(None)
    assert window.undo.depth() == 1
    zoomed = plot.view_x()
    plot.fit()
    assert window.undo.depth() == 2
    window.undo_step()
    assert plot.view_x() == pytest.approx(zoomed)


def test_a_framing_from_another_unit_comes_back_as_the_fit(window):
    """Limits in W/g say nothing about an mW axis."""
    plot = window.plot
    window.undo.clear()
    plot.grab()
    plot.wheelEvent(_pinch(plot, plot.plot_rect().center()))
    plot.commit_view()
    plot.wheelEvent(_pinch(plot, plot.plot_rect().center()))
    plot.commit_view()
    window.set_unit(units.UNIT_MW)
    window.undo_step()
    assert plot._view_x is None and plot._view_y is None


# ------------------------------------------ round 9: the window around it
def test_the_menu_bar_is_file_edit_search_help(window):
    titles = [a.text() for a in window.menuBar().actions()]
    assert titles == ["&File", "&Edit", "&Search", "&Help"]
    from dscpanel import branding
    about = [a.text() for a in window.menus["&Help"].actions()]
    assert about == ["About " + branding.APP_NAME]
    searched = []
    window.operator_search = lambda: searched.append(True)
    window._search_action.trigger()
    assert searched == [True]


def test_about_says_what_is_running(window):
    from dscpanel import __version__
    text = window.about_text()
    assert __version__ in text
    assert "ACH-DSC-Plotter" in text                # where the reader is from
    assert "PySide6" in text and "Qt" in text


def test_the_windows_wear_the_plot_theme(window):
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    window.set_theme("blender-default")
    assert app.palette().color(QPalette.Window).lightness() < 100
    window.set_theme("light")
    assert app.palette().color(QPalette.Window).lightness() > 180
    window.set_theme("blender-default")
    assert app.palette().color(QPalette.Window).lightness() < 100


def test_saving_flashes_a_confirmation(window, tmp_path):
    path = window.save_session(path=str(tmp_path / "flash.dscpanel"))
    assert path
    assert window.plot.flashing().startswith("Saved flash.dscpanel")
    window.plot.grab()                              # and it paints
