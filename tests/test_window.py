"""The window: drawing, picking, transforms, and what an export admits to.

Offscreen, so it runs anywhere, and never `exec()`s a dialog - a test that
reaches a modal event loop hangs rather than fails, which is the worst shape
a test problem can take. Menus are BUILT and inspected instead.
"""

import os

import numpy as np
import pytest

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
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
    # nothing selected, nothing happens (round 17)
    window.select_all(False)
    window.run_op("arrange.reset")
    assert window.doc.scans[1].offset == 2.0


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
    modifier, and the y axis opens or closes about y = 0."""
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
    # the default template, whole degrees: T_on = 61 degC
    assert analysis.summary() == "*T*_{on} = 61 \u00b0C"


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
    scan_out, x0, x1, editing, span = asked[0]
    assert scan_out is scan and editing is None and x0 < x1
    assert span is None                   # typed / clicked: temperatures
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
    # no text of its own: the default template, number filled in on drawing
    assert made.label is None
    text = made.summary(window.doc)
    assert text.startswith("*T*_{on} = ") and text.endswith("\u00b0C")
    from dscpanel.ui.plot import markup_runs
    runs = markup_runs(text)
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
    for x in range(int(rect.left()) + 5, int(rect.right()) - 5, 23):
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
    assert label.can_scale and label.can_rotate      # S and R
    assert arrow.can_scale and not arrow.can_rotate   # S, round 16


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
    label_before = first.label
    # the window is handed the analysis being edited, so it does not ask -
    # and it moves THAT analysis rather than replacing it (round 10)
    again = window._measure_ready(scan, 65.0, 125.0, first)
    assert again is first
    assert first in scan.analysis_objects
    assert first.cursors() == pytest.approx([65.0, 125.0])
    # the label is a template: what it SHOWS follows the new number
    assert first.label == label_before
    first.number_format = "%.3f"         # whole degrees hide the change
    shown_after = first.summary(window.doc)
    window.undo.undo()
    assert first.cursors() == pytest.approx([60.0, 120.0])
    assert first.summary(window.doc) != shown_after


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
    assert legend.can_scale and legend.can_rotate    # S and R
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
    scan, x0, x1, editing, span = asked[0]
    assert scan is window.doc.scans[0] and editing is None
    # the interval is the two SAMPLES nearest where the drag began and ended
    trace = plot._trace_of(scan)
    first = plot.sample_at(trace, QPointF(*start))
    last = plot.sample_at(trace, QPointF(*end))
    assert span == (first, last)
    assert x0 == pytest.approx(float(scan.temperature()[first]))
    assert x1 == pytest.approx(float(scan.temperature()[last]))
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
    from dscpanel.core import measure, style
    style.set_preference("analysis_flush", style.FLUSH_AUTO)
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
    dialog.revert()                            # Revert puts it back
    assert style.preference("tick_size") == style.builtin("tick_size")


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
    assert dialog.text_size.value() is None                  # following
    assert "default" in dialog.text_size.box.suffix()
    dialog.text_size.box.setValue(13.0)
    assert legend.size == 13.0                          # its own now
    style.set_preference("legend_size", 6.0)
    assert style.value(window.doc, legend, "size") == 13.0   # still its own
    dialog.text_size.reset.click()
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


# ------------------------------------------------------------- round 10
def test_z_starts_with_the_box(window):
    plot = window.plot
    seen = []
    for _ in range(4):
        plot.cycle_mode(plot.ZOOM_CYCLE)
        seen.append(plot.mode())
    assert seen == ["zoom_box", "zoom_h", "zoom_v", None]


def test_ctrl_l_r_m_align_analysis_labels_and_leave_the_legend(window):
    from dscpanel.core import measure, style
    keys = {op.id: op.key for op in window.ops.all()}
    assert keys["legend.toggle"] == ""
    assert keys["analysis.flush_left"] == "Ctrl+L"
    assert keys["analysis.flush_right"] == "Ctrl+R"
    assert keys["analysis.flush_center"] == "Ctrl+M"
    scan = window.doc.scans[0]
    onset = measure.run("Onset point", scan, 60.0, 120.0)
    integral = measure.run("Peak Integration (enthalpy)", scan, 70.0, 150.0)
    window.refresh()
    window.doc.select_only([integral])
    assert window.run_op("analysis.flush_right")
    assert integral.flush == style.FLUSH_RIGHT and onset.flush is None
    # nothing but the scan selected: every analysis shown on it
    window.doc.select_only([scan])
    assert window.run_op("analysis.flush_left")
    assert onset.flush == integral.flush == style.FLUSH_LEFT
    window.undo.undo()
    assert integral.flush == style.FLUSH_RIGHT and onset.flush is None
    window.doc.select_all(False)
    assert not window.ops.get("analysis.flush_center").enabled(window)


def _orange_in(plot, box):
    image = plot.grab().toImage()
    ratio = image.devicePixelRatio() or 1.0
    for x in range(box.left(), box.right()):
        for y in range(box.top(), box.bottom()):
            c = image.pixelColor(int(x * ratio), int(y * ratio))
            if c.red() > 200 and 100 < c.green() < 200 and c.blue() < 100:
                return True
    return False


def test_clicking_off_an_artist_takes_the_orange_away(window):
    """The cache was keyed on the selection of scans and analyses only, so a
    label kept its orange after a click elsewhere (and did not always get
    it in the first place)."""
    plot = window.plot
    plot.grab()
    label = window.add_label("note", at=QPointF(400, 150))
    plot.grab()
    box = [b for lb, b in plot._text_boxes if lb is label][0]
    centre = (box.center().x(), box.center().y())
    plot.mousePressEvent(_press(plot, centre))
    plot.mouseReleaseEvent(_release(plot, centre))
    assert label.selected and _orange_in(plot, box)
    empty = (plot.plot_rect().right() - 30, plot.plot_rect().top() + 30)
    assert plot.object_at(QPointF(*empty)) is None
    plot.mousePressEvent(_press(plot, empty))
    plot.mouseReleaseEvent(_release(plot, empty))
    assert not label.selected and not _orange_in(plot, box)


def _trace_of(window, scan):
    window.plot.grab()
    return [t for t in window.plot.traces if t.scan is scan][0]


def test_an_integration_is_marked_by_two_dashes_and_nothing_between(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    integral = measure.run("Peak Integration (enthalpy)", scan, 70.0, 150.0)
    window.refresh()
    plot = window.plot
    trace = _trace_of(window, scan)
    rect = plot.plot_rect()
    dashes, lines = plot.interval_marks(trace, integral, rect)
    assert lines == []                        # never a connecting curve
    assert len(dashes) == 2
    for (a, b), celsius in zip(dashes, sorted(integral.cursors())):
        # a vertical dash centred ON the trace, not lifted above it
        x = plot.x_to_px(plot.to_axis(celsius), rect)
        assert a.x() == pytest.approx(x) and b.x() == pytest.approx(x)
        on_curve = plot._curve_y_at(trace, plot.to_axis(celsius), rect)
        assert (a.y() + b.y()) / 2.0 == pytest.approx(on_curve)


def test_an_onset_is_marked_by_lines_to_its_point_in_the_axis_colour(window):
    from dscpanel.core import measure
    from dscpanel.ui import plot as plot_module
    scan = window.doc.scans[0]
    onset = measure.run("Onset point", scan, 60.0, 120.0)
    assert onset.marks_a_point
    window.refresh()
    plot = window.plot
    trace = _trace_of(window, scan)
    rect = plot.plot_rect()
    dashes, lines = plot.interval_marks(trace, onset, rect)
    assert len(dashes) == 2 and len(lines) == 2
    (left, point), (point_again, right) = lines
    assert point == point_again
    x_point = plot.x_to_px(plot.to_axis(onset.value()), rect)
    assert point.x() == pytest.approx(x_point)
    # the lines start and end where the dashes sit; no dash at the point
    centres = [QPointF(a.x(), (a.y() + b.y()) / 2.0) for a, b in dashes]
    assert left == centres[0] and right == centres[1]
    assert all(abs(a.x() - point.x()) > 1 for a, _b in dashes)
    # drawn in the axis colour, whatever the analysis colour is
    painted = []

    class Pen(object):
        def setPen(self, pen):
            painted.append(pen.color().name())

        def drawLine(self, *_args):
            pass
    plot._paint_interval(Pen(), rect, trace, onset)
    assert painted == [plot_module._AXIS.name()]


def _edit(window, analysis):
    """Double-click an analysis label made here, without dragging."""
    plot = window.plot
    plot.grab()
    box = [b for a, b in plot._analysis_boxes if a is analysis][0]
    centre = (box.center().x(), box.center().y())
    plot.mouseDoubleClickEvent(_double(plot, centre))
    plot.mouseReleaseEvent(_release(plot, centre))
    return window._editing[1]


def test_the_gizmos_live_only_while_the_settings_are_open(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    analysis = measure.run("Peak Integration (enthalpy)", scan, 70.0, 150.0)
    window.refresh()
    dialog = _edit(window, analysis)
    plot = window.plot
    assert plot.editing() is analysis and dialog.isVisible()
    # dragging a gizmo recomputes the SAME analysis the moment it is let go
    plot.grab()
    rect = plot.plot_rect()
    x = plot.x_to_px(plot.to_axis(150.0), rect)
    index = plot.cursor_at(QPointF(x, rect.center().y()))
    assert index is not None
    plot.start_cursor_drag(index, QPointF(x, rect.center().y()))
    plot.drag_cursor(QPointF(x + 40, rect.center().y()))
    plot.end_cursor_drag()
    assert analysis in scan.analysis_objects
    assert max(analysis.cursors()) > 150.0
    # the dialog follows: its End is the new cursor
    assert dialog.end.text().startswith("%.2f" % max(analysis.cursors()))
    # closing the settings - here Cancel - ends the gizmos
    dialog.reject()
    assert plot.measuring() is None


def test_closing_the_settings_confirms_a_moved_interval(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    analysis = measure.run("Onset point", scan, 60.0, 120.0)
    window.refresh()
    dialog = _edit(window, analysis)
    # moved (typed, say) but never confirmed
    window.plot.measuring()["cursors"] = [62.0, 118.0]
    dialog.accept()
    assert window.plot.measuring() is None
    assert analysis.cursors() == pytest.approx([62.0, 118.0])


def test_while_editing_a_press_elsewhere_does_not_move_a_gizmo(window):
    from PySide6.QtGui import QKeyEvent
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    analysis = measure.run("Onset point", scan, 60.0, 120.0)
    window.refresh()
    dialog = _edit(window, analysis)
    plot = window.plot
    before = list(plot.measuring()["cursors"])
    empty = (plot.plot_rect().right() - 30, plot.plot_rect().top() + 30)
    plot.mousePressEvent(_press(plot, empty))
    plot.mouseReleaseEvent(_release(plot, empty))
    plot.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape,
                                 Qt.NoModifier))
    assert plot.measuring()["cursors"] == before    # neither moved nor lost
    dialog.reject()


def test_the_settings_open_beside_the_gizmos_not_over_them(window):
    from PySide6.QtCore import QRect
    from dscpanel.ui.dialogs import AnalysisSettings
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    analysis = measure.run("Onset point", scan, 60.0, 120.0)
    dialog = AnalysisSettings(window, analysis)
    area = window.screen().availableGeometry()
    for avoid in (QRect(area.left() + 40, area.top() + 60, 120, 300),
                  QRect(area.right() - 160, area.top() + 60, 120, 300)):
        at = window.place_beside(dialog, avoid)
        placed = QRect(at, dialog.size())
        assert not placed.intersects(avoid)
        assert area.contains(placed.topLeft())
    dialog.close()


def test_no_dialog_field_shadows_a_qt_method():
    """`self.size = <a spin box>` hid QWidget.size() - and `width`, `x` and
    `y` did the same - which only surfaced when something asked a dialog how
    big it was. The `grab` trap, again."""
    import io
    import re
    from PySide6.QtWidgets import QDialog
    import dscpanel.ui.dialogs as dialogs_module
    import dscpanel.ui.settings as settings_module
    qt = set(dir(QDialog))
    for module in (dialogs_module, settings_module):
        with io.open(module.__file__, encoding="utf-8") as fh:
            names = set(re.findall(r"self\.([a-z_]+)\s*=", fh.read()))
        assert not sorted(names & qt), module.__name__


def test_ctrl_w_closes_the_pop_ups_before_the_window(window):
    """Christian: hotkey muscle memory must not close the whole project
    while a settings window is open."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    closed = []
    window.close = lambda: closed.append("window") or True
    window.show()                  # a window shortcut needs a shown window
    QTest.qWaitForWindowExposed(window)
    window.edit_object(window.doc.legend)
    window.edit_object(window.doc.arrow)
    first, second = window._dialogs[-2], window._dialogs[-1]
    assert window.popups()[-2:] == [first, second]
    # through the real shortcut, pressed while a pop-up has the keyboard
    QTest.keyClick(second.windowHandle(), Qt.Key_W, Qt.ControlModifier)
    assert not second.isVisible() and first.isVisible()
    assert closed == []
    assert window.close_step() is first         # then the next one
    assert window.popups() == []
    assert closed == []
    # then the tab (round 19), asking about its unsaved changes...
    window.ask_to_save = lambda: "discard"
    assert window.close_step() == "tab"
    assert window.figures() == [] and closed == []
    assert window.close_step() is None          # ...and only now the window
    assert closed == ["window"]


