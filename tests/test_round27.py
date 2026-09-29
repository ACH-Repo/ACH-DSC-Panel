"""Round 27 (Christian, 2026-09-29): margin gizmos, the colour picker, sums
in number boxes, the crosshair's colour, opaque shading, colour gradients,
DTG. The requests are in docs/NEXT.md and PLAN.md round 27.
"""

import numpy as np
import pytest

from dscpanel.core import dtg, model, numbers, session, shades, style, units

from conftest import make_data
from test_weight import _path, _window, sdt_data, CN81_TRI


@pytest.fixture
def window(qapp, sample):
    from dscpanel.ui.window import MainWindow
    win = MainWindow()
    win.resize(900, 560)
    win._sample_loaded(sample)
    win.toggle_segment(sample, 1, True)
    win.undo.clear()
    return win



# ------------------------------------------------------------------ sums
def test_a_number_box_takes_a_sum():
    assert numbers.evaluate("255-20") == 235.0
    assert numbers.evaluate("(3+4)*2") == 14.0
    assert numbers.evaluate("1,5*2") == 3.0
    assert numbers.evaluate("-4") == -4.0
    for refused in ("255-", "1/0", "2**8", "__import__('os')", "", "abc"):
        assert numbers.evaluate(refused) is None, refused
    assert numbers.is_sum("255-20") and not numbers.is_sum("-4")
    # a typed temperature may be a sum too, with its unit
    assert units.parse_temperature("98+5") == pytest.approx(103.0)
    assert units.parse_temperature("273+0,15 K") == pytest.approx(0.0)


