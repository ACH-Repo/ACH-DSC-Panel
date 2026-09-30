"""The axes and the page margins, from testing on a real figure -
double-clicking the y axis, the margins following an axis to its
other side, numbers at the corners of the box never cut off, hidden
numbers, locking a caption's move, offset markers per selection, and what
the numbers' Format box does.
"""

import pytest

from dscpanel.core import figure as figure_module
from dscpanel.core import model, numbers, session

from test_window import _double, _press, _release


@pytest.fixture
def window(qapp, sample):
    from dscpanel.ui.window import MainWindow
    win = MainWindow()
    win.resize(900, 560)
    win._sample_loaded(sample)
    win.toggle_segment(sample, 1, True)
    win.undo.clear()
    return win


def _exact(win, left=4.0, right=0.3):
    layout = win.doc.figure
    layout.mode = figure_module.MODE_SIZE
    layout.unit = "cm"
    layout.width, layout.height = 12.0, 9.0
    layout.margin_left, layout.margin_right = left, right
    layout.margin_top, layout.margin_bottom = 0.3, 1.5
    win.refresh()
    win.plot.fit_page()
    win.plot.grab()
    return layout


def _margins(layout):
    return tuple(getattr(layout, "margin_" + side)
                 for side in figure_module.MARGIN_SIDES)


# ------------------------------------------------- double-clicking an axis
def test_the_y_axis_opens_with_its_caption_hidden(window):
    """`visible` is the caption's: hiding it left the spine and the numbers
    unclickable."""
    plot = window.plot
    axis = window.doc.axes["y"]
    axis.visible = False
    window.refresh()
    plot.grab()
    for part, rect in (("spine", plot.axis_spine_rect("y")),
                       ("numbers", plot.axis_numbers_rect("y"))):
        assert plot.object_at(rect.center()) is axis, part
        assert plot.axis_hit() == part


def test_the_axis_line_and_its_inward_ticks_are_the_spine(window):
    from PySide6.QtCore import QPointF
    plot = window.plot
    # Anything within the pick distance wins over the frame: the arrow
    # stands at the left edge here.
    window.doc.arrow.visible = False
    window.refresh()
    plot.grab()
    rect = plot.plot_rect()
    y_axis, x_axis = window.doc.axes["y"], window.doc.axes["x"]
    assert y_axis.ticks_inward and y_axis.mirror
    # on the y axis's own line, over its ticks, and on the mirrored line
    middle = rect.top() + rect.height() * 0.37
    for point in (QPointF(rect.left(), middle),
                  QPointF(rect.left() + 3.0, middle),
                  QPointF(rect.right() - 1.0, middle)):
        if plot._trace_at(point) is not None:
            continue                      # a curve there is the curve
        assert plot.object_at(point) is y_axis, point
        assert plot.axis_hit() == "spine"
        assert plot.drag_target(point) is None     # a drag is a box
    point = QPointF(rect.left() + rect.width() * 0.63, rect.bottom() - 2.0)
    if plot._trace_at(point) is None:
        assert plot.object_at(point) is x_axis
    # well inside the box: nothing
    assert not isinstance(plot.object_at(rect.center()), model.Axis)
    # a curve's own points stay the curve's, even close to the frame
    trace = plot.traces[0]
    k = int(trace.px.argmin())
    at = QPointF(float(trace.px[k]), float(trace.py[k]))
    assert plot.object_at(at) is trace.scan


def test_a_click_on_the_spine_clears_the_selection(window):
    plot = window.plot
    plot.grab()
    scan = window.doc.scans[0]
    window.doc.select_only([scan])
    plot.select_at(plot.axis_spine_rect("y").center())
    assert not scan.selected
    assert not window.doc.axes["y"].selected


def test_a_slow_double_click_on_an_axis_still_opens_it(window):
    """Between 0.35 s and the system's double-click time the second click
    is a layer step, which leaves axes out - on an axis it did nothing."""
    plot = window.plot
    plot.grab()
    seen = []
    plot.activated.disconnect(window.edit_object)
    plot.activated.connect(seen.append)
    try:
        clock = [100.0]
        plot._clock = lambda: clock[0]
        where = plot.to_widget(plot.axis_numbers_rect("y").center())
        pos = (where.x(), where.y())
        plot.mousePressEvent(_press(plot, pos))
        plot.mouseReleaseEvent(_release(plot, pos))
        clock[0] += 0.45
        plot.mouseDoubleClickEvent(_double(plot, pos))
        plot.mouseReleaseEvent(_release(plot, pos))
        assert seen == [window.doc.axes["y"]]
        assert plot.axis_hit() == "numbers"
    finally:
        plot.activated.disconnect(seen.append)
        plot.activated.connect(window.edit_object)