# ------------------------------------------------------------- round 11
def test_closing_with_unsaved_changes_asks_first(window, tmp_path):
    from PySide6.QtTest import QTest
    window.show()
    QTest.qWaitForWindowExposed(window)
    assert window.is_modified()               # a file was opened, not saved
    assert window.windowTitle().startswith("unsaved *")
    answers = []

    def answer(reply):
        def ask():
            answers.append(reply)
            return reply
        return ask
    window.ask_to_save = answer("cancel")
    assert window.close() is False and window.isVisible()
    window.save_session(path=str(tmp_path / "kept.dscpanel"))
    assert not window.is_modified()
    # the framing is part of the figure since round 17: a zoom IS a change
    # to the file, and going back to the saved framing is clean again
    before = window.plot.view_state()
    window.plot.zoom_at(window.plot.plot_rect().center(), 2.0, both=True)
    assert window.is_modified()
    window.plot.restore_view(before)
    assert not window.is_modified()
    window.doc.scans[0].offset = 0.3
    assert window.is_modified()
    window.doc.scans[0].offset = 0.0          # back as it was saved
    assert not window.is_modified()
    window.doc.scans[0].offset = 0.3
    window.ask_to_save = answer("discard")
    assert window.close() is True
    assert answers == ["cancel", "discard"]


def test_a_settings_window_closed_any_way_keeps_its_changes(window):
    from dscpanel.ui.dialogs import LegendSettings
    legend = window.doc.legend
    window.undo.clear()
    dialog = window.edit_object(legend) and window._dialogs[-1]
    assert isinstance(dialog, LegendSettings)
    dialog.text_size.box.setValue(13.0)
    dialog.reject()                           # its X, Esc, Ctrl+W
    assert legend.size == 13.0
    assert window.undo.depth() == 1           # one step, undoable
    window.undo.undo()
    assert legend.size is None
    # Revert is the one way to put it back
    window.edit_object(legend)
    dialog = window._dialogs[-1]
    dialog.text_size.box.setValue(15.0)
    dialog.revert()
    assert legend.size is None


# ------------------------------------------- round 11: x_truncate, spans
def test_a_truncated_start_is_left_out_of_fit_picking_and_exports(
        window, tmp_path, sample):
    from dscpanel.core import export as core_export, session
    plot = window.plot
    scan = window.doc.scans[0]
    window.doc.scans[1].visible = False
    scan.keep = (0.1, 1.0)
    window.refresh()
    plot.grab()
    trace = plot._trace_of(scan)
    count = len(scan.temperature())
    assert len(trace.x) == count - int(count * 0.1)
    assert trace.first == int(count * 0.1)
    # the fit (F) ignores the hidden start: the dip at 26 degC is gone
    assert plot.data_x()[0] == pytest.approx(float(trace.x.min()))
    assert plot.data_x()[0] > 50.0
    # dashed only while hovered or selected - never otherwise
    window.doc.select_all(False)
    plot._cursor = None
    assert plot.hidden_shown() == []
    scan.selected = True
    assert plot.hidden_shown() == [trace]
    plot.grab()                                   # and it paints
    # the exports: CSV holds the kept part, the driver repeats x_truncate
    csv = window.export_csv(str(tmp_path / "kept.csv"))
    rows = [line for line in open(csv, encoding="utf-8")
            if line[:1].isdigit() or line[:1] == "-"]
    assert len(rows) == len(trace.x)
    assert "x_truncate(ax, datas, (0, 0), x0=0.1, x1=1)" in \
        core_export.driver_source(window.doc)
    # and a session keeps it
    path = tmp_path / "cut.dscpanel"
    session.save(window.doc, str(path))
    reopened, _problems = session.load(
        str(path), lambda _p: model.Sample(sample.path, sample.data))
    assert reopened.scans[0].keep == (0.1, 1.0)