def test_the_spin_boxes_work_a_sum_out_on_enter(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from dscpanel.ui.numbox import NumberBox, WholeBox
    whole = WholeBox()
    whole.setRange(0, 255)
    whole.setValue(255)
    whole.lineEdit().selectAll()
    QTest.keyClicks(whole, "255-20")
    QTest.keyClick(whole, Qt.Key_Return)
    assert whole.value() == 235
    box = NumberBox()
    box.setRange(0.0, 10.0)
    box.setSuffix(" pt")
    box.lineEdit().selectAll()
    QTest.keyClicks(box, "2*3")
    QTest.keyClick(box, Qt.Key_Return)
    assert box.value() == pytest.approx(6.0)
    # a sum past the range is clamped, an unfinished one changes nothing
    box.lineEdit().selectAll()
    QTest.keyClicks(box, "4*4")
    QTest.keyClick(box, Qt.Key_Return)
    assert box.value() == pytest.approx(10.0)
    box.lineEdit().selectAll()
    QTest.keyClicks(box, "3-")
    QTest.keyClick(box, Qt.Key_Return)
    assert box.value() == pytest.approx(10.0)


# ---------------------------------------------------------- colour picker
def test_the_colour_picker_is_live_and_reverts(qapp):
    from PySide6.QtGui import QColor
    from dscpanel.ui.colour import ColourDialog
    heard = []
    dialog = ColourDialog("#1f77b4", live=heard.append)
    assert dialog.colour().name() == "#1f77b4" and heard == []
    dialog.boxes["R"].lineEdit().setText("255-20")
    dialog.boxes["R"].interpretText()
    assert dialog.colour().name() == "#eb77b4" and heard[-1] == "#eb77b4"
    dialog.hex.setText("00ff00")
    dialog._typed_hex()
    assert dialog.colour().name() == "#00ff00"
    # paler is INWARDS: the centre of the wheel is white at full value
    dialog.wheel.pick(dialog.wheel.point_of(0.0, 0.0))
    dialog._bar_picked(1.0)
    assert dialog.colour().name() == "#ffffff"
    # closing keeps, Revert puts back
    dialog.reject()
    assert not dialog.reverted()
    dialog = ColourDialog(QColor("#123456"), live=heard.append)
    dialog.set_colour("#ff0000")
    dialog.revert()
    assert dialog.reverted() and heard[-1] == "#123456"


def test_the_wheel_is_hue_by_angle_and_white_in_the_middle(qapp):
    from PySide6.QtGui import QColor
    from dscpanel.ui.colour import hsv_image
    image = hsv_image(101, 1.0)
    centre = QColor(image.pixel(50, 50))
    right = QColor(image.pixel(98, 50))
    assert centre.saturation() < 10 and centre.value() > 245
    assert right.red() > 240 and right.green() < 30 and right.blue() < 30
    assert QColor.fromRgba(image.pixel(0, 0)).alpha() == 0


# ------------------------------------------------------------- crosshair
def test_the_reticle_keeps_the_theme_accent_on_a_light_page(window):
    """Boombox on a white page drew the light theme's amber reticle
    (Christian, 2026-09-29)."""
    from dscpanel.ui import plot as plot_module
    window.set_theme(plot_module.THEME_BOOMBOX)
    window.set_background("#ffffff")
    assert plot_module.THEME == plot_module.THEME_LIGHT     # the ink
    cursor = plot_module._CURSOR
    green = plot_module.THEMES[plot_module.THEME_BOOMBOX]["_CURSOR"]
    amber = plot_module.THEMES[plot_module.THEME_LIGHT]["_CURSOR"]
    assert cursor.name() != amber.name()
    assert abs(cursor.hueF() - green.hueF()) < 0.02
    assert plot_module._SELECT.name() == cursor.name()
    window.set_background(None)
    assert plot_module._CURSOR.name() == green.name()


# ------------------------------------------------------ opaque shading
def test_opaque_shading_is_the_translucent_colour_over_the_page():
    from PySide6.QtGui import QColor
    from dscpanel.ui.plot import SHADE_ALPHA, shade_fill
    thin = shade_fill("#0000ff", QColor("#ffffff"))
    assert thin.alpha() == SHADE_ALPHA
    solid = shade_fill("#0000ff", QColor("#ffffff"), opaque=True)
    a = SHADE_ALPHA / 255.0
    assert solid.alpha() == 255
    assert solid.blue() == 255
    assert solid.red() == pytest.approx(255 * (1 - a), abs=1)


def test_opaque_shading_is_saved_and_in_the_settings(qapp, window, tmp_path):
    from dscpanel.core import measure
    from dscpanel.ui.dialogs import AnalysisSettings
    scan = window.doc.scans[0]
    analysis = measure.run("Peak Integration (enthalpy)", scan, 80.0, 140.0)
    scan.analysis_objects.append(analysis)
    dialog = AnalysisSettings(window, analysis)
    assert dialog.opaque.value() is None          # the house style's
    dialog.opaque.combo.setCurrentIndex(
        dialog.opaque.combo.findData(style.SHADING_OPAQUE))
    assert analysis.shading == style.SHADING_OPAQUE
    dialog.shade.setChecked(False)
    assert not analysis.shade and not dialog.opaque.isEnabled()
    dialog.shade.setChecked(True)
    path = str(tmp_path / "shade.dscpanel")
    session.save(window.doc, path)
    doc, _problems = session.load(path, lambda p: window.doc.samples[0])
    again = [a for s in doc.scans for a in s.analysis_objects
             if a.source == "panel"]
    assert again and again[0].shading == style.SHADING_OPAQUE
    # and as the house style
    doc.style.analysis_shading = style.SHADING_OPAQUE
    again[0].shading = None
    assert style.value(doc, again[0], 'shading') == style.SHADING_OPAQUE


# ------------------------------------------------------------- gradient
def test_shades_run_dark_to_light_in_one_hue():
    found = shades.shades("#1f77b4", 4, -0.4, 0.5)
    assert len(found) == 4 and found[0] < found[-1]
    assert shades.shade("#ff0000", 0) == "#ff0000"
    assert shades.shade("#ff0000", 1) == "#ffffff"
    assert shades.shade("#ff0000", -1) == "#000000"
    lights = [sum(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in found]
    assert lights == sorted(lights)


def test_the_gradient_dialog_colours_the_stack_top_down(window):
    doc = window.doc
    low, high = doc.scans[0], doc.scans[1]
    low.offset, high.offset = 0.0, 1.0
    for scan in doc.scans:
        scan.selected = True
    old = [s.colour for s in doc.scans]
    assert window.run_op("object.colour_gradient") is True
    dialog = window._dialogs[-1]
    try:
        # the top of the stack is darkest
        assert dialog.scans[0] is high
        top, bottom = high.colour, low.colour
        assert sum(int(top[i:i + 2], 16) for i in (1, 3, 5)) < sum(
            int(bottom[i:i + 2], 16) for i in (1, 3, 5))
        dialog.reverse.setChecked(True)
        assert high.colour == bottom
        dialog.accept()
    finally:
        dialog.close()
    assert window.undo.undo_label() == "colour gradient"
    window.undo_step()
    assert [s.colour for s in doc.scans] == old


# -------------------------------------------------------- margin gizmos
def test_old_fit_margins_convert_to_shares_of_the_axis():
    entries = {"fit_left": 10.0, "fit_bottom": 6.0}
    style.convert_old_fit(entries)
    assert entries["fit_left"] == pytest.approx(0.1 / 1.1, abs=1e-4)
    assert entries["fit_bottom"] == pytest.approx(0.06 / 1.12, abs=1e-4)


def _shown(window):
    from PySide6.QtTest import QTest
    window.show()
    QTest.qWaitForWindowExposed(window)
    plot = window.plot
    plot._page_handles_shown = True
    plot.grab()
    return plot


def test_a_margin_arrow_dragged_is_one_undo_step(window):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    plot = _shown(window)
    doc = window.doc
    assert plot.margin_share("left") == pytest.approx(0.0, abs=1e-6)
    start = plot.margin_gizmo("left").boundingRect().center().toPoint()
    QTest.mousePress(plot, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(plot, start + QPoint(80, 0))
    drag = plot._margin_state()["drag"]
    assert drag is not None and drag["share"] > 0.1
    QTest.mouseRelease(plot, Qt.LeftButton, Qt.NoModifier,
                       start + QPoint(80, 0))
    share = doc.style.fit_left
    assert share == pytest.approx(drag["share"], abs=1e-3)
    # the data now begins that share of the axis in
    assert plot.margin_share("left") == pytest.approx(share, abs=1e-3)
    assert window.undo.undo_label() == "fit margin"
    window.undo_step()
    assert doc.style.fit_left is None
    assert plot.margin_share("left") == pytest.approx(0.0, abs=1e-6)


def test_a_typed_margin_and_a_refused_one(window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    plot = _shown(window)
    doc = window.doc
    where = plot.margin_gizmo("right").boundingRect().center().toPoint()
    QTest.mouseClick(plot, Qt.LeftButton, Qt.NoModifier, where)
    assert plot.margin_selected() == "right"
    QTest.keyClicks(plot, "0.3")
    QTest.keyClick(plot, Qt.Key_Return)
    assert doc.style.fit_right == pytest.approx(0.3)
    assert plot.margin_share("right") == pytest.approx(0.3, abs=1e-3)
    # a left margin that leaves the data no room beside it: refused, red
    plot.select_margin("left")
    assert plot.type_margin("0.7") is False
    assert doc.style.fit_left is None
    assert plot._margin_state()["flash"] is not None
    assert plot.type_margin("-0.1") is False
    assert plot.type_margin("0.5") is True
    assert doc.style.fit_left == pytest.approx(0.5)


def test_ctrl_z_never_becomes_the_zoom_modes(window):
    """Christian, 2026-09-29: Ctrl+Z "just goes to zoom"."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    plot = window.plot
    event = QKeyEvent(QEvent.KeyPress, Qt.Key_Z, Qt.ControlModifier, "\x1a")
    plot.keyPressEvent(event)
    assert plot.mode() is None


# -------------------------------------------------------------------- DTG
def test_dtg_of_a_known_loss():
    t = np.linspace(0.0, 30.0, 3001)
    T = 30.0 + 10.0 * t
    m = 100.0 - 20.0 / (1.0 + np.exp(-(T - 200.0) / 8.0))
    d = dtg.dtg(t, T, m)
    peak = int(np.nanargmax(d))
    assert T[peak] == pytest.approx(200.0, abs=0.5)
    # a loss is positive, and the area is the loss
    assert d[peak] == pytest.approx(20.0 / 32.0, rel=0.02)
    assert np.nansum(d[1:] * np.diff(T)) == pytest.approx(20.0, rel=1e-3)
    per_minute = dtg.dtg(t, T, m, dtg.PER_MINUTE)
    assert np.nanmax(per_minute) == pytest.approx(10.0 * d[peak], rel=1e-3)
    assert dtg.missing(t, np.full_like(t, 100.0), m) is not None
    assert dtg.missing(t, np.full_like(t, 100.0), m, dtg.PER_MINUTE) is None


def test_a_dtg_is_a_scan_on_the_y_axis(qapp):
    win = _window(qapp, model.Sample("C:/nowhere/SDT-1.tri", sdt_data()))
    doc = win.doc
    assert [s.signal for s in doc.scans] == [model.SIGNAL_MASS]
    win.toggle_signal(model.SIGNAL_DTG)
    made = [s for s in doc.scans if s.is_dtg]
    assert made and made[0].visible
    assert doc.y_signal() == model.SIGNAL_DTG
    assert doc.axes["y"].caption(doc) == "DTG  /  " + dtg.PER_DEGREE
    assert made[0].analysis_objects == []
    assert doc.scans_missing() == []
    # the heat flow beside it has no axis, and says so
    win.toggle_signal(model.SIGNAL_HEAT)
    missing = dict(doc.scans_missing())
    heat = [s for s in doc.scans if s.is_heat][0]
    assert "axis" in missing[heat]
    # %/min converts the offset by the heating rate
    made[0].offset = 0.5
    rate = made[0].heating_rate()
    win.set_dtg_unit(dtg.PER_MINUTE)
    assert made[0].offset == pytest.approx(0.5 * abs(rate))



def test_a_dtg_survives_a_session(qapp, tmp_path):
    win = _window(qapp, model.Sample("C:/nowhere/SDT-1.tri", sdt_data()))
    win.toggle_signal(model.SIGNAL_DTG)
    scan = [s for s in win.doc.scans if s.is_dtg][0]
    scan.dtg_window = 5.0
    win.doc.dtg_unit = dtg.PER_MINUTE
    state = session.to_state(win.doc)
    entry = [e for e in state["scans"] if e["signal"] == model.SIGNAL_DTG]
    assert entry and entry[0]["dtg_window"] == 5.0
    assert state["dtg_unit"] == dtg.PER_MINUTE



def test_the_dtg_of_a_real_sdt_run(qapp):
    from dscpanel.core import loader
    sample = loader.read_sample(_path(CN81_TRI))
    win = _window(qapp, sample)
    win.toggle_signal(model.SIGNAL_DTG)
    scan = [s for s in win.doc.scans if s.is_dtg][0]
    assert scan.heating_rate() == pytest.approx(10.0, abs=0.2)
    values = scan.dtg_values()
    assert np.isfinite(values).sum() > 0.9 * len(values)
    # the whole loss, from the curve's own ends, is the area under it
    percent = scan.weight_values()
    temp = scan.temperature()
    ok = np.isfinite(values) & np.isfinite(temp)
    area = np.nansum(values[ok][1:] * np.diff(temp[ok]))
    finite = percent[np.isfinite(percent)]
    assert area == pytest.approx(finite[0] - finite[-1], rel=0.05)



# ------------------------------------------------------------ closing
def test_a_file_with_no_curve_can_be_closed(window):
    """CN-58 in Christian's figure: a file with no curve on it could not be
    taken off (2026-09-29)."""
    doc = window.doc
    sample = doc.samples[0]
    for scan in list(sample.scans):
        window.remove_scans([scan])
    assert sample in doc.samples and not sample.scans
    menu = window.context_menu_for(sample)
    words = [a.text() for a in menu.actions()]
    assert "Close {}\tDel".format(sample.name) in words
    window.close_sample(sample)
    assert sample not in doc.samples
    window.undo_step()
    assert sample in doc.samples


def test_closing_a_file_takes_its_curves_and_labels_and_undoes(window):
    doc = window.doc
    sample = doc.samples[0]
    scans = list(sample.scans)
    label = window.plot.doc.labels.append(
        model.TextLabel(999, "owned", scan=scans[0])) or doc.labels[-1]
    window.close_sample(sample)
    assert not any(s in doc.scans for s in scans)
    assert label not in doc.labels and sample not in doc.samples
    window.undo_step()
    assert all(s in doc.scans for s in scans)
    assert label in doc.labels and sample in doc.samples


# ----------------------------------------------------- range and lock
def test_an_axis_takes_its_range_in_its_settings(window):
    from dscpanel.ui.dialogs import AxisSettings
    doc, plot = window.doc, window.plot
    axis = doc.axes["x"]
    dialog = AxisSettings(window, axis, doc)
    fit = plot.view_x()
    assert dialog.low.value() == pytest.approx(fit[0], abs=1e-3)
    dialog.low.setValue(60.0)
    dialog.high.setValue(120.0)
    assert plot.view_x() == pytest.approx((60.0, 120.0))
    assert not dialog.locked.isChecked()
    # F goes back to the fit ...
    plot.reset_view()
    assert plot.view_x() == pytest.approx(fit)
    # ... unless the axis is locked
    window.set_axis_range(axis, 70.0, 110.0)
    dialog._show_range()
    dialog.locked.setChecked(True)
    assert axis.lock == pytest.approx([70.0, 110.0])
    window.plot.set_axis_view("x", 0.0, 50.0)
    plot.reset_view()
    assert plot.view_x() == pytest.approx((70.0, 110.0))
    window.undo_step()                 # the F
    window.undo_step()                 # the zoom
    window.undo_step()                 # the lock
    assert axis.lock is None


def test_lock_the_current_framing(window):
    doc, plot = window.doc, window.plot
    plot.set_axis_view("x", 60.0, 120.0)
    plot.set_axis_view("y", -2.0, 2.0)
    assert window.run_op("view.lock_framing")
    plot.fit()
    assert plot.view_x() == pytest.approx((60.0, 120.0))
    assert plot.view_y() == pytest.approx((-2.0, 2.0))
    assert plot.at_home_x() and plot.at_home_y()
    # a lock in W/g is not used on an mW axis
    window.set_unit(units.UNIT_MW)
    assert plot.lock_of("y") is None
    window.set_unit(units.UNIT_W_G)
    assert plot.lock_of("y") == pytest.approx((-2.0, 2.0))
    assert window.run_op("view.unlock_framing")
    plot.fit()
    assert plot.view_x() != pytest.approx((60.0, 120.0))
    # saved with the figure
    window.run_op("view.lock_framing")
    state = session.to_state(doc)
    assert state["axes"]["x"]["lock"] == pytest.approx(list(plot.view_x()))


# ------------------------------------------- decorators follow the zoom
def test_decorators_move_with_the_data_when_zoomed(window):
    from PySide6.QtCore import QPointF
    plot, doc = window.plot, window.doc
    label = window.add_label("free", at=QPointF(300.0, 200.0))
    plot.grab()
    rect = plot.plot_rect()
    home_point = plot.artist_point(label, rect)
    arrow_home = plot.artist_point(doc.arrow, rect)
    assert not plot.zoomed()
    # the data under the label, before the zoom
    x_data = plot.px_to_x(home_point[0], rect)
    y_data = plot.px_to_y(home_point[1], rect)
    lo, hi = plot.view_x()
    plot.set_axis_view("x", lo, lo + (hi - lo) / 2.0)
    assert plot.zoomed()
    moved = plot.artist_point(label, rect)
    assert moved[0] == pytest.approx(plot.x_to_px(x_data, rect), abs=0.5)
    assert moved[1] == pytest.approx(plot.y_to_px(y_data, rect), abs=0.5)
    assert plot.artist_point(doc.arrow, rect) != pytest.approx(arrow_home)
    # a drag while zoomed is stored in the home frame
    plot.set_artist_point(label, moved[0] + 10.0, moved[1], rect)
    plot.reset_view()
    assert not plot.zoomed()
    back = plot.artist_point(label, rect)
    assert back[0] == pytest.approx(home_point[0] + 5.0, abs=0.5)
    assert back[1] == pytest.approx(home_point[1], abs=0.5)
    plot.grab()


def test_a_label_on_a_curve_hangs_from_it(window):
    from PySide6.QtCore import QPointF
    plot, doc = window.plot, window.doc
    plot.grab()
    trace = plot.traces[0]
    i = len(trace.px) // 2
    point = QPointF(float(trace.px[i]), float(trace.py[i]) - 30.0)
    label = window.add_label("name", at=point, scan=trace.scan)
    assert label.attached
    rect = plot.plot_rect()
    placed = plot.artist_point(label, rect)
    assert placed[0] == pytest.approx(point.x(), abs=0.5)
    assert placed[1] == pytest.approx(point.y(), abs=0.5)
    # zoomed, it stays beside its curve: the same distance in pixels
    lo, hi = plot.view_x()
    plot.set_axis_view("x", lo + (hi - lo) / 4.0, hi - (hi - lo) / 4.0)
    plot.rebuild()
    hung = plot.attach_point(label, rect)
    now = plot.artist_point(label, rect)
    assert (now[0] - hung.x(), now[1] - hung.y()) == pytest.approx(
        (label.dx, label.dy))


def test_an_older_session_keeps_its_decorators_where_they_were(
        window, tmp_path, sample):
    import json
    plot, doc = window.plot, window.doc
    label = window.add_label("free", at=None)
    lo, hi = plot.view_x()
    plot.set_axis_view("x", lo, hi + (hi - lo))       # framed wider
    plot.grab()
    rect = plot.plot_rect()
    drawn_frac = ((plot.artist_point(label, rect)[0] - rect.left())
                  / rect.width())
    path = tmp_path / "old.dscpanel"
    session.save(doc, str(path))
    state = json.loads(path.read_text(encoding="utf-8"))
    state["version"] = 6
    # a version-6 file stored the fraction of the view as shown
    state["labels"][0]["x"] = drawn_frac
    path.write_text(json.dumps(state), encoding="utf-8")
    window.open_session(str(path))
    new = window.plot
    new.grab()
    rect = new.plot_rect()
    again = window.doc.labels[0]
    assert new.artist_point(again, rect)[0] == pytest.approx(
        rect.left() + drawn_frac * rect.width(), abs=0.5)
    assert not window.is_modified()


def test_f_resets_every_axis_at_once(window):
    """DSC's F is one press (`profile.FIT_STAGED`, Christian 2026-09-29)."""
    from dscpanel.core import profile
    plot = window.plot
    assert profile.FIT_STAGED is False
    fit_x, fit_y = plot.view_x(), plot.view_y()
    plot.set_axis_view("x", fit_x[0] + 5.0, fit_x[1] - 5.0)
    plot.set_axis_view("y", fit_y[0] / 2.0, fit_y[1] / 2.0)
    assert plot.reset_view()
    assert plot.view_x() == pytest.approx(fit_x)
    assert plot.view_y() == pytest.approx(fit_y)
    assert plot.at_home_x() and plot.at_home_y()
    assert not plot.reset_view()                # nothing left to do
    window.undo_step()                          # one step back
    assert plot.view_y() == pytest.approx((fit_y[0] / 2.0, fit_y[1] / 2.0))


def test_delete_in_the_outliner_closes_a_file(window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    doc = window.doc
    sample = doc.samples[0]
    window.show()
    QTest.qWaitForWindowExposed(window)
    outliner = window.outliner
    row = [item for item in outliner._items()
           if outliner._object(item) is sample][0]
    outliner.setCurrentItem(row)
    row.setSelected(True)
    outliner.setFocus()
    QTest.qWait(10)
    assert window.files_to_close() == [sample]
    QTest.keyClick(outliner, Qt.Key_Delete)
    QTest.qWait(10)
    assert sample not in doc.samples
    window.undo_step()
    assert sample in doc.samples
    # with the plot in hand, Delete removes curves as before
    window.plot.setFocus()
    assert window.files_to_close() == []


# ----------------------------------------------- the outliner's order
def _two_files(qapp):
    from dscpanel.ui.window import MainWindow
    win = MainWindow()
    win.resize(900, 560)
    for k in range(3):
        win._sample_loaded(model.Sample("C:/nowhere/F{}.tri".format(k),
                                        make_data()))
    win.undo.clear()
    return win


def test_a_file_box_shows_and_hides_its_curves(window):
    from PySide6.QtCore import Qt
    doc, tree = window.doc, window.outliner
    sample = doc.samples[0]
    window.refresh()
    row = [i for i in tree._items() if tree._object(i) is sample][0]
    assert row.flags() & Qt.ItemIsUserCheckable
    assert row.checkState(0) == Qt.Checked
    window.show_sample(sample, False)
    assert not any(s.visible for s in sample.scans)
    row = [i for i in tree._items() if tree._object(i) is sample][0]
    assert row.checkState(0) == Qt.Unchecked
    window.undo_step()
    assert all(s.visible for s in sample.scans)
    # some shown: half ticked
    sample.scans[0].visible = False
    window.refresh()
    row = [i for i in tree._items() if tree._object(i) is sample][0]
    assert row.checkState(0) == Qt.PartiallyChecked
    # a file with no curve has no box at all
    for scan in list(sample.scans):
        window.remove_scans([scan])
    row = [i for i in tree._items() if tree._object(i) is sample][0]
    assert not row.flags() & Qt.ItemIsUserCheckable


def test_a_file_is_renamed_and_its_curves_follow(window, tmp_path):
    doc = window.doc
    sample = doc.samples[0]
    old = sample.scans[0].display_name()
    window.rename_sample(sample, "Hbc (pure)")
    assert sample.name == "Hbc (pure)"
    assert sample.scans[0].display_name().startswith("Hbc (pure)")
    state = session.to_state(doc)
    assert state["samples"][0]["title"] == "Hbc (pure)"
    window.undo_step()
    assert sample.scans[0].display_name() == old
    menu = window.context_menu_for(sample)
    assert "Rename\tF2" in [a.text() for a in menu.actions()]


def test_files_are_dragged_into_order_and_s_follows(qapp):
    win = _two_files(qapp)
    doc, plot = win.doc, win.plot
    a, b, c = doc.samples
    assert win.move_samples([c], 0)
    assert doc.samples == [c, a, b]
    assert [s.sample for s in doc.scans] == [c, a, b]     # legend too
    # S, all laid on 0: the outliner's top at the top of the stack
    scans = list(doc.scans)
    doc.select_only(scans)
    plot.grab()
    assert plot.start_spread(scans)
    offsets = [s.offset for s in scans]
    assert offsets == sorted(offsets, reverse=True)
    assert scans[-1].offset == 0.0                # the lowest stays put
    # R turns the order over, the line where it was
    assert plot.flip_spread()
    offsets = [s.offset for s in scans]
    assert offsets == sorted(offsets)
    assert scans[0].offset == 0.0
    plot._finish_transform(cancel=True)
    assert all(s.offset == 0.0 for s in scans)      # Esc puts all back
    win.undo_step()
    assert doc.samples == [a, b, c]


def test_the_gap_a_file_is_dropped_into(qapp):
    win = _two_files(qapp)
    win.show()
    tree = win.outliner
    win.refresh()
    rows = tree._sample_rows()
    top = tree.visualItemRect(rows[0]).top()
    assert tree.gap_at(top + 1) == 0
    assert tree.gap_at(tree.visualItemRect(rows[1]).top() + 1) == 1
    assert tree.gap_at(tree._blocks_end(rows) - 1) == 3
    assert tree.gap_y(0) == top


def test_two_selected_scans_swap_places(qapp):
    win = _two_files(qapp)
    doc = win.doc
    x, y = doc.scans[0], doc.scans[2]
    x.offset, y.offset = 0.0, 2.0
    doc.select_only([x, y])
    assert win.ops.get("arrange.swap").enabled(win)
    menu = win.context_menu_for(x)
    assert any("Swap" in a.text() for a in menu.actions())
    assert win.run_op("arrange.swap")
    assert (x.offset, y.offset) == (2.0, 0.0)
    # of two files, the files swap places in the outliner too
    assert doc.samples.index(y.sample) < doc.samples.index(x.sample)
    win.undo_step()
    assert (x.offset, y.offset) == (0.0, 2.0)
    assert doc.samples.index(x.sample) < doc.samples.index(y.sample)
    doc.select_only([x])
    assert not win.ops.get("arrange.swap").enabled(win)


def test_f2_renames_a_file_in_place(window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    doc, tree = window.doc, window.outliner
    sample = doc.samples[0]
    window.show()
    QTest.qWaitForWindowExposed(window)
    window.refresh()
    row = [i for i in tree._items() if tree._object(i) is sample][0]
    window.activateWindow()
    tree.setFocus()
    tree.setCurrentItem(row)
    QTest.keyClick(tree.viewport(), Qt.Key_F2)
    editor = None
    for _ in range(100):                    # a busy machine is slow
        editor = QApplication.focusWidget()
        if editor is not None and editor is not tree and                 tree.isAncestorOf(editor):
            break
        QTest.qWait(10)
    assert editor is not None and tree.isAncestorOf(editor)
    editor.selectAll()
    QTest.keyClicks(editor, "renamed")
    QTest.keyClick(editor, Qt.Key_Return)
    for _ in range(100):                    # the rename is deferred
        if sample.name == "renamed":
            break
        QTest.qWait(10)
    assert sample.name == "renamed"
    # emptied, it goes back to the file's own name
    window.rename_sample(sample, "")
    assert sample.title is None and sample.name == sample.file_name


def test_s_keeps_the_order_the_offsets_have(qapp):
    """"If you just prearrange the scans a little bit" (2026-09-29): the
    offsets decide the order, the outliner only breaks ties, and the
    lowest scan is the neutral line."""
    win = _two_files(qapp)
    doc, plot = win.doc, win.plot
    a, b, c = doc.scans
    a.offset, b.offset, c.offset = 0.5, 0.2, 0.9       # c, a, b from the top
    win.refresh()
    plot.grab()
    doc.select_only([a, b, c])
    assert plot.start_spread([a, b, c])
    assert plot._scale["scans"] == [c, a, b]
    assert b.offset == pytest.approx(0.2)            # the lowest stays
    step = plot._scale["step"]
    assert a.offset == pytest.approx(0.2 + step)
    assert c.offset == pytest.approx(0.2 + 2 * step)
    plot._finish_transform()
    # "Stack evenly" keeps the same order
    a.offset, b.offset, c.offset = 0.5, 0.2, 0.9
    win.refresh()
    doc.select_only([a, b, c])
    win.stack_selected()
    assert c.offset > a.offset > b.offset


# ----------------------------------------------------- copy and paste
def test_labels_are_copied_and_pasted_as_free_ones(window):
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication
    doc, plot = window.doc, window.plot
    plot.grab()
    trace = plot.traces[0]
    i = len(trace.px) // 2
    note = window.add_note("melt", at=QPointF(float(trace.px[i]),
                                              float(trace.py[i])))
    plain = window.add_label("second", at=QPointF(200.0, 150.0))
    plain.bold = True
    assert note.attached
    doc.select_only([note, plain])
    assert window.run_op("edit.copy")
    assert QApplication.clipboard().text() == "melt\nsecond"
    rect = plot.plot_rect()
    before = (plot.artist_point(note, rect), plot.artist_point(plain, rect))
    tip_before = plot.leader_tip(note, rect)
    plot._cursor = None
    made = window.paste()
    assert len(made) == 2
    copy_note, copy_plain = made
    assert all(label.scan is None for label in made)      # free
    assert copy_note.leader and not copy_plain.leader
    assert copy_plain.bold and copy_plain.text == "second"
    # the same arrangement, a little down and right of the originals
    moved = (plot.artist_point(copy_note, rect)[0] - before[0][0],
             plot.artist_point(copy_note, rect)[1] - before[0][1])
    assert moved == pytest.approx((14.0, 14.0), abs=1.0)
    tip = plot.leader_tip(copy_note, rect)
    assert (tip.x() - tip_before.x(), tip.y() - tip_before.y()) == \
        pytest.approx((14.0, 14.0), abs=1.0)
    assert set(doc.selected()) == set(made)
    window.undo_step()
    assert not any(label in doc.labels for label in made)
    # plain text on the clipboard still pastes as a label
    QApplication.clipboard().setText("just words")
    label = window.paste()
    assert label.text == "just words"


def test_an_integration_can_give_its_peak_temperature(window, tmp_path):
    from dscpanel.core import labels, measure
    from dscpanel.ui.dialogs import AnalysisSettings
    doc = window.doc
    scan = doc.scans[0]
    analysis = measure.run("Peak Integration (enthalpy)", scan, 80.0, 140.0)
    scan.analysis_objects.append(analysis)
    plain = labels.render(analysis, doc).text
    assert "T*_{p}" not in plain                     # off built in
    dialog = AnalysisSettings(window, analysis)
    dialog.peak.combo.setCurrentIndex(
        dialog.peak.combo.findData(style.PEAK_ON))
    assert analysis.show_peak == style.PEAK_ON
    shown = labels.render(analysis, doc)
    peak = model.number(analysis.fields["Peak temperature"])
    assert shown.text.startswith(plain + ", *T*_{p} = ")
    assert shown.text.endswith("{:.0f} °C".format(peak))
    assert shown.problems == []
    # in K on a K axis, and anywhere a label says {Tp}
    doc.x_unit = units.TEMP_K
    analysis.label = "{} at {Tp}"
    text = labels.render(analysis, doc).text
    assert text.endswith("{:.0f} K".format(peak + 273.15))
    assert labels.render(analysis, doc).problems == []
    # the house style's default for every integration
    analysis.show_peak = None
    analysis.label = None
    doc.style.analysis_peak = style.PEAK_ON
    assert "T*_{p}" in labels.render(analysis, doc).text
    # saved with the session
    analysis.show_peak = style.PEAK_OFF
    state = session.to_state(doc)
    saved = [a for s in state["scans"] for a in s["analyses"]
             if a.get("source") == "panel"]
    assert saved and saved[0]["show_peak"] == style.PEAK_OFF