# ------------------------------------------------ margins follow the axis
def test_moving_an_axis_to_its_other_side_moves_its_room(window):
    """The margins stayed as they were, and the numbers and the caption
    were cut off until a blade was touched."""
    layout = _exact(window, left=4.0, right=0.3)
    plot = window.plot
    least = dict(zip(figure_module.MARGIN_SIDES, plot.least_page_margins()))
    white = layout.margin_left - least["left"]
    assert white > 0
    box = plot.plot_rect()
    y_axis = window.doc.axes["y"]
    assert window.set_axis_side(y_axis, "right")
    plot.grab()
    now = dict(zip(figure_module.MARGIN_SIDES, plot.least_page_margins()))
    assert layout.margin_right == pytest.approx(now["right"], abs=1e-3)
    assert layout.margin_left == pytest.approx(now["left"] + white, abs=1e-3)
    assert [s for s, _n, _h in plot.overflow()
            if s in ("left", "right")] == []
    # the axes box keeps its size
    assert plot.plot_rect().width() == pytest.approx(box.width(), abs=0.5)
    # one undo step puts the side and both margins back
    window.undo_step()
    assert y_axis.side == "left"
    assert layout.margin_left == pytest.approx(4.0)
    assert layout.margin_right == pytest.approx(0.3)


def test_a_side_switch_on_a_figure_that_sizes_itself_changes_no_margin(
        window):
    layout = window.doc.figure
    before = _margins(layout)
    window.set_axis_side(window.doc.axes["x"], "top")
    assert _margins(layout) == before
    assert window.doc.axes["x"].side == "top"


# ------------------------------------------ numbers at the corners of the box
def test_a_number_at_the_corner_is_held_by_the_margin_beside_it(window):
    """With the y axis on the right, the x axis's first number, centred on
    the box's corner, hangs half over the left margin - which a blade or
    Tighten cut to nothing."""
    _exact(window)
    plot = window.plot
    window.set_axis_side(window.doc.axes["y"], "right")
    window.set_x_range(50.0, 250.0)
    plot.grab()
    x_axis = window.doc.axes["x"]
    first = plot.numbered_ticks(x_axis)[0]
    assert first[0] == pytest.approx(50.0)
    assert first[1] == pytest.approx(plot.plot_rect().left())
    over = plot._numbers_overhang(plot.plot_rect(), plot.figure_font())
    assert over["left"] > 1.0
    needs = dict(zip(figure_module.MARGIN_SIDES, plot.page_needs()))
    assert needs["left"] >= over["left"]
    window.tighten_page_margins()
    plot.grab()
    assert plot.overflow() == []
    rect = plot.plot_rect()
    assert rect.left() >= over["left"] - 0.5


# ------------------------------------------------------- hidden numbers
def test_a_number_can_be_hidden_and_shown_again(window, tmp_path):
    _exact(window)
    plot = window.plot
    window.set_x_range(50.0, 250.0)
    plot.grab()
    x_axis = window.doc.axes["x"]
    assert window.hide_number(x_axis, 50.0)
    plot.grab()
    written = [value for value, _at, _text in plot.numbered_ticks(x_axis)]
    assert 50.0 not in written and 100.0 in written
    every = [value for value, _at, _text in
             plot.numbered_ticks(x_axis, hidden=True)]
    assert 50.0 in every                          # its tick stays
    assert x_axis.hidden_context == plot.axis_context("x")
    # the margin need not hold it any more
    over = plot._numbers_overhang(plot.plot_rect(), plot.figure_font())
    assert over.get("left", 0.0) <= 0.0
    # the right-click menu offers it back
    rect = [box for value, _t, box, hidden in plot.number_boxes(x_axis)
            if value == pytest.approx(50.0)][0]
    plot._cursor = rect.center()
    assert plot.number_at(rect.center())[1:] == (pytest.approx(50.0), "50",
                                                 True)
    menu = window.context_menu_for(x_axis)
    words = [a.text() for a in menu.actions()]
    assert "Show the number 50" in words
    assert any(w.startswith("Show every number") for w in words)
    # it travels in the session, with its unit
    path = str(tmp_path / "hidden.dscpanel")
    state = session.to_state(window.doc)
    assert state["axes"]["x"]["hidden_numbers"] == [50.0]
    session.save(window.doc, path)
    # in another unit it is not a 50 any more
    window.doc.x_unit = "K" if hasattr(window.doc, "x_unit") else ""
    if plot.axis_context("x") != x_axis.hidden_context:
        assert not plot.number_hidden(x_axis, 50.0, 50.0)
    window.undo_step()
    assert x_axis.hidden_numbers == []