def test_measuring_leaves_out_what_is_hidden(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    scan.keep = (0.25, 1.0)
    minutes, temperature, flow = measure._series(scan)
    k0, k1 = scan.kept_range(len(scan.temperature()))
    assert len(temperature) == k1 - k0
    assert float(temperature[0]) == pytest.approx(
        float(scan.temperature()[k0]))


def _hooked_sample():
    """A heating segment whose temperature DOUBLES BACK: 30 -> 80, back
    down to 50, then up to 200. The shape the reader returns; synthetic."""
    from conftest import make_data
    data = make_data(segments=1)
    temp = np.concatenate([np.linspace(30.0, 80.0, 100),
                           np.linspace(80.0, 50.0, 60),
                           np.linspace(50.0, 200.0, 400)])
    time = np.linspace(0.0, 30.0, len(temp))
    watts = -0.004 - 0.003 * np.exp(-((temp - 65.0) / 4.0) ** 2) \
        * (np.arange(len(temp)) >= 160)       # a peak on the LAST branch
    data["numdata"][0]["nums"] = np.column_stack([time, temp, watts])
    return model.Sample("C:/nowhere/HOOK.tri", data)


def test_a_stretch_dragged_on_one_branch_measures_that_branch(qapp):
    """Christian: a DSC curve is a parametric curve, not a function of
    temperature, so an interval has to be a stretch of samples. Between 60
    and 70 degC this curve passes three times; the drag was on one pass."""
    from dscpanel.core import measure
    from dscpanel.ui.window import MainWindow
    sample = _hooked_sample()
    win = MainWindow()
    win.resize(900, 560)
    win._sample_loaded(sample)
    scan = win.doc.scans[0]
    temperature = scan.temperature()
    # the last branch between 60 and 70 degC
    first = int(np.flatnonzero((np.arange(len(temperature)) >= 160)
                               & (temperature >= 60.0))[0])
    last = int(np.flatnonzero((np.arange(len(temperature)) >= 160)
                              & (temperature <= 70.0))[-1])
    minutes, temp, _flow = measure._series(scan, (first, last))
    assert len(temp) == last - first + 1                 # that pass only
    by_span = measure.run("Peak Integration (enthalpy)", scan,
                          float(temperature[first]),
                          float(temperature[last]), span=(first, last))
    assert by_span is not None and by_span.span == (first, last)
    by_temperature = measure.run("Peak Integration (enthalpy)", scan,
                                 float(temperature[first]),
                                 float(temperature[last]))
    win.refresh()
    plot = win.plot
    plot.grab()
    trace = plot._trace_of(scan)
    covered_span = plot._covered(trace, by_span)[0]
    covered_temp = plot._covered(trace, by_temperature)[0]
    assert len(covered_span) == last - first + 1
    assert len(covered_temp) > len(covered_span)          # every pass


def test_a_gizmo_of_a_stretch_follows_the_curve(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    plot = window.plot
    plot.grab()
    trace = plot._trace_of(scan)
    first, last = trace.first + 100, trace.first + 200
    analysis = measure.run("Peak Integration (enthalpy)", scan,
                           float(scan.temperature()[first]),
                           float(scan.temperature()[last]),
                           span=(first, last))
    window.refresh()
    assert plot.start_measure(scan, editing=analysis, span=analysis.span)
    plot.grab()
    target = plot._sample_point(trace, last + 60)
    plot.start_cursor_drag(1, target)
    plot.drag_cursor(target)
    assert plot.measuring()["span"][1] == pytest.approx(last + 60, abs=2)
    plot.end_measure()


def test_the_scan_settings_hide_the_ends(window):
    from dscpanel.ui.dialogs import ScanSettings
    scan = window.doc.scans[0]
    dialog = ScanSettings(window, scan, window.doc.y_unit)
    dialog.cut_start.setValue(10.0)
    dialog.cut_end.setValue(5.0)
    assert scan.keep == pytest.approx((0.1, 0.95))
    assert "points" in dialog.cut_note.text()
    dialog.revert()
    assert scan.keep == (0.0, 1.0)


def test_the_caption_keeps_its_distance_from_the_numbers(window):
    """The x caption sat a fixed 16 px below the axis line, which 8 pt
    numbers nearly fill and bigger ones overlapped."""
    from dscpanel.core import style
    plot = window.plot
    plot.grab()
    x_axis, y_axis = window.doc.axes["x"], window.doc.axes["y"]
    rect = plot.plot_rect()
    numbers_end = rect.bottom() + plot.tick_extent(x_axis)
    caption = plot.axis_label_rect(x_axis)
    assert caption.top() == pytest.approx(numbers_end
                                          + style.builtin("caption_gap"))
    # a bigger distance is a bigger margin, not a caption run off the edge
    bottom = plot.margins()[3]
    style.set_preference("caption_gap", 30.0)
    assert plot.margins()[3] > bottom
    assert plot.axis_label_rect(x_axis).bottom() <= plot.height()
    # the y caption sits LEFT of the widest number, the same distance off
    rect = plot.plot_rect()
    y_caption = plot.axis_label_rect(y_axis)
    assert y_caption.right() == pytest.approx(
        rect.left() - plot.tick_extent(y_axis) - 30.0)


def test_cancelling_a_caption_drag_leaves_it_following_the_default(window):
    plot = window.plot
    plot.grab()
    axis = window.doc.axes["x"]
    assert axis.label_gap is None
    plot.start_grab([axis])
    plot._update_move(QPointF(plot._move["start"].x(),
                              plot._move["start"].y() + 20))
    assert axis.label_gap is not None
    plot._finish_move(cancel=True)
    assert axis.label_gap is None          # not pinned at what was drawn


def test_the_session_keeps_the_temperature_scale(window, tmp_path, sample):
    from dscpanel.core import session, units as core_units
    window.set_x_unit(core_units.TEMP_K)
    path = tmp_path / "kelvin.dscpanel"
    session.save(window.doc, str(path))
    reopened, _problems = session.load(
        str(path), lambda _p: model.Sample(sample.path, sample.data))
    assert reopened.x_unit == core_units.TEMP_K


# ------------------------------------------------------------ round 13
def test_a_plain_swipe_keeps_zero_where_it_is(window):
    """Christian, round 13: the y scale moves about y = 0 and nothing else,
    wherever the cursor is."""
    plot = window.plot
    plot.grab()
    plot.set_view_y(-0.5, 2.0)
    zero = plot.y_to_px(0.0)
    for at in ((200, 100), (300, 400)):
        plot.wheelEvent(_wheel(pixels=(0, 40), at=at))
        assert plot.y_to_px(0.0) == pytest.approx(zero)
    lo, hi = plot.view_y()
    assert lo / hi == pytest.approx(-0.5 / 2.0)       # scaled, not shifted
    assert hi < 2.0


def test_m_is_the_x_range(window):
    assert {op.id: op.key for op in window.ops.all()}["view.x_range"] == "M"


def test_the_x_range_pop_up_is_typed_straight_through(window):
    """The first number is selected on opening, so typing replaces it; Tab
    reaches the second; a comma is a decimal point; the pair may be typed in
    either order."""
    window.show()
    dialog = window.x_range_dialog()
    dialog.show()
    assert dialog.low_edit.hasFocus() or dialog.focusWidget() is dialog.low_edit
    assert dialog.low_edit.selectedText() == dialog.low_edit.text()
    dialog.low_edit.setText("150")
    dialog.high_edit.setText("40,5")
    assert dialog.values() == (40.5, 150.0)
    dialog.high_edit.setText("150")
    assert dialog.values() is None               # not a range
    dialog.accept()
    assert dialog.isVisible()                    # and it stays open
    dialog.close()
    window.hide()


def test_the_x_range_is_one_undo_step(window):
    plot = window.plot
    plot.grab()
    before = plot.view_x()
    window.set_x_range(60.0, 120.0)
    assert plot.view_x() == (60.0, 120.0)
    assert plot.view_y() is not None
    window.undo_step()
    assert plot.view_x() == before


def test_m_through_the_window_uses_what_was_typed(window, monkeypatch):
    from dscpanel.ui import dialogs
    monkeypatch.setattr(dialogs.RangeDialog, "exec", lambda self: 1)
    real = window.x_range_dialog

    def filled():
        dialog = real()
        dialog.low_edit.setText("70")
        dialog.high_edit.setText("90")
        return dialog
    window.x_range_dialog = filled
    window.run_op("view.x_range")
    assert window.plot.view_x() == (70.0, 90.0)


def _two_onsets(window):
    """Two onsets on the first scan, drawn, with their label boxes."""
    scan = window.doc.scans[0]
    scan._analyses = None
    scan.sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C #1": {
            "Onset point": [{"segment": 1, "Onset x": "90,0 \u00b0C"},
                            {"segment": 1, "Onset x": "150,0 \u00b0C"}]}}
    first, second = scan.analysis_objects[:2]
    first.visible = second.visible = True
    window.refresh()
    window.plot.grab()
    return first, second


def _box_of(plot, boxes, obj):
    box = [b for o, b in boxes if o is obj][0]
    return (box.center().x(), box.center().y())


# ------------------------------------------------------------ round 14
def test_y_offset_markers_are_objects_against_the_axis(window):
    doc = window.doc
    doc.scans[1].offset = 0.5
    plain = window.plot.grab().toImage()
    window.run_op("figure.offset_markers")
    assert doc.offset_markers
    assert window.plot.grab().toImage() != plain
    markers = [s.marker for s in doc.scans]
    assert all(m in doc.objects() for m in markers)
    plot = window.plot
    assert len(plot._marker_boxes) == 2
    # unplaced, each hugs the left end of its curve - against the y axis
    # where the curve reaches it
    rect = plot.plot_rect()
    for scan in doc.scans:
        trace = plot._trace_of(scan)
        left = max(rect.left(), plot.x_to_px(float(np.nanmin(trace.x)), rect))
        x = plot.x_to_px(plot.marker_x(scan.marker), rect)
        assert x - left == pytest.approx(8.0, abs=4.0)
    # the object is what is picked where it is drawn
    at = QPointF(*_box_of(plot, plot._marker_boxes, markers[0]))
    assert plot.object_at(at) is markers[0]


def test_selected_markers_are_dragged_together(window):
    doc = window.doc
    window.run_op("figure.offset_markers")
    plot = window.plot
    plot.grab()
    first, second = [s.marker for s in doc.scans]
    window.run_op("select.offset_markers")
    assert first.selected and second.selected
    start = _box_of(plot, plot._marker_boxes, first)
    before = [(plot.marker_celsius(m), plot.marker_dy(m))
              for m in (first, second)]
    plot.mousePressEvent(_press(plot, start))
    plot.mouseMoveEvent(_move(plot, (start[0] + 20, start[1] + 10)))
    plot.mouseMoveEvent(_move(plot, (start[0] + 40, start[1] + 20)))
    plot.mouseReleaseEvent(_release(plot, (start[0] + 40, start[1] + 20)))
    for marker, (x0, dy0) in zip((first, second), before):
        assert marker.dy == pytest.approx(dy0 + 20)
        assert marker.at[0] == "i"                     # pinned to a sample
        assert plot.marker_celsius(marker) > x0        # both moved right
    window.undo.undo()                                 # ONE step
    assert first.at is None and second.at is None
    assert first.dy is None and second.dy is None


def test_shift_selected_analyses_stretch_their_arrows_together(window):
    """Round 14: shift-click several analyses, double-click-drag one, and
    every one's arrow changes length by the same amount. The first click of
    the double-click narrows the selection; the double-click puts it back."""
    first, second = _two_onsets(window)
    plot = window.plot
    window.doc.select_only([first, second])
    before = [plot.effective_label_dy(a) for a in (first, second)]
    start = _box_of(plot, plot._analysis_boxes, first)
    _double_drag(plot, start, (start[0], start[1] - 25))
    assert first.selected and second.selected
    assert first.label_dy == pytest.approx(before[0] - 25)
    assert second.label_dy == pytest.approx(before[1] - 25)
    window.undo.undo()
    assert first.label_dy is None and second.label_dy is None


def test_one_settings_dialog_sets_what_several_share(window):
    """Select two onsets, open the settings: a shared property (the label
    size) goes to both; one that belongs to each alone (the label text) is
    greyed out. The whole dialog is ONE undo step."""
    first, second = _two_onsets(window)
    first.label = "first"
    window.doc.select_only([first, second])
    window.edit_object(first)
    dialog = window._dialogs[-1]
    assert dialog.group == [second]
    assert not dialog.label.isEnabled()
    assert not hasattr(dialog, "shown_on")   # no "Drawn on" any more
    assert not dialog.model.isEnabled()
    assert not dialog.start.isEnabled() and not dialog.end.isEnabled()
    dialog.text_size.box.setValue(15.0)
    dialog.interval.setChecked(False)
    assert first.label_size == second.label_size == 15.0
    assert not first.show_interval and not second.show_interval
    assert first.label == "first" and second.label is None
    dialog.accept()
    assert first.label_size == second.label_size == 15.0
    window.undo.undo()
    assert first.label_size is None and second.label_size is None
    assert first.show_interval and second.show_interval


def test_revert_puts_back_every_object_of_a_group(window):
    first, second = _two_onsets(window)
    window.doc.select_only([first, second])
    window.edit_object(first)
    dialog = window._dialogs[-1]
    dialog.text_size.box.setValue(18.0)
    dialog.revert()
    assert first.label_size is None and second.label_size is None


def test_marker_settings_for_several(window):
    window.run_op("figure.offset_markers")
    window.plot.grab()
    window.run_op("select.offset_markers")
    first, second = [s.marker for s in window.doc.scans]
    window.edit_object(first)
    dialog = window._dialogs[-1]
    dialog.text_size.box.setValue(9.0)
    dialog.at.setValue(75.0)
    assert first.size == second.size == 9.0
    assert first.at == second.at == ("T", 75.0)   # one column
    assert not dialog.at_auto.isChecked()
    dialog.accept()


def test_the_arrow_head_keeps_what_is_locked():
    import math
    arrow = model.HeatFlowArrow(1)
    # the template's add_exo_arrow, in points
    assert (arrow.head_length, arrow.head_width, arrow.tail_width) == (
        9.0, 13.0, 4.5)
    assert arrow.tip_angle == pytest.approx(
        math.degrees(2 * math.atan(6.5 / 9.0)))
    arrow.lock = "angle"
    angle = arrow.tip_angle
    length, width = arrow.head_for_length(18.0)
    assert (length, width) == pytest.approx((18.0, 26.0))  # wider, same angle
    arrow.head_length, arrow.head_width = arrow.head_for_width(13.0)
    assert arrow.tip_angle == pytest.approx(angle)
    arrow.lock = "width"
    arrow.head_length, arrow.head_width = arrow.head_for_angle(90.0)
    assert arrow.head_width == pytest.approx(13.0)
    assert arrow.head_length == pytest.approx(6.5)          # 90 deg: w = 2l
    arrow.lock = None
    arrow.head_length, arrow.head_width = arrow.head_for_length(10.0)
    assert arrow.head_width == pytest.approx(13.0)          # the angle moved


def test_the_arrow_dialog_locks_one_at_a_time(window):
    from dscpanel.ui.dialogs import ArrowSettings
    arrow = window.doc.arrow
    dialog = ArrowSettings(window, arrow)
    dialog.lock_angle.setChecked(True)
    assert arrow.lock == "angle" and not dialog.tip_angle.isEnabled()
    dialog.lock_width.setChecked(True)
    assert arrow.lock == "width" and not dialog.lock_angle.isChecked()
    assert not dialog.head_width.isEnabled() and dialog.tip_angle.isEnabled()
    dialog.tip_angle.setValue(90.0)
    assert arrow.head_length == pytest.approx(arrow.head_width / 2.0)
    assert dialog.head_length.value() == pytest.approx(arrow.head_length,
                                                       abs=0.05)
    dialog.tail_width.setValue(3.0)
    dialog.text_size.box.setValue(14.0)
    assert arrow.tail_width == 3.0 and arrow.size == 14.0
    source = export.driver_source(window.doc)
    assert "add_exo_arrow(ax, width=3, headwidth=13" in source
    assert "ax.texts[-1].set_fontsize(14)" in source


def test_the_arrow_is_drawn_from_its_points(window):
    plot = window.plot
    plot.grab()
    arrow = window.doc.arrow
    _top, _tip, _cx, head_len, head_half, tail_half = plot.arrow_geometry()
    assert head_len == pytest.approx(9.0 * 96 / 72)
    assert head_half == pytest.approx(13.0 * 96 / 72 / 2)
    arrow.head_width = 26.0
    assert plot.arrow_geometry()[4] == pytest.approx(26.0 * 96 / 72 / 2)


def test_markers_and_the_arrow_survive_a_session(window, tmp_path, sample):
    from dscpanel.core import session
    doc = window.doc
    doc.offset_markers = True
    doc.scans[0].marker.at, doc.scans[0].marker.dy = ("i", 42), -12.0
    doc.scans[1].marker.number_format = "%.2f"
    doc.scans[1].marker.size = 9.0
    doc.arrow.head_width, doc.arrow.lock, doc.arrow.size = 20.0, "width", 12.0
    path = tmp_path / "m.dscpanel"
    session.save(doc, str(path))
    loaded, _problems = session.load(
        str(path), lambda _p: model.Sample(sample.path, sample.data))
    assert loaded.offset_markers
    assert (loaded.scans[0].marker.at, loaded.scans[0].marker.dy) == (
        ("i", 42), -12.0)
    assert loaded.scans[1].marker.size == 9.0
    assert loaded.scans[1].marker.number_format == "%.2f"
    assert (loaded.arrow.head_width, loaded.arrow.lock,
            loaded.arrow.size) == (20.0, "width", 12.0)


def test_the_driver_places_each_marker_as_drawn(window):
    window.run_op("figure.offset_markers")
    window.plot.grab()
    window.doc.scans[1].offset = 0.25
    window.doc.scans[0].marker.at = ("T", 80.0)
    window.doc.marker_hint = window.marker_hint()
    source = export.driver_source(window.doc)
    at = window.plot.marker_celsius(window.doc.scans[0].marker)
    assert abs(at - 80.0) < 1.0
    assert "mark_spot(ax, datas, (0, {}), {:.6g}, '+0.0', yoff_label=".format(
        window.doc.scans[0].seg, at) in source
    assert "'+0.2'" in source or "'+0.3'" in source   # %+.1f by default
    window.run_op("figure.offset_markers")              # off again
    assert "mark_spot" not in export.driver_source(window.doc)


def test_an_image_is_not_stamped_with_the_exo_direction(window, tmp_path):
    assert any("EXO DIRECTION" in line
               for line in export.warnings_for(window.doc))
    assert not any("EXO DIRECTION" in line
                   for line in export.warnings_for(window.doc, exo=False))
    path = window.export_image(str(tmp_path / "f.svg"))
    with open(path, encoding="utf-8") as fh:
        assert "EXO DIRECTION" not in fh.read()
    assert "EXO DIRECTION" in export.driver_source(window.doc)


def test_ctrl_a_leaves_the_axes_alone(window):
    window.run_op("select.all")
    assert all(s.selected for s in window.doc.scans)
    assert not any(a.selected for a in window.doc.axes.values())


# ------------------------------------------------------------ round 15
def test_number_formats():
    from dscpanel.core import numbers
    assert numbers.write(13.247, "%.3g") == "13.2"
    assert numbers.write(1.5, "%.3g") == "1.50"         # the zero is kept
    assert numbers.write(0.05234, "%.3g") == "0.0523"
    assert numbers.write(1234.5, "%.3g") == "1230"      # never 1.23e+03
    assert numbers.write(9.996, "%.3g") == "10.0"
    assert numbers.write(61.08, "%.0f") == "61"
    assert numbers.write(0.5, "%+.1f") == "+0.5"
    assert numbers.write(-0.04, "%.1f") == "0.0"        # no "-0.0"
    assert numbers.write(141.2, "{:.2f}") == "141.20"
    # a format is the number and nothing else: no text, no unit
    assert numbers.normalise("%.1f degF") is None
    assert numbers.normalise("%.1f %.1f") is None
    assert numbers.normalise(".2f") == "%.2f"


def test_a_label_is_a_template_and_a_unit_converts(window):
    from dscpanel.core import labels
    first, second = _two_onsets(window)          # onsets at 90 and 150 degC
    doc = window.doc
    assert labels.render(first, doc).text == "*T*_{on} = 90 \u00b0C"
    # the axis in Kelvin: the label follows, converted
    window.set_x_unit(units.TEMP_K)
    assert labels.render(first, doc).text == "*T*_{on} = 363 K"
    window.set_x_unit(units.TEMP_C)
    # a unit written after {} is a CONVERSION
    first.label = "onset {} \u00b0F"
    assert labels.render(first, doc).text == "onset 194 \u00b0F"
    # ...and one the quantity cannot be in is refused, never relabelled
    first.label = "{} J/g"
    rendered = labels.render(first, doc)
    assert rendered.text == "90 \u00b0C"
    assert rendered.problems[0][0] == "unit"
    # a number typed by hand beside a temperature unit is flagged
    first.label = "*T*_{on} = 150 \u00b0C"
    assert [k for k, _m in labels.render(first, doc).problems] == ["typed"]
    first.label = "*T*_{on} = {} (lit. 148 \u00b0C)"
    rendered = labels.render(first, doc)
    assert rendered.text.startswith("*T*_{on} = 90 \u00b0C")
    assert rendered.problems and rendered.problems[0][0] == "typed"
    # the digits are the user's
    first.label = None
    first.number_format = "%.2f"
    assert labels.render(first, doc).text == "*T*_{on} = 90.00 \u00b0C"


def test_endset_and_enthalpy_defaults(window):
    from dscpanel.core import labels, measure
    scan = window.doc.scans[0]
    endset = measure.run("Endset point", scan, 60.0, 120.0)
    assert endset is not None
    assert labels.render(endset, window.doc).text.startswith("*T*_{end} = ")
    scan._analyses = None
    scan.sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C #1": {
            "Peak Integration (enthalpy)": [
                {"segment": 1, "Peak temperature": "120,0 \u00b0C",
                 "Enthalpy (normalized)": "0,04567 J/g",
                 "Baseline cursor x": "80,0 \u00b0C",
                 "Baseline cursor x1": "160,0 \u00b0C"}]}}
    enthalpy = scan.analysis_objects[0]
    # three significant figures: a small enthalpy keeps its digits
    assert labels.render(enthalpy, window.doc).text == \
        "\\Delta*H* = 0.0457 J/g"
    # per mole needs a molar mass, and says so rather than assuming one
    enthalpy.label = "\\Delta*H* = {} kJ/mol"
    rendered = labels.render(enthalpy, window.doc)
    assert rendered.text.endswith("? kJ/mol")
    enthalpy.visible = True
    assert any("NO MOLAR MASS" in line
               for line in export.warnings_for(window.doc))
    scan.sample.molar_mass = 200.0
    assert labels.render(enthalpy, window.doc).text.endswith(
        "0.00913 kJ/mol")


def test_an_old_session_label_with_its_number_becomes_the_template(
        window, tmp_path, sample):
    """Before round 15 a panel analysis was GIVEN "*T*_{onset} = 61.1 degC"
    as its label. Read back, that is the default template again - and a
    label somebody wrote stays theirs."""
    import json
    from dscpanel.core import measure, session
    scan = window.doc.scans[0]
    made = measure.run("Onset point", scan, 60.0, 120.0)
    kept = measure.run("Onset point", scan, 70.0, 130.0)
    made.label = measure.legacy_label(made)
    kept.label = "my own words"
    path = tmp_path / "old.dscpanel"
    session.save(window.doc, str(path))
    state = json.loads(path.read_text(encoding="utf-8"))
    state["version"] = 3
    path.write_text(json.dumps(state), encoding="utf-8")
    loaded, _problems = session.load(
        str(path), lambda _p: model.Sample(sample.path, sample.data))
    panel = [a for a in loaded.scans[0].analysis_objects
             if a.source == "panel"]
    assert sorted(str(a.label) for a in panel) == ["None", "my own words"]


def test_axis_numbers_take_a_format(window):
    plot = window.plot
    axis = window.doc.axes["y"]
    assert plot.tick_text(axis, 0.5, "y") == "0.5"
    axis.number_format = "%.2f"
    assert plot.tick_text(axis, 0.5, "y") == "0.50"
    plot.grab()
    assert "FormatStrFormatter('%.2f')" in export.driver_source(window.doc)


def test_offset_markers_use_their_format(window):
    window.run_op("figure.offset_markers")
    marker = window.doc.scans[1].marker
    window.doc.scans[1].offset = 0.25
    assert window.plot.marker_text(marker) in ("+0.2", "+0.3")   # %+.1f
    marker.number_format = "%.2f"
    assert window.plot.marker_text(marker) == "0.25"