def test_the_numbers_window_says_what_is_written_and_hides(window):
    from dscpanel.ui.dialogs import NumberSettings
    window.set_x_range(50.0, 250.0)
    window.plot.grab()
    axis = window.doc.axes["x"]
    dialog = NumberSettings(window, axis, window.doc,
                            on_change=window._live_change)
    assert dialog.written.text().startswith("50, 100")
    dialog.number_format.set_value("%.1f")
    assert dialog.written.text().startswith("50.0, 100.0")
    dialog.hidden_numbers.setText("50; 250")
    dialog._hidden_typed("50; 250")
    assert axis.hidden_numbers == [50.0, 250.0]
    assert "50.0" not in dialog.written.text().split(", ")
    dialog._hidden_typed("fifty")                  # refused, kept as it was
    assert axis.hidden_numbers == [50.0, 250.0]
    dialog.close()


def test_typed_numbers_are_split_like_typed_temperatures():
    assert numbers.values("50; 300") == [50.0, 300.0]
    assert numbers.values("50, 300") == [50.0, 300.0]
    assert numbers.values("50 300") == [50.0, 300.0]
    assert numbers.values("0,5") == [0.5]             # a decimal comma
    assert numbers.values("") == []
    assert numbers.values("50; x") is None


# ---------------------------------------------------- a caption's move
def test_x_and_y_lock_a_captions_move(window):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    plot = window.plot
    plot.grab()
    caption = window.doc.axes["x"]
    window.doc.select_only([caption])
    assert plot.start_grab([caption])
    QTest.keyClick(plot, Qt.Key_X)
    assert plot._move["axis"] == "x"
    gap = plot.style_of(caption, "label_gap")
    plot._update_move(plot._move["start"] + QPointF(40.0, 30.0))
    assert plot.style_of(caption, "label_gap") == pytest.approx(gap)
    assert caption.label_along != pytest.approx(0.5)
    QTest.keyClick(plot, Qt.Key_Y)                    # now only up and down
    plot._update_move(plot._move["start"] + QPointF(40.0, 30.0))
    assert caption.label_along == pytest.approx(0.5)
    assert plot.style_of(caption, "label_gap") != pytest.approx(gap)
    plot._finish_move(cancel=True)


# ------------------------------------------------------- offset markers
def test_offset_markers_go_on_the_selected_scans(window):
    doc = window.doc
    first, second = doc.scans[0], doc.scans[1]
    # a selection: those scans only
    doc.select_only([first])
    window.toggle_offset_markers()
    assert doc.offset_markers
    assert first.marker.visible and not second.marker.visible
    # nothing selected: every scan
    doc.select_all(False)
    window.toggle_offset_markers()
    assert first.marker.visible and second.marker.visible
    # all have one: the selected one's goes
    doc.select_only([second])
    window.toggle_offset_markers()
    assert doc.offset_markers
    assert first.marker.visible and not second.marker.visible
    # and back, for that scan alone
    window.toggle_offset_markers()
    assert first.marker.visible and second.marker.visible
    # nothing selected and every scan has one: all of them go
    doc.select_all(False)
    window.toggle_offset_markers()
    assert not doc.offset_markers
    window.undo_step()
    assert doc.offset_markers


def test_h_hides_a_selected_offset_marker(window):
    doc = window.doc
    doc.select_all(False)
    window.toggle_offset_markers()
    marker = doc.scans[0].marker
    doc.select_only([marker])
    window.hide_selected()
    assert not marker.visible and doc.scans[0].visible
    # the toggle with its scan selected brings it back
    doc.select_only([doc.scans[0]])
    window.toggle_offset_markers()
    assert marker.visible