def test_a_marker_spawns_on_the_shown_curve_not_the_raw_data(window):
    """Round 15: markers are placed on the data as SHOWN - truncated and
    inside the view - so a hidden start-up hook or a stretch outside the
    view is never where one points."""
    plot = window.plot
    window.run_op("figure.offset_markers")
    plot.grab()
    scan = window.doc.scans[0]
    rect = plot.plot_rect()
    trace = plot._trace_of(scan)
    k = plot.marker_sample(scan.marker, trace, rect)
    assert k is not None
    # zoomed in, the marker is against the axis of the NEW view
    lo, hi = plot.view_x()
    window.set_x_range(lo + 0.3 * (hi - lo), hi)
    plot.grab()
    rect = plot.plot_rect()
    trace = plot._trace_of(scan)
    k = plot.marker_sample(scan.marker, trace, rect)
    x = plot.x_to_px(trace.x[k], rect)
    assert rect.left() <= x <= rect.left() + 20
    # truncated: the hidden start is not a place to point at
    scan.keep = (0.2, 1.0)
    scan._cache_key = None
    window.plot.fit()
    window.refresh()
    plot.grab()
    trace = plot._trace_of(scan)
    assert trace.first > 0
    assert plot.marker_sample(scan.marker, trace) is not None
    assert plot.marker_at(scan.marker)[1] >= trace.first


def test_enter_in_a_settings_field_does_not_close_it(window):
    from PySide6.QtTest import QTest
    window.show()
    window.run_op("arrow.settings")
    dialog = window._dialogs[-1]
    dialog.show()
    dialog.head_length.setFocus()
    dialog.head_length.lineEdit().selectAll()
    QTest.keyClicks(dialog.head_length, "12")
    QTest.keyClick(dialog.head_length, Qt.Key_Return)
    assert dialog.isVisible()                     # still open
    assert window.doc.arrow.head_length == pytest.approx(12.0)
    dialog.close()
    window.hide()


def test_the_pointer_shows_while_gizmos_are_up(window):
    """The reticle is not drawn while measure cursors or gizmos are up, so
    the system pointer must be - it used to be hidden too, leaving nothing
    to aim at a gizmo with."""
    plot = window.plot
    plot.grab()
    rect = plot.plot_rect()
    away = plot.x_to_px(110.0, rect)          # between the two cursors
    plot.mouseMoveEvent(_move(plot, (away, rect.center().y()),
                              buttons=Qt.NoButton))
    assert plot.cursor().shape() == Qt.BlankCursor        # the reticle's
    window.doc.select_only([window.doc.scans[0]])
    plot.start_measure(window.doc.scans[0], [80.0, 140.0])
    assert plot.cursor().shape() == Qt.CrossCursor
    x = plot.x_to_px(80.0, rect)
    plot.mouseMoveEvent(_move(plot, (x, rect.center().y()),
                              buttons=Qt.NoButton))
    assert plot.cursor().shape() == Qt.SizeHorCursor      # over a gizmo
    plot.end_measure()


def test_one_font_family_for_the_whole_figure(window):
    # A family by name: the offscreen platform has no font database, and
    # the name is what the figure and the driver carry.
    family = "Arial"
    window.doc.style.font_family = family
    window.plot.invalidate()
    assert window.plot.figure_font().family() == family
    assert window.plot.font().family() == family
    window.plot.grab()
    assert "plt.rcParams['font.family'] = [{!r}, 'sans-serif']".format(
        family) in \
        export.driver_source(window.doc)


def test_the_settings_page_takes_formats_and_a_font(window):
    from dscpanel.core import style
    from dscpanel.ui.settings import SettingsDialog
    page = SettingsDialog(window)
    page.figure["value_format"].set_value("%.2f")
    assert window.doc.style.value_format == "%.2f"
    page.set_default("temperature_format", "%.1f")
    assert style.preference("temperature_format") == "%.1f"
    page.defaults["font_family"].set_value("Arial")
    assert style.preference("font_family") == "Arial"
    page.revert()
    assert window.doc.style.value_format is None
    assert style.preference("temperature_format") == "%.0f"


# ------------------------------------------------------------ round 16
def test_marker_arrow_offsets_are_set_or_shifted_numerically(window):
    """Round 17: the marker's ARROW offset - how far its number sits from
    the curve - absolute or relative; the scan's offset is not in here."""
    doc = window.doc
    window.run_op("figure.offset_markers")
    window.plot.grab()
    first, second = doc.scans
    first.marker.dy, second.marker.dy = 10.0, 20.0     # below the curve
    window.run_op("select.offset_markers")
    window.edit_object(first.marker)
    dialog = window._dialogs[-1]
    assert not hasattr(dialog, "offset") and not hasattr(dialog, "shift")
    assert dialog.arrow_offset.value() == pytest.approx(-10.0)   # up is +
    dialog.arrow_shift.setValue(4.0)                  # relative: both move
    assert (first.marker.dy, second.marker.dy) == pytest.approx((6.0, 16.0))
    assert dialog.arrow_shift.value() == 0.0
    dialog.arrow_offset.setValue(-30.0)               # absolute: both
    assert first.marker.dy == second.marker.dy == pytest.approx(30.0)
    dialog.accept()
    window.undo.undo()                                # the window: ONE step
    assert (first.marker.dy, second.marker.dy) == (10.0, 20.0)
    assert (first.offset, second.offset) == (0.0, 0.0)


def test_s_scales_the_artists_and_nothing_measured(window):
    doc = window.doc
    arrow, legend = doc.arrow, doc.legend
    legend.visible = True
    label = window.add_label("note", at=QPointF(300, 200))
    window.plot.grab()
    scan = doc.scans[0]
    doc.select_only([arrow, legend, label, scan])
    before = (arrow.head_length, arrow.tail_width, legend.sample)
    assert window.plot.start_scale()
    assert scan not in [e["obj"] for e in
                        window.plot._scale["entries"]]   # data never
    for key, text in ((Qt.Key_2, "2"), (Qt.Key_Return, "")):
        window.plot.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key,
                                            Qt.NoModifier, text))
    assert arrow.head_length == pytest.approx(2 * before[0])
    assert arrow.tail_width == pytest.approx(2 * before[1])
    assert arrow.size == pytest.approx(20.0)          # its 10 pt text too
    assert legend.sample == pytest.approx(2 * before[2])
    assert label.size == pytest.approx(20.0)
    window.undo.undo()                                # ONE step
    assert (arrow.head_length, arrow.tail_width, legend.sample) == before
    assert arrow.size is None and label.size is None  # house style again
    # dragged, and cancelled: nothing changes
    doc.select_only([arrow])
    window.plot.start_scale()
    window.plot.mouseMoveEvent(_move(window.plot, (600, 400),
                                     buttons=Qt.NoButton))
    assert arrow.head_length != before[0]
    window.plot.mousePressEvent(_press(window.plot, (600, 400),
                                       button=Qt.RightButton))
    assert arrow.head_length == before[0]
    assert {op.id: op.key for op in window.ops.all()}["transform.scale"] \
        == "S"


def test_the_model_is_switched_in_place(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    analysis = measure.run("Onset point", scan, 60.0, 120.0)
    window.refresh()
    window.doc.select_only([analysis])
    window.edit_object(analysis)
    dialog = window._dialogs[-1]
    dialog.model.setCurrentIndex(dialog.model.findData("Endset point"))
    assert analysis.model_name == "Endset point"
    assert analysis in scan.analysis_objects             # the same object
    assert analysis.summary(window.doc).startswith("*T*_{end} = ")
    assert dialog.windowTitle().startswith("Endset point")
    window.undo.undo()
    assert analysis.model_name == "Onset point"


def test_start_and_end_are_typed_with_or_without_a_unit(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    analysis = measure.run("Peak Integration (enthalpy)", scan, 70.0, 150.0)
    window.refresh()
    window.doc.select_only([analysis])
    window.edit_object(analysis)
    dialog = window._dialogs[-1]
    assert dialog.start.text().startswith("70.00")
    dialog.start.setText("80")                        # the axis unit
    dialog.end.setText("284 F")                       # 140 degC
    dialog._typed_interval()
    low, high = analysis.cursors()
    assert low == pytest.approx(80.0, abs=1.0)
    assert high == pytest.approx(140.0, abs=1.0)
    assert dialog.end.text().startswith("%.2f" % high)
    assert window.undo.can_undo()
    dialog.end.setText("banana")
    dialog._typed_interval()
    assert "d04040" in dialog.end.styleSheet()         # refused, marked


def test_a_file_analysis_retyped_becomes_the_panels(window):
    scan = window.doc.scans[0]
    scan._analyses = None
    scan.sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C #1": {
            "Onset point": [{"segment": 1, "Onset x": "90,0 \u00b0C",
                             "Onset cursor x": "60,0 \u00b0C",
                             "Transition cursor x": "120,0 \u00b0C"}]}}
    analysis = scan.analysis_objects[0]
    assert analysis.source == "file"
    assert window.retype_interval(analysis, 65.0, 125.0) is analysis
    assert analysis.source == "panel"
    assert analysis.cursors() == pytest.approx([65.0, 125.0])


def test_the_analysis_window_says_it_briefly(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    analysis = measure.run("Onset point", scan, 60.0, 120.0)
    window.refresh()
    window.doc.select_only([analysis])
    window.edit_object(analysis)
    dialog = window._dialogs[-1]
    assert dialog.visible.text() == "Show"
    assert dialog.interval.text() == "Show interval markers"
    assert dialog.auto.text() == "Same as scan"
    assert dialog.note.text().startswith("Adjust the values as needed.")
    assert not hasattr(dialog, "shown_on")
    assert "T" in dialog.preview.text() and "<sub>on</sub>" in \
        dialog.preview.text()
    # readable: labels selectable, tooltips wrapped
    dialog.show()
    assert dialog.note.textInteractionFlags() & Qt.TextSelectableByMouse
    assert dialog.start.toolTip().startswith("<qt>")
    dialog.close()


def test_a_unit_in_the_number_format_converts(window):
    from dscpanel.core import labels, numbers
    first, _second = _two_onsets(window)             # 90 degC
    first.number_format = labels.normalise_format("%.0f f")
    assert first.number_format == "%.0f \u00b0F"
    assert labels.render(first, window.doc).text == \
        "*T*_{on} = 194 \u00b0F"
    # a unit written after {} still wins
    first.label = "{} K"
    assert labels.render(first, window.doc).text == "363 K"
    # a unit the quantity cannot be in, in ITS OWN format, is refused
    first.label = None
    first.number_format = labels.normalise_format("%.1f J/g")
    rendered = labels.render(first, window.doc)
    assert rendered.text == "*T*_{on} = 90.0 \u00b0C"
    assert rendered.problems[0][0] == "unit"
    # ...but an axis format never takes a unit: its numbers sit on ticks
    assert numbers.normalise("%.1f K") is None
    assert labels.normalise_format("%.1f banana") is None


def test_typed_temperatures():
    from dscpanel.core import units as u
    assert u.parse_temperature("98", u.TEMP_C) == pytest.approx(98.0)
    assert u.parse_temperature("98", u.TEMP_K) == pytest.approx(-175.15)
    for text in ("208.4 F", "208.4f", "208.4 \u00b0F", "208.4 degF"):
        assert u.parse_temperature(text) == pytest.approx(98.0)
    assert u.parse_temperature("371.15 k") == pytest.approx(98.0)
    assert u.parse_temperature("98,5 C") == pytest.approx(98.5)
    assert u.parse_temperature("hot") is None


def test_a_marker_format_with_a_unit_converts_the_offset(window):
    window.run_op("figure.offset_markers")
    scan = window.doc.scans[1]
    scan.offset = 0.5                                # W/g on the axis
    marker = scan.marker
    marker.number_format = "%.1f mW"
    mass = scan.sample.mass_g
    if mass:
        assert window.plot.marker_text(marker) == "%.1f mW" % (0.5 * mass
                                                                * 1000)
    else:
        assert window.plot.marker_text(marker) == "? mW"


# ------------------------------------------------------------ round 17
def test_the_framing_is_saved_with_the_figure(window, tmp_path, sample):
    """Christian's glitch: a y range narrowed to show a peak's label came
    back fitted when the session was reopened. The view is in the file."""
    from dscpanel.core import session
    plot = window.plot
    plot.grab()
    lo, hi = plot.view_y()
    plot.set_view_y(lo, lo + (hi - lo) / 3.0)
    narrowed = plot.view_y()
    path = str(tmp_path / "framed.dscpanel")
    window.save_session(path=path)
    loaded, _problems = session.load(
        path, lambda _p: model.Sample(sample.path, sample.data))
    assert loaded.view["y"] == pytest.approx(narrowed)
    # and the window puts it back on opening
    window.doc.view = None
    window.plot.fit()
    import dscpanel.ui.window as window_module
    real = window_module.session.load
    window_module.session.load = lambda p, _r: (loaded, [])
    try:
        window.open_session(path)
    finally:
        window_module.session.load = real
    assert window.plot.view_y() == pytest.approx(narrowed)
    assert not window.is_modified()


def test_bahnschrift_with_a_fallback():
    from dscpanel.core import style
    from dscpanel.ui.plot import FALLBACK_FAMILIES
    assert style.builtin("font_family") == "Bahnschrift"
    assert "Arial" in FALLBACK_FAMILIES and "DejaVu Sans" in FALLBACK_FAMILIES


def test_the_figure_font_lists_its_fallbacks(window):
    font = window.plot.figure_font()
    assert font.families()[0] == "Bahnschrift"
    assert "DejaVu Sans" in font.families()
    assert "plt.rcParams['font.family'] = ['Bahnschrift', 'sans-serif']" \
        in export.driver_source(window.doc)


def test_the_legend_has_no_frame_until_asked(window, tmp_path, sample):
    import json
    from dscpanel.core import session
    assert window.doc.legend.show_frame is False          # frameon=False
    window.doc.legend.show_frame = True                   # chosen
    path = tmp_path / "framed.dscpanel"
    session.save(window.doc, str(path))
    reader = (lambda _p: model.Sample(sample.path, sample.data))
    assert session.load(str(path), reader)[0].legend.show_frame is True
    # an older file's True was the old default, not a choice
    state = json.loads(path.read_text(encoding="utf-8"))
    state["version"] = 4
    path.write_text(json.dumps(state), encoding="utf-8")
    assert session.load(str(path), reader)[0].legend.show_frame is False


def test_a_stale_generated_label_in_a_version_4_file(window, tmp_path,
                                                     sample):
    import json
    from dscpanel.core import measure, session
    scan = window.doc.scans[0]
    made = measure.run("Peak Integration (enthalpy)", scan, 70.0, 150.0)
    made.label = "\\Delta*H* = 2.492 J/g"            # not the measurement
    path = tmp_path / "v4.dscpanel"
    session.save(window.doc, str(path))
    state = json.loads(path.read_text(encoding="utf-8"))
    state["version"] = 4
    path.write_text(json.dumps(state), encoding="utf-8")
    loaded, _problems = session.load(
        str(path), lambda _p: model.Sample(sample.path, sample.data))
    again = [a for a in loaded.scans[0].analysis_objects
             if a.source == "panel"][0]
    assert again.label is None                 # the template, live number


def test_a_txt_analysis_is_offered_on_every_scan_of_its_step():
    """Round 17: an analysis a .txt export names by STEP is offered under
    every segment with that step name, and attributed by being shown on
    the one it belongs to."""
    from conftest import make_data
    data = make_data(segments=3, analyses={
        "Ramp 10,00 C/min to 250 C": {
            "Onset point": [{"Onset x": "61,08 \u00b0C"}]}})
    sample = model.Sample("x.tri", data)
    assert len(sample.analyses_for(0)) == 1        # first heating
    assert len(sample.analyses_for(2)) == 1        # second heating too
    assert sample.analyses_for(1) == []            # the cooling: not its step
    doc = model.Document()
    doc.add_sample(sample, [0, 2])
    first, second = [s.analysis_objects[0] for s in doc.scans]
    assert not first.certain and not second.certain
    second.visible = True                          # shown on ITS scan
    assert second.certain and not first.certain


def test_show_every_analysis_leaves_the_step_name_ones_alone(window):
    scan = window.doc.scans[0]
    scan._analyses = None
    scan.sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C": {
            "Onset point": [{"Onset x": "61,08 \u00b0C"}]},
        "Ramp 10,00 C/min to 250 C #1": {
            "Onset point": [{"segment": 1, "Onset x": "80,0 \u00b0C"}]}}
    window.doc.select_only([scan])
    window.set_analyses(True)
    shown = {a.attribution: a.visible for a in scan.analysis_objects}
    assert shown == {"cached curve": True, "by step name": False}


def _key(plot, key, text=""):
    plot.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key,
                                 Qt.NoModifier, text))


def test_pivot_keys_reach_all_nine_points(window):
    label = window.add_label("a longer label", at=QPointF(400, 250))
    plot = window.plot
    plot.grab()
    window.doc.select_only([label])
    assert plot.start_scale()
    assert plot._scale["pivot"] == (0.0, 1.0)            # bottom left
    reached = {plot._scale["pivot"]}
    for keys in ("x", "xx", "y", "yy", "xxy", "xm", "xxm", "ym", "yym", "c"):
        plot._scale["pivot"], plot._scale["last"] = (0.0, 1.0), None
        for key in keys:
            plot.pivot_key(key)
        reached.add(plot._scale["pivot"])
    assert reached == {(fx, fy) for fx in (0.0, 0.5, 1.0)
                       for fy in (0.0, 0.5, 1.0)}
    plot._scale["pivot"], plot._scale["last"] = (0.0, 1.0), None
    plot.pivot_key("x")
    plot.pivot_key("m")
    assert plot._scale["pivot"] == (0.0, 0.5)             # S X M
    assert plot.pivot_name((0.0, 0.5)) == "middle left"
    plot._finish_transform(cancel=True)


def test_a_scale_keeps_its_pivot_where_it_is(window):
    label = window.add_label("a longer label", at=QPointF(400, 250))
    plot = window.plot
    plot.grab()
    window.doc.select_only([label])
    plot.start_scale()
    entry = plot._scale["entries"][0]
    before = plot._pivot_point(entry)
    _key(plot, Qt.Key_2, "2")
    rect = plot.plot_rect()
    live = dict(entry, anchor=plot.artist_point(label, rect),
                box=plot.artist_box(label, rect))
    after = plot._pivot_point(live)
    # bottom left stays, within the box's fixed padding, which does not scale
    assert after == pytest.approx(before, abs=5.0)
    _key(plot, Qt.Key_Return)
    assert label.size == pytest.approx(20.0)


def test_r_rotates_a_label_about_its_centre(window):
    label = window.add_label("a longer label", at=QPointF(400, 250))
    plot = window.plot
    plot.grab()
    window.doc.select_only([label])
    centre = plot.artist_point(label)            # anchored at its centre
    window.run_op("arrange.reset")               # R, with a label selected
    assert plot.scaling() and plot._scale["mode"] == "rotate"
    _key(plot, Qt.Key_9, "9")
    _key(plot, Qt.Key_0, "0")
    _key(plot, Qt.Key_Return)
    assert label.rotation == pytest.approx(90.0)
    assert plot.artist_point(label) == pytest.approx(centre, abs=1.0)
    plot.grab()
    box = [b for lb, b in plot._text_boxes if lb is label][0]
    assert box.height() > box.width()            # it stands upright now
    window.undo.undo()
    assert label.rotation == 0.0


def test_the_arrow_is_not_rotated(window):
    window.doc.select_only([window.doc.arrow])
    assert not window.rotatable_selected()
    assert not window.run_op("arrange.reset")
    assert not window.plot.scaling()


def test_s_and_r_keep_their_keys_from_the_window(window):
    label = window.add_label("note", at=QPointF(400, 250))
    window.plot.grab()
    window.doc.select_only([label])
    window.plot.start_scale()
    override = QKeyEvent(QKeyEvent.Type.ShortcutOverride, Qt.Key_M,
                         Qt.NoModifier, "m")
    assert window.plot.event(override) and override.isAccepted()
    window.plot._finish_transform(cancel=True)


def test_analysis_arrow_offset_is_typed_and_shifted(window):
    first, second = _two_onsets(window)
    window.doc.select_only([first, second])
    window.edit_object(first)
    dialog = window._dialogs[-1]
    assert dialog.arrow_default.isChecked()         # automatic side
    dialog.arrow_offset.setValue(30.0)              # 30 above the curve
    assert first.label_dy == second.label_dy == pytest.approx(-30.0)
    second.label_dy = -50.0
    dialog.arrow_shift.setValue(10.0)               # both, 10 higher
    assert (first.label_dy, second.label_dy) == pytest.approx((-40.0, -60.0))
    dialog.accept()


def test_a_long_problem_under_a_label_is_not_cut_off(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    analysis = measure.run("Peak Integration (enthalpy)", scan, 70.0, 150.0)
    analysis.label = "\\Delta*H* = 2.492 J/g (typed by hand, as it was)"
    window.refresh()
    window.doc.select_only([analysis])
    window.edit_object(analysis)
    dialog = window._dialogs[-1]
    dialog.show()
    for label in (dialog.preview, dialog.results):
        assert label.height() >= label.heightForWidth(label.width()) - 1
    dialog.close()


# ------------------------------------------------------------ round 18
@pytest.mark.parametrize("anchor", ["center", "top right", "bottom left"])
@pytest.mark.parametrize("keys", ["", "c", "xx", "yym"])
def test_the_scale_pivot_stays_put_whatever_the_anchor(window, anchor, keys):
    """Round 18: with the anchor anywhere but bottom left, a scale drifted,
    because a box does not grow in proportion (font sizes step, padding
    does not scale). The pivot is now measured back into place."""
    legend = window.doc.legend
    legend.visible = True
    legend.anchor = anchor
    plot = window.plot
    plot.grab()
    window.doc.select_only([legend])
    assert plot.start_scale()
    for key in keys:
        plot.pivot_key(key)
    entry = plot._scale["entries"][0]
    before = plot._pivot_point(entry)
    for factor in ("1.37", "2.5", "0.6"):
        plot._scale["typed"] = factor
        plot._update_transform()
        rect = plot.plot_rect()
        live = dict(entry, anchor=plot.artist_point(legend, rect),
                    box=plot.artist_box(legend, rect))
        assert plot._pivot_point(live) == pytest.approx(before, abs=1.0)
    plot._finish_transform(cancel=True)


def test_the_legend_line_width(window, tmp_path, sample):
    from dscpanel.core import session
    from dscpanel.ui.dialogs import LegendSettings
    legend = window.doc.legend
    assert legend.line_width is None                  # each scan's own
    dialog = LegendSettings(window, legend)
    dialog.line_width.setValue(2.5)
    assert legend.line_width == 2.5
    dialog.line_width.setValue(0.0)
    assert legend.line_width is None
    legend.line_width = 3.0
    path = tmp_path / "lw.dscpanel"
    session.save(window.doc, str(path))
    loaded, _p = session.load(
        str(path), lambda _p: model.Sample(sample.path, sample.data))
    assert loaded.legend.line_width == 3.0


def test_latex_between_dollars(window):
    from dscpanel.ui.plot import markup_runs
    assert markup_runs("(Hbc)$_{1.00}$") == [("(Hbc)", False, False),
                                               ("1.00", False, "sub")]
    # mathtext's rule: without braces only one character is lowered
    assert markup_runs("$_1.00$")[0] == ("1", False, "sub")
    assert markup_runs("$x^2$") == [("x", True, False), ("2", False, "sup")]
    runs = markup_runs("$T \\quad / \\quad \\mathrm{K}$")
    assert runs[0] == ("T", True, False)                 # a variable: italic
    assert runs[-1][0].endswith("K") and not runs[-1][1]  # mathrm: upright
    assert markup_runs("price \\$5") == [("price $5", False, False)]
    # an added label is drawn with it, so its box is the markup's width
    label = window.add_label("(Hbc)$_{1.00}$", at=QPointF(300, 200))
    window.plot.grab()
    from PySide6.QtGui import QFontMetrics
    box = window.plot._label_box(label, window.plot.plot_rect(),
                                 window.plot.figure_font())
    font = window.plot.figure_font()
    font.setPointSizeF(window.plot.style_of(label, "size"))
    assert box.width() < QFontMetrics(font).horizontalAdvance(label.text)


def test_the_basic_colours_start_with_the_plotters():
    from PySide6.QtWidgets import QColorDialog
    from dscpanel.ui.dialogs import PLOTTER_COLOURS, install_basic_colours
    assert install_basic_colours() == 48
    # read left to right: Qt numbers the grid down its six rows first
    assert QColorDialog.standardColor(0).name() == PLOTTER_COLOURS[0]
    assert QColorDialog.standardColor(6).name() == PLOTTER_COLOURS[1]
    assert QColorDialog.standardColor(1).name() == PLOTTER_COLOURS[8]


def test_a_sweep_down_the_outliner_boxes_is_one_step(window, qapp):
    outliner = window.outliner
    window.show()
    rows = [item for item in outliner._items()
            if outliner._key(item) and outliner._key(item)[0] == "scan"]
    assert len(rows) == 2 and all(s.visible for s in window.doc.scans)

    def box_point(item):
        cell = outliner.visualItemRect(item)
        left = outliner.visualRect(outliner.indexFromItem(item, 0)).left()
        return QPointF(left + 5, cell.center().y())

    first, second = box_point(rows[0]), box_point(rows[1])
    outliner.mousePressEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, first, first, Qt.LeftButton,
        Qt.LeftButton, Qt.NoModifier))
    outliner.mouseMoveEvent(QMouseEvent(
        QMouseEvent.Type.MouseMove, second, second, Qt.NoButton,
        Qt.LeftButton, Qt.NoModifier))
    outliner.mouseReleaseEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, second, second, Qt.LeftButton,
        Qt.NoButton, Qt.NoModifier))
    for _ in range(4):
        qapp.processEvents()
    assert not any(s.visible for s in window.doc.scans)
    window.undo.undo()                              # ONE step
    assert all(s.visible for s in window.doc.scans)
    window.hide()


def test_the_outliner_state_column_is_never_cut_off(window):
    from PySide6.QtWidgets import QHeaderView
    header = window.outliner.header()
    assert header.sectionResizeMode(0) == QHeaderView.Stretch
    assert header.sectionResizeMode(1) == QHeaderView.ResizeToContents


def test_the_theme_is_in_the_edit_menu(window):
    theme = window.menus["Theme"]
    texts = [a.text() for a in theme.actions()]
    assert any("light" in t for t in texts) and len(texts) == 2
    window._sync_menu_state()
    ticked = [a.text() for a in theme.actions() if a.isChecked()]
    assert ticked == ["Theme: {}".format(window.doc.theme)]


def test_an_export_in_the_theme_or_for_a_page(window, tmp_path):
    from PySide6.QtGui import QImage
    from dscpanel.ui import plot as plot_module
    window.set_theme(plot_module.THEME_DARK)
    window.ask_export = lambda: (str(tmp_path / "dark.png"), False)
    window.export_image()
    dark = QImage(str(tmp_path / "dark.png"))
    assert QColorFrom(dark.pixel(2, 2)).lightness() < 80
    window.ask_export = lambda: (str(tmp_path / "page.png"), True)
    window.export_image()
    page = QImage(str(tmp_path / "page.png"))
    assert QColorFrom(page.pixel(2, 2)).lightness() > 240


def QColorFrom(value):
    from PySide6.QtGui import QColor
    return QColor.fromRgba(value)


def test_an_svg_export_is_clipped_to_the_axes(window, tmp_path):
    import xml.etree.ElementTree as ElementTree
    plot = window.plot
    plot.grab()
    lo, hi = plot.view_y()
    plot.set_view_y(lo, lo + (hi - lo) / 4.0)       # curves run off the top
    path = window.export_image(str(tmp_path / "clipped.svg"), light=True)
    text = open(path, encoding="utf-8").read()
    assert "clip-path=" in text and "<clipPath" in text
    assert plot.CLIP_OPEN not in text and plot.CLIP_CLOSE not in text
    ElementTree.fromstring(text.encode("utf-8"))        # still well formed


def test_spine_numbers_and_caption_are_three_windows(window):
    plot = window.plot
    plot.grab()
    axis = window.doc.axes["x"]
    assert axis.mirror and axis.mirror_ticks            # Origin's frame
    spine = plot.axis_spine_rect("x").center()
    numbers = plot.axis_numbers_rect("x").center()
    assert plot.object_at(spine) is axis and plot.axis_hit() == "spine"
    assert plot.object_at(numbers) is axis and plot.axis_hit() == "numbers"
    # a click on the spine selects nothing: no orange on the frame
    plot.select_at(spine)
    assert not axis.selected
    from dscpanel.ui.dialogs import AxisSettings, CaptionSettings, \
        NumberSettings
    for part, kind in (("spine", AxisSettings), ("numbers", NumberSettings),
                       ("caption", CaptionSettings)):
        window.edit_object(axis, part=part)
        assert isinstance(window._dialogs[-1], kind)
        window._dialogs[-1].close()


def test_the_ticks_are_set_in_the_spine_window(window):
    from dscpanel.ui.dialogs import AxisSettings
    axis = window.doc.axes["y"]
    dialog = AxisSettings(window, axis, window.doc)
    assert dialog.step_auto.isChecked()
    dialog.step_auto.setChecked(False)
    dialog.step.setValue(0.25)
    dialog.minor_count.setValue(4)
    dialog.mirror_ticks.setChecked(False)
    assert axis.major_step == 0.25 and axis.minor_count == 4
    assert axis.mirror and not axis.mirror_ticks
    lo, hi = window.plot.view_y()
    assert window.plot.tick_step(axis, lo, hi) == 0.25
    source = export.driver_source(window.doc)
    assert "MultipleLocator(0.25)" in source
    assert "AutoMinorLocator(4)" in source
    assert "ax.tick_params(axis='y', which='both', right=False" in source
    assert "ax.tick_params(axis='x', which='both', top=True" in source


def test_an_interval_mark_is_cut_to_the_axes():
    from PySide6.QtCore import QRectF
    from dscpanel.ui.plot import _clip_segment
    box = QRectF(10.0, 10.0, 100.0, 50.0)
    # a dash left of the axes (a bound outside the view) is not drawn
    assert _clip_segment(QPointF(2.0, 20.0), QPointF(2.0, 28.0), box) is None
    # one across the edge is cut at it
    a, b = _clip_segment(QPointF(0.0, 30.0), QPointF(50.0, 30.0), box)
    assert (a.x(), b.x()) == pytest.approx((10.0, 50.0))
    inside = _clip_segment(QPointF(20.0, 20.0), QPointF(30.0, 25.0), box)
    assert inside[0] == QPointF(20.0, 20.0) and inside[1] == QPointF(30.0,
                                                                    25.0)


# ------------------------------------------------------------ round 19
def test_an_export_carries_no_selection(window, tmp_path):
    from PySide6.QtGui import QImage
    window.select_all(False)
    plain = window.export_image(str(tmp_path / "plain.png"), light=True)
    window.select_all(True)
    chosen = window.export_image(str(tmp_path / "chosen.png"), light=True)
    assert QImage(plain) == QImage(chosen)
    assert all(s.selected for s in window.doc.scans)     # put back after


def test_artists_stay_inside_the_axes_box(window):
    plot = window.plot
    doc = window.doc
    doc.legend.visible = True
    plot.grab()
    rect = plot.plot_rect()
    for artist in (doc.legend, doc.arrow):
        doc.select_only([artist])
        assert plot.start_grab([artist])
        plot._update_move(QPointF(plot._move["start"].x() - 5000,
                                  plot._move["start"].y() + 5000))
        box = plot.rotated_bounds(artist, plot.artist_box(artist, rect),
                                  rect)
        # (the arrow's box is whole pixels: a pixel of rounding)
        assert box.left() >= rect.left() - 1.0
        assert box.bottom() <= rect.bottom() + 1.0
        plot._finish_move()


def test_the_stack_order_is_per_object(window):
    doc = window.doc
    label = window.add_label("note", at=QPointF(300, 200))
    scan = doc.scans[0]
    assert model.z_of(scan) < model.z_of(label)          # curves below
    doc.select_only([scan])
    window.run_op("order.front")
    assert model.z_of(scan) > model.z_of(label)
    plot = window.plot
    items = plot._paint_items(None, plot.plot_rect())
    assert items[-1][0] == model.z_of(scan)              # drawn last
    window.undo.undo()
    assert model.z_of(scan) < model.z_of(label)
    doc.select_only([label])
    window.run_op("order.back")
    assert min(model.z_of(o) for o in window.stack_objects()) == \
        model.z_of(label)
    keys = {op.id: op.key for op in window.ops.all()}
    assert keys["order.front"] == "Ctrl+Shift+PgUp"


def test_chemdraw_alignment_of_artists(window):
    plot = window.plot
    first = window.add_label("a short one", at=QPointF(200, 150))
    second = window.add_label("a much longer label", at=QPointF(420, 260))
    plot.grab()
    window.doc.select_only([first, second])
    rect = plot.plot_rect()

    def boxes():
        return [plot.rotated_bounds(a, plot.artist_box(a, rect), rect)
                for a in (first, second)]

    window.run_op("arrange.align_left")
    a, b = boxes()
    assert a.left() == pytest.approx(b.left(), abs=0.5)
    window.run_op("arrange.align_top")
    a, b = boxes()
    assert a.top() == pytest.approx(b.top(), abs=0.5)
    window.run_op("arrange.align_centre")
    a, b = boxes()
    assert a.center().x() == pytest.approx(b.center().x(), abs=0.5)
    window.undo.undo()
    keys = {op.id: op.key for op in window.ops.all()}
    assert keys["arrange.align_right"] == "Ctrl+Shift+Alt+R"
    assert keys["arrange.align_bottom"] == "Ctrl+Shift+Alt+B"


def test_an_integral_label_slides_along_its_interval_with_x(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    area = measure.run("Peak Integration (enthalpy)", scan, 70.0, 150.0)
    window.refresh()
    plot = window.plot
    plot.grab()
    window.doc.select_only([area])
    assert plot.start_grab([area])
    start = plot._move["start"]
    plot._update_move(QPointF(start.x() + 40, start.y() - 30))
    assert area.label_at is None                       # vertical by default
    plot._key_during_move(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_X,
                                    Qt.NoModifier, "x"))
    plot._update_move(QPointF(start.x() + 4000, start.y()))
    assert area.label_at == pytest.approx(150.0)        # stops at the end
    plot._finish_move()
    assert plot.label_celsius(area) == pytest.approx(150.0)
    window.undo.undo()
    assert area.label_at is None
    # an onset labels a point: X does not slide it
    onset = measure.run("Onset point", scan, 60.0, 120.0)
    assert not onset.slides and area.slides


def test_a_slower_second_click_steps_down_the_stack(window):
    plot = window.plot
    doc = window.doc
    doc.scans[1].offset = 0.0               # the two curves overlap
    window.refresh()
    plot.grab()
    trace = plot._trace_of(doc.scans[0])
    point = QPointF(float(trace.px[len(trace.px) // 2]),
                    float(trace.py[len(trace.py) // 2]))
    found = [o for o in plot.objects_at(point)
             if not isinstance(o, model.Axis)]
    assert len(found) >= 2
    clock = [100.0]
    plot._clock = lambda: clock[0]

    def click():
        at = (point.x(), point.y())
        plot.mousePressEvent(_press(plot, at))
        plot.mouseReleaseEvent(_release(plot, at))

    click()
    first = [o for o in doc.selected()]
    clock[0] += 0.5                                  # 350 to 700 ms: a step
    click()
    second = [o for o in doc.selected()]
    assert second and second != first
    clock[0] += 0.5
    click()
    assert [o for o in doc.selected()] != second or len(found) == 2
    clock[0] += 2.0                                  # slower: a new click
    click()
    assert [o for o in doc.selected()] == [found[0]]


def test_tabs_one_per_figure(window, tmp_path, sample):
    from dscpanel.core import session
    first = window.doc
    assert len(window.figures()) == 1
    window.new_figure()
    assert len(window.figures()) == 2 and window.doc is not first
    assert window.doc.scans == []
    # a session opens in a tab of its own - unless the tab is a new one
    path = str(tmp_path / "one.dscpanel")
    session.save(first, path)
    import dscpanel.ui.window as window_module
    real = window_module.session.load
    window_module.session.load = lambda p, r: real(
        p, lambda _p: model.Sample(sample.path, sample.data))
    try:
        window.open_session(path)
    finally:
        window_module.session.load = real
    assert len(window.figures()) == 2               # the empty one reused
    assert window._tabs.tabText(window._tabs.currentIndex()) == "one.dscpanel"
    # switching tabs switches the figure, its plot and its undo history
    window._tabs.setCurrentIndex(0)
    assert window.doc is first
    window._tabs.setCurrentIndex(1)
    assert window.doc is not first


def test_closing_tabs_asks_then_leaves_the_blank_window(window):
    closed = []
    window.close = lambda: closed.append("window") or True
    asked = []
    window.ask_to_save = lambda: asked.append(1) or "discard"
    window.new_figure()
    assert window.close_step() == "tab"             # the new one: clean
    assert asked == []
    assert window.close_step() == "tab"             # the loaded one asks
    assert asked == [1]
    assert window.figures() == []
    assert window._stack.currentWidget() is window._empty
    assert not window.ops.get("view.fit").enabled(window)
    assert window.close_step() is None and closed == ["window"]
    # Ctrl+N, or opening something, brings a tab back
    window.run_op("file.new")
    assert len(window.figures()) == 1


def test_the_window_remembers_its_place(qapp, sample):
    from dscpanel.core import style
    from dscpanel.ui.window import MainWindow
    first = MainWindow()
    first.resize(777, 555)
    first.save_layout()
    assert style.window_state() and "geometry" in style.window_state()
    style.load_preferences()                         # as a new start would
    second = MainWindow()
    assert second.restore_layout()
    assert second.size().width() == 777


def test_m_sets_the_y_range_too(window, monkeypatch):
    from dscpanel.ui import dialogs
    monkeypatch.setattr(dialogs.RangeDialog, "exec", lambda self: 1)
    plot = window.plot
    plot.grab()
    before_y = plot.view_y()
    real = window.x_range_dialog

    def only_x():
        dialog = real()
        assert dialog.y_low_edit is not None        # the y pair is there
        dialog.low_edit.setText("70")
        dialog.high_edit.setText("90")
        return dialog
    window.x_range_dialog = only_x
    window.run_op("view.x_range")
    assert plot.view_x() == (70.0, 90.0)
    assert plot.view_y() == pytest.approx(before_y)  # untouched: unchanged

    def with_y():
        dialog = real()
        dialog.y_low_edit.setText("-1")
        dialog.y_high_edit.setText("0,5")
        return dialog
    window.x_range_dialog = with_y
    window.run_op("view.x_range")
    assert plot.view_y() == (-1.0, 0.5)
    window.undo.undo()                               # one step
    assert plot.view_x() == (70.0, 90.0)
    assert plot.view_y() == pytest.approx(before_y)


def test_the_driver_carries_the_legend_and_the_labels(window):
    from dscpanel.core.export import mathtext
    window.doc.legend.visible = True
    label = window.add_label("\\Delta*H* = {}", at=QPointF(300, 200))
    label.rotation = 30.0
    source = export.driver_source(window.doc)
    assert "leg = ax.legend(" in source and "frameon=False" in source
    assert "ax.text(" in source and "rotation=30" in source
    assert mathtext("\\Delta*H*") == "$\\Delta\\mathit{H}$"
    assert mathtext("*T*_{on}") == "$\\mathit{T}_{\\mathrm{on}}$"
    assert mathtext("(Hbc)$_{1.00}$") == "(Hbc)$_{1.00}$"


def test_a_picture_is_an_artist(window, tmp_path, sample):
    from PySide6.QtGui import QColor, QImage
    from dscpanel.core import session
    picture = QImage(120, 60, QImage.Format_ARGB32)
    picture.fill(QColor("#336699"))
    image = window.add_image(picture, at=QPointF(300, 200))
    assert image in window.doc.images and image.selected
    assert image.width == pytest.approx(120.0)
    plot = window.plot
    plot.grab()
    box = plot.artist_box(image, plot.plot_rect())
    assert box.height() == pytest.approx(60.0)          # its proportions
    # S scales it, R turns it, like any artist
    window.doc.select_only([image])
    assert plot.start_scale()
    plot._scale["typed"] = "2"
    plot._update_transform()
    plot._finish_transform()
    assert image.width == pytest.approx(240.0)
    assert window.rotatable_selected()
    # kept in the session, picture and all
    path = tmp_path / "pic.dscpanel"
    session.save(window.doc, str(path))
    loaded, _p = session.load(
        str(path), lambda _p: model.Sample(sample.path, sample.data))
    assert len(loaded.images) == 1
    assert plot.image_pixels(loaded.images[0]).width() == 120
    # Delete takes it off, Ctrl+Z puts it back
    window.doc.select_only([image])
    window.run_op("object.remove")
    assert image not in window.doc.images
    window.undo.undo()
    assert image in window.doc.images


def test_ctrl_v_pastes_a_picture(window, qapp):
    from PySide6.QtGui import QColor, QImage
    picture = QImage(40, 40, QImage.Format_ARGB32)
    picture.fill(QColor("#aa3300"))
    qapp.clipboard().setImage(picture)
    before = len(window.doc.images)
    window.run_op("edit.paste")
    assert len(window.doc.images) == before + 1
