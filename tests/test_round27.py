"""Margin gizmos, the colour picker, sums in number boxes, the crosshair's
colour, opaque shading, colour gradients, DTG, page margins, mirroring,
labels hanging from hidden curves.
"""

import numpy as np
import pytest

from dscpanel.core import dtg, model, numbers, session, shades, style, units

from conftest import make_data
from test_weight import _path, _window, sdt_data, SDT_REFERENCE


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
    """Boombox on a white page drew the light theme's amber reticle."""
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
    """Ctrl+Z went to the zoom modes."""
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
    sample = loader.read_sample(_path(SDT_REFERENCE))
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
    """A file with no curve on it could not be taken off the figure."""
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
    doc.follow_zoom = True                     # the F3 toggle's way
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
    doc.follow_zoom = True
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
    """DSC's F is one press (`profile.FIT_STAGED`)."""
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
    window.rename_sample(sample, "Reference (pure)")
    assert sample.name == "Reference (pure)"
    assert sample.scans[0].display_name().startswith("Reference (pure)")
    state = session.to_state(doc)
    assert state["samples"][0]["title"] == "Reference (pure)"
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
    """Prearranging the scans a little chooses the order: the offsets decide
    it, the outliner only breaks ties, and the lowest scan is the neutral
    line."""
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
    assert shown.text.endswith("{:.0f} \u00b0C".format(peak))
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


# ------------------------------------------------ molar masses (27d)
def test_the_molar_mass_calculator_reads_three_ways():
    from dscpanel.core import molar
    if not molar.available():
        pytest.skip("RDKit is not installed")
    # values an independent calculation prints
    for text, formula, mass in (
            ("(Hbc)1.00+Zn(im)1.70(bim)0.30", "C14.2H12.6N4O2Zn", 336.67),
            ("(Hbc)0.75+Zn(im)1.70(bim)0.30", "C12.45H11.1N4O1.5Zn", 306.14),
            ("Hbc", "C7H6O2", 122.12),
            ("Zn(im)2", "C6H6N4Zn", 199.53)):
        found = molar.calculate(text)
        assert found.read == molar.COMPOSITION, text
        assert (found.formula, round(found.mass, 2)) == (formula, mass), text
    for text, read, formula in (
            ("C6H6", molar.FORMULA, "C6H6"),
            ("CH3COOH", molar.FORMULA, "C2H4O2"),
            ("Zn(C3H3N2)2", molar.FORMULA, "C6H6N4Zn"),
            ("C14.2H12.6N4O2Zn", molar.FORMULA, "C14.2H12.6N4O2Zn"),
            ("CuSO4*5H2O", molar.FORMULA, "CuH10O9S"),
            ("O=C(O)c1ccccc1", molar.SMILES, "C7H6O2"),
            ("CCO", molar.SMILES, "C2H6O"),
            ("CO", molar.FORMULA, "CO")):
        found = molar.calculate(text)
        assert (found.read, found.formula) == (read, formula), text
    assert molar.calculate("CO", molar.SMILES).formula == "CH4O"
    assert not molar.calculate("xyz").ok
    assert not molar.calculate("C6H6", molar.SMILES).ok


def test_the_calculator_fills_the_molar_mass(window, monkeypatch):
    from dscpanel.core import molar
    from dscpanel.ui import dialogs
    if not molar.available():
        pytest.skip("RDKit is not installed")
    scan = window.doc.scans[0]
    settings = dialogs.ScanSettings(window, scan,
                                    window.doc.unit_for(scan))
    assert not hasattr(settings, "own_molar")         # one M per file

    def answered(calculator):
        calculator.entry.setText("C6H6")
        assert calculator.mass() == pytest.approx(78.114, abs=1e-3)
        return 1
    monkeypatch.setattr(dialogs.MolarMassDialog, "exec", answered)
    settings.calculate_molar()
    assert scan.sample.molar_mass == pytest.approx(78.114, abs=1e-3)
    assert scan.sample.composition == "C6H6"
    assert all(s.molar_mass == scan.sample.molar_mass
               for s in scan.sample.scans)


def test_an_old_scan_molar_mass_goes_to_its_file(window, tmp_path, sample):
    import json
    doc = window.doc
    path = tmp_path / "m.dscpanel"
    session.save(doc, str(path))
    state = json.loads(path.read_text(encoding="utf-8"))
    state["scans"][0]["molar_mass_override"] = 150.0
    path.write_text(json.dumps(state), encoding="utf-8")
    again, _problems = session.load(
        str(path), lambda _p: model.Sample(sample.path, sample.data))
    assert again.samples[0].molar_mass == 150.0
    assert all(s.molar_mass == 150.0 for s in again.scans)


# ------------------------------------------------------------- the rest
def test_every_axis_window_has_its_side(window):
    from dscpanel.ui.dialogs import CaptionSettings, NumberSettings
    doc = window.doc
    axis = doc.axes["y"]
    caption = CaptionSettings(window, axis, doc)
    assert caption.side.currentData() == "left"
    caption.side.setCurrentIndex(caption.side.findData("right"))
    assert axis.side == "right"
    assert window.plot.axis_side(axis) == "right"
    window.undo_step()
    assert axis.side == "left"
    numbers_window = NumberSettings(window, doc.axes["x"], doc)
    numbers_window.side.setCurrentIndex(
        numbers_window.side.findData("top"))
    assert doc.axes["x"].side == "top"


def test_a_label_on_a_curve_offers_its_parents_colour(window):
    from PySide6.QtCore import QPointF
    from dscpanel.ui.dialogs import LabelSettings
    scan = window.doc.scans[0]
    owned = window.add_label("owned", at=QPointF(300.0, 200.0), scan=scan)
    free = window.add_label("free", at=QPointF(300.0, 150.0))
    assert LabelSettings(window, owned).auto.text() == "Same as parent"
    assert LabelSettings(window, free).auto.text() == "Follow the theme"
    owned.colour = "auto"
    assert window.plot.label_colour(owned).name() == \
        window.plot.label_colour(owned).name()
    assert window.doc.labels_for(scan) == [owned]


def test_a_file_takes_another_source(window, monkeypatch):
    from dscpanel.core import loader
    doc = window.doc
    sample = doc.samples[0]
    first, second = doc.scans
    first.offset, second.offset = 0.4, 1.2
    first.colour = "#123456"
    sample.molar_mass = 99.0
    other = make_data(segments=1)
    monkeypatch.setattr(loader, "read_sample",
                        lambda path: model.Sample(path, other))
    old_path = sample.path
    problems = window.change_source(sample, "C:/nowhere/OTHER.tri")
    assert sample.path == "C:/nowhere/OTHER.tri"
    assert sample.name == "OTHER" and sample.molar_mass is None
    # the curve of segment 1 kept its place; segment 2 is not in the file
    assert first in doc.scans and first.offset == 0.4
    assert first.colour == "#123456"
    assert second not in doc.scans and problems
    window.undo_step()
    assert sample.path == old_path and sample.molar_mass == 99.0
    assert second in doc.scans and second.offset == 1.2
    menu = window.context_menu_for(sample)
    assert "Change the source file..." in [a.text() for a in menu.actions()]


# ------------------------------------------ the page's margins (27e)
def _exact(win):
    from dscpanel.core import figure as figure_module
    layout = win.doc.figure
    layout.mode = figure_module.MODE_SIZE
    layout.unit = "cm"
    layout.width, layout.height = 12.0, 9.0
    layout.margin_left, layout.margin_right = 4.0, 0.3
    layout.margin_top, layout.margin_bottom = 0.3, 1.5
    win.refresh()
    win.plot.fit_page()
    return layout


def test_room_grown_for_an_axis_is_given_back(qapp):
    """Room grown for an axis is given back: the heat flow's axis joining an
    SDT run's mass grows the right margin; hiding it again gives the room back
    - unless the margin was set by hand meanwhile."""
    win = _window(qapp, model.Sample("C:/nowhere/SDT-1.tri", sdt_data()))
    layout = _exact(win)
    win.toggle_signal(model.SIGNAL_HEAT)
    assert layout.margin_right > 0.3
    assert layout.grown["right"][0] == pytest.approx(0.3)
    win.toggle_signal(model.SIGNAL_HEAT)                 # hidden again
    assert layout.margin_right == pytest.approx(0.3)
    assert "right" not in layout.grown
    # grown, then set by hand: it stays when the axis goes
    win.toggle_signal(model.SIGNAL_HEAT)
    win.set_page_margin("right", 2.0)
    win.toggle_signal(model.SIGNAL_HEAT)
    assert layout.margin_right == pytest.approx(2.0)
    # the record travels in the session, and not in a preset
    win.toggle_signal(model.SIGNAL_HEAT)
    state = session.to_state(win.doc)
    assert state["figure_grown"] == {} or "right" in state["figure_grown"]
    assert "grown" not in layout.to_state()


def test_the_page_margins_tighten_to_what_they_hold(window):
    layout = _exact(window)
    plot = window.plot
    least = plot.least_page_margins()
    assert least[0] < 4.0                     # 4 cm is more than needed
    changes = window.tighten_page_margins()
    assert changes
    assert (layout.margin_left, layout.margin_right, layout.margin_top,
            layout.margin_bottom) == pytest.approx(least)
    assert plot.overflow() == []              # nothing is cut off
    assert layout.width < 12.0                # the white space is cut off
    window.undo_step()
    assert layout.margin_left == pytest.approx(4.0)
    # not for a figure that sizes its margins itself
    from dscpanel.core import figure as figure_module
    layout.mode = figure_module.MODE_ASPECT
    window.refresh()
    assert window.tighten_page_margins() == []
    assert not window.ops.get("figure.tighten_margins").enabled(window)


def test_the_page_margin_blades(window):
    """A blade stands at the page's corner, at its
    very edge; pulled in it cuts white space off, out it adds some - the
    page grows or shrinks and the axes box keeps its size."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    layout = _exact(window)
    window.show()
    QTest.qWaitForWindowExposed(window)
    plot = window.plot
    plot._page_handles_shown = True
    plot.grab()
    page = plot.page_on_pane()
    out = plot.BLADE_OUT
    # at the corners: right and top at the upper right, left and bottom at
    # the lower left, just outside the page
    right = plot.page_margin_blade("right").boundingRect().center()
    top = plot.page_margin_blade("top").boundingRect().center()
    left = plot.page_margin_blade("left").boundingRect().center()
    bottom = plot.page_margin_blade("bottom").boundingRect().center()
    assert (right.x(), right.y()) == (pytest.approx(page.right(), abs=1.0),
                                      pytest.approx(page.top() - out, abs=1.0))
    assert (top.x(), top.y()) == (pytest.approx(page.right() + out, abs=1.0),
                                  pytest.approx(page.top(), abs=1.0))
    assert (left.x(), left.y()) == (pytest.approx(page.left(), abs=1.0),
                                    pytest.approx(page.bottom() + out,
                                                  abs=1.0))
    assert (bottom.x(), bottom.y()) == (pytest.approx(page.left() - out,
                                                      abs=1.0),
                                        pytest.approx(page.bottom(), abs=1.0))
    axes = layout.axes_size()
    # pulled OUT, white space is added: the page grows, the box stays
    k = plot.page()[2]
    start = right.toPoint()
    QTest.mousePress(plot, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(plot, start + QPoint(int(40 * k), 0))
    QTest.mouseRelease(plot, Qt.LeftButton, Qt.NoModifier,
                       start + QPoint(int(40 * k), 0))
    assert layout.margin_right > 0.3 + 0.5
    assert layout.width > 12.0
    assert layout.axes_size() == pytest.approx(axes)
    window.undo_step()
    assert (layout.margin_right, layout.width) == pytest.approx((0.3, 12.0))
    # pulled IN, it is cut off - never into what the margin holds
    plot._page_handles_shown = True
    plot.grab()
    start = plot.page_margin_blade("left").boundingRect().center().toPoint()
    QTest.mousePress(plot, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(plot, start + QPoint(2000, 0))
    QTest.mouseRelease(plot, Qt.LeftButton, Qt.NoModifier,
                       start + QPoint(2000, 0))
    least = plot.least_page_margin("left")
    assert layout.margin_left == pytest.approx(least)
    assert layout.width == pytest.approx(12.0 - (4.0 - least), abs=1e-3)
    assert layout.axes_size() == pytest.approx(axes)
    window.undo_step()
    # clicked, a typed number; one that would cut something off is refused
    plot._page_handles_shown = True
    plot.grab()
    where = plot.page_margin_blade("left").boundingRect().center().toPoint()
    QTest.mouseClick(plot, Qt.LeftButton, Qt.NoModifier, where)
    assert plot.page_margin_selected() == "left"
    wanted = round(plot.least_page_margin("left") + 0.5, 2)
    QTest.keyClicks(plot, str(wanted))
    QTest.keyClick(plot, Qt.Key_Return)
    assert layout.margin_left == pytest.approx(wanted)
    assert plot.type_page_margin("0.1") is False
    assert layout.margin_left == pytest.approx(wanted)
    assert plot._page_margin_state()["flash"] is not None


def test_the_margins_in_numbers(window):
    """Double-clicked, a blade opens the page's margins and an arrow the
    data's."""
    from PySide6.QtWidgets import QDialogButtonBox
    layout = _exact(window)
    plot = window.plot
    asked = []
    window.ask_page_margins = lambda: asked.append("page")
    window.ask_data_margins = lambda: asked.append("data")
    plot.page_margins_asked.emit()
    plot.data_margins_asked.emit()
    assert asked == ["page", "data"]
    dialog = window.page_margins_dialog()
    least = plot.least_page_margins()
    assert dialog.boxes["left"].minimum() == pytest.approx(least[0])
    dialog.boxes["top"].setValue(1.0)
    dialog.tighten()
    assert dialog.values()["left"] == pytest.approx(least[0])
    axes = layout.axes_size()
    window.set_page_margins(dialog.values())
    assert layout.axes_size() == pytest.approx(axes)
    assert layout.margin_left == pytest.approx(least[0])
    data = window.data_margins_dialog()
    data.boxes["left"].setValue(0.6)
    data.boxes["right"].setValue(0.5)
    assert not data.buttons.button(QDialogButtonBox.Ok).isEnabled()
    data.boxes["right"].setValue(0.1)
    assert data.buttons.button(QDialogButtonBox.Ok).isEnabled()
    window.set_fit_margins(data.values())
    assert window.doc.style.fit_left == pytest.approx(0.6)
    assert plot.margin_share("left") == pytest.approx(0.6, abs=1e-3)


def test_blades_on_every_figure(window):
    """Blades on a figure whose margins size themselves too:
    taking one makes the figure exact, from the screen (test_family)."""
    plot = window.plot
    plot._page_handles_shown = True
    plot.grab()
    assert plot.page_margins_editable()
    assert plot.page_margin_blade_at(plot.page_on_pane().center()) is None


def test_a_hair_from_home_is_not_zoomed(window):
    plot = window.plot
    window.doc.follow_zoom = True
    lo, hi = plot.view_y()
    span = hi - lo
    plot.set_axis_view("y", lo + 0.005 * span, hi + 0.006 * span)
    assert not plot.zoomed()
    plot.set_axis_view("y", lo, lo + span / 2.0)
    assert plot.zoomed()



def test_decorators_stay_on_the_page_by_default(window):
    """Decorators stay on the page by default, so a heat flow arrow or a
    structure is not lost off the view; the F3 toggle makes them follow
    the zoom, nothing jumping either way."""
    from PySide6.QtCore import QPointF
    plot, doc = window.plot, window.doc
    assert doc.follow_zoom is False
    label = window.add_label("free", at=QPointF(300.0, 200.0))
    plot.grab()
    rect = plot.plot_rect()
    home = plot.artist_point(label, rect)
    arrow = plot.artist_point(doc.arrow, rect)
    lo, hi = plot.view_x()
    plot.set_axis_view("x", lo, lo + (hi - lo) / 2.0)
    assert plot.artist_point(label, rect) == pytest.approx(home)
    assert plot.artist_point(doc.arrow, rect) == pytest.approx(arrow)
    assert not plot.zoomed()                   # never cut at the axes
    # toggled while zoomed: nothing moves, and then it follows
    assert window.run_op("view.follow_zoom")
    assert doc.follow_zoom is True
    assert plot.artist_point(label, rect) == pytest.approx(home, abs=0.5)
    plot.reset_view()
    assert plot.artist_point(label, rect) != pytest.approx(home, abs=0.5)
    window.undo_step()                         # the F
    window.undo_step()                         # the toggle
    assert doc.follow_zoom is False
    # saved with the figure
    assert session.to_state(doc)["follow_zoom"] is False


def test_a_version_7_session_opens_with_its_decorators_in_place(
        window, tmp_path, monkeypatch):
    import json
    from dscpanel.core import loader
    plot, doc = window.plot, window.doc
    # the synthetic file exists nowhere: the session is handed it back
    data = doc.samples[0].data
    monkeypatch.setattr(loader, "read_sample",
                        lambda path: model.Sample(path, data))
    doc.follow_zoom = True
    label = window.add_label("free", at=None)
    lo, hi = plot.view_x()
    plot.set_axis_view("x", lo, hi + (hi - lo))
    plot.grab()
    rect = plot.plot_rect()
    drawn = plot.artist_point(label, rect)
    path = tmp_path / "seven.dscpanel"
    window.save_session(path=str(path))        # with its framing
    state = json.loads(path.read_text(encoding="utf-8"))
    state["version"] = 7
    del state["follow_zoom"]
    path.write_text(json.dumps(state), encoding="utf-8")
    window.open_session(str(path))
    new = window.plot
    new.grab()
    assert window.doc.follow_zoom is False
    again = window.doc.labels[0]
    assert new.artist_point(again, new.plot_rect()) == pytest.approx(
        drawn, abs=1.0)


# ------------------------------------------------------------ 27f
def test_tightened_margins_stop_at_the_last_drawn_pixel(window, tmp_path):
    """Tightening left extra margin where there were axis captions: after
    tightening, a PNG's ink reaches the page's edge on the sides with a
    caption."""
    from PySide6.QtGui import QColor, QImage
    layout = _exact(window)
    window.set_background("#ffffff")
    window.tighten_page_margins()
    path = str(tmp_path / "tight.png")
    window.export_image(path, light=True)
    image = QImage(path)

    def inked(x, y):
        c = QColor(image.pixel(x, y))
        return c.red() + c.green() + c.blue() < 600

    width, height = image.width(), image.height()
    cols = [x for x in range(0, width) if any(inked(x, y)
                                              for y in range(0, height, 3))]
    rows = [y for y in range(0, height) if any(inked(x, y)
                                               for x in range(0, width, 3))]
    per_mm = layout.dpi / 25.4
    # at most the 0.01 rounding and the antialiasing (it was 0.7 mm)
    assert cols[0] / per_mm < 0.3                    # the y caption
    assert (height - 1 - rows[-1]) / per_mm < 0.3    # the x caption
    assert window.plot.overflow() == []


def test_interval_marks_have_a_length_of_their_own(window):
    from dscpanel.core import measure
    from dscpanel.ui.dialogs import AnalysisSettings
    scan = window.doc.scans[0]
    analysis = measure.run("Peak Integration (enthalpy)", scan, 80.0, 140.0)
    window.refresh()
    plot = window.plot
    plot.grab()
    trace = [t for t in plot.traces if t.scan is scan][0]
    dashes, _lines = plot.interval_marks(trace, analysis)
    (a, b) = dashes[0]
    assert b.y() - a.y() == pytest.approx(2 * 3.0)      # built in: 3
    dialog = AnalysisSettings(window, analysis)
    assert dialog.interval_size.value() is None         # the house style's
    analysis.interval_size = 6.0
    dashes, _lines = plot.interval_marks(trace, analysis)
    (a, b) = dashes[0]
    assert b.y() - a.y() == pytest.approx(12.0)
    window.doc.style.interval_tick = 2.0
    analysis.interval_size = None
    dashes, _lines = plot.interval_marks(trace, analysis)
    assert dashes[0][1].y() - dashes[0][0].y() == pytest.approx(4.0)


def test_an_analysis_following_its_curve_is_one_solid_colour(window):
    from PySide6.QtGui import QColor
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    analysis = measure.run("Peak Integration (enthalpy)", scan, 80.0, 140.0)
    colour = window.plot.analysis_colour(analysis)
    assert colour.alpha() == 255
    # the shade 75 % of the curve's colour made over the page
    page = window.plot.page_colour()
    curve = QColor(scan.colour)
    share = 190 / 255.0
    assert colour.redF() == pytest.approx(
        share * curve.redF() + (1 - share) * page.redF(), abs=0.01)


def test_the_offset_readout_has_two_significant_figures(window):
    from PySide6.QtCore import QPointF
    plot, doc = window.plot, window.doc
    scan = doc.scans[0]
    scan.offset = 4.6543
    window.refresh()
    plot.grab()
    doc.select_only([scan])
    assert plot.start_grab([scan])
    plot._update_move(QPointF(plot._move["start"].x(),
                              plot._move["start"].y() - 17.0))
    text = plot._move_readout()
    moved = scan.offset - 4.6543
    assert numbers.write(moved, "%+.2g") in text
    plot._finish_move(cancel=True)


def test_set_the_molar_mass_offers_the_calculator(window, monkeypatch):
    from dscpanel.core import molar
    from dscpanel.ui import dialogs
    if not molar.available():
        pytest.skip("RDKit is not installed")
    scan = window.doc.scans[0]

    def answered(prompt):
        assert hasattr(prompt, "calculate_molar")        # the button
        prompt.molar.setValue(122.12)
        return 1
    monkeypatch.setattr(dialogs.MolarMassPrompt, "exec", answered)
    assert window.ask_molar_mass([scan]) == pytest.approx(122.12)
    assert scan.sample.molar_mass == pytest.approx(122.12)
    window.undo_step()
    assert scan.sample.molar_mass is None


def test_pictures_and_structures_mirror(window):
    from dscpanel.core import chem
    atoms = [{"el": "C", "x": 0.0, "y": 0.0}, {"el": "O", "x": 2.0,
                                                "y": 1.0}]
    bonds = [{"a": 0, "b": 1, "order": 1, "stereo": "wedge"}]
    new_atoms, new_bonds = chem.mirrored_layout(atoms, bonds, True)
    assert [a["x"] for a in new_atoms] == [2.0, 0.0]
    assert [a["y"] for a in new_atoms] == [0.0, 1.0]
    assert new_bonds[0]["stereo"] == "hash"      # the same molecule
    assert atoms[0]["x"] == 0.0                  # the originals untouched
    up_atoms, _b = chem.mirrored_layout(atoms, bonds, False)
    assert [a["y"] for a in up_atoms] == [1.0, 0.0]
    # a picture's mirror is two flags, saved
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage
    picture = QImage(4, 2, QImage.Format_ARGB32)
    picture.fill(0xff0000ff)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    picture.save(buffer, "PNG")
    image = model.ImageArtist(990, bytes(QByteArray(buffer.data()).toBase64()
                                         ).decode("ascii"), 0.5, 0.5, 40.0)
    window.doc.images.append(image)
    window.doc.select_only([image])
    assert window.ops.get("object.mirror_h").key == "Ctrl+Shift+H"
    assert window.ops.get("object.mirror_v").key == "Ctrl+Shift+V"
    assert window.ops.get("edit.paste_text").key == "Ctrl+Alt+V"
    assert window.run_op("object.mirror_h")
    assert image.mirror_h and not image.mirror_v
    window.plot.grab()
    saved = session.to_state(window.doc)["images"][0]
    assert saved["mirror_h"] is True
    window.undo_step()
    assert not image.mirror_h


def test_a_mirrored_ring_keeps_its_double_bonds_inside(window):
    """After a mirror the ring's double bonds were
    drawn outside it - their ring's stored centre had not moved."""
    from dscpanel.core import chem
    atoms = [{"el": "C", "x": 1.0, "y": 0.0}, {"el": "C", "x": 2.0,
                                                "y": 0.0}]
    bonds = [{"a": 0, "b": 1, "order": 2, "ring": [1.5, 1.0],
              "stereo": None}]
    new_atoms, new_bonds = chem.mirrored_layout(atoms, bonds, True)
    # mirrored about the atoms' middle, x = 1.5: the centre stays over them
    assert new_bonds[0]["ring"] == pytest.approx([1.5, 1.0])
    atoms = [{"el": "C", "x": 0.0, "y": 0.0}, {"el": "C", "x": 4.0,
                                                "y": 0.0}]
    bonds = [{"a": 0, "b": 1, "order": 2, "ring": [1.0, -1.0],
              "stereo": None}]
    _atoms, new_bonds = chem.mirrored_layout(atoms, bonds, True)
    assert new_bonds[0]["ring"] == pytest.approx([3.0, -1.0])
    _atoms, new_bonds = chem.mirrored_layout(atoms, bonds, False)
    assert new_bonds[0]["ring"] == pytest.approx([1.0, 1.0])


def test_a_turned_structures_box_holds_its_level_labels(window):
    """The OH's H stuck out of a turned structure's selection: level labels
    are laid out after the turn, and the box now takes them so. Checked on
    the pixels: every red (oxygen) pixel lies inside the turned box."""
    from PySide6.QtGui import QColor, QPolygonF
    from dscpanel.core import chem
    if not chem.available():
        pytest.skip("RDKit is not installed")
    window.show()
    molecule = window.add_molecule("O=C(O)c1ccccc1")
    molecule.bond_length = 40.0
    molecule.label_size = 18.0
    plot = window.plot
    for angle in (90.0, 270.0):
        molecule.rotation = angle
        window.refresh()
        image = plot.grab().toImage()
        rect = plot.plot_rect()
        box = plot._molecule_layout(molecule, rect)[0]
        turned = plot._turn_of(molecule, rect).map(QPolygonF(box))
        corners = [plot.to_widget(turned[k]) for k in range(turned.size())]
        ratio = image.devicePixelRatio()
        left = min(c.x() for c in corners) * ratio - 1
        right = max(c.x() for c in corners) * ratio + 1
        top = min(c.y() for c in corners) * ratio - 1
        bottom = max(c.y() for c in corners) * ratio + 1
        reds = []
        for y in range(0, image.height(), 1):
            for x in range(0, image.width(), 1):
                c = QColor(image.pixel(x, y))
                if c.red() > 200 and c.green() < 140 and c.blue() < 140:
                    reds.append((x, y))
        assert reds, "no oxygen drawn"
        assert all(left <= x <= right and top <= y <= bottom
                   for x, y in reds), angle


def test_mirroring_a_turned_structure_is_left_right_on_screen(window):
    from dscpanel.core import chem
    if not chem.available():
        pytest.skip("RDKit is not installed")
    molecule = window.add_molecule("O=C(O)c1ccccc1")
    molecule.rotation = 270.0
    window.doc.select_only([molecule])
    window.mirror_selected(True)
    assert molecule.rotation == pytest.approx(90.0)
    window.undo_step()
    assert molecule.rotation == pytest.approx(270.0)


def _hang_a_label(window):
    """A label hanging from the first curve, 30 units above it."""
    from PySide6.QtCore import QPointF
    plot = window.plot
    plot.grab()
    trace = plot.traces[0]
    i = len(trace.px) // 2
    point = QPointF(float(trace.px[i]), float(trace.py[i]) - 30.0)
    label = window.add_label("name", at=point, scan=trace.scan)
    plot.grab()
    return label, trace.scan


def _drag_from(plot, start, dx, dy):
    """Press at `start` (figure units), drag by (dx, dy) PANE pixels, let
    go - through the handlers, so an error fails the test."""
    from PySide6.QtCore import QPointF
    from test_window import _move, _press, _release
    at = plot.to_widget(QPointF(*start))
    plot.mousePressEvent(_press(plot, (at.x(), at.y())))
    for k in range(1, 5):
        plot.mouseMoveEvent(_move(plot, (at.x() + dx * k / 4.0,
                                         at.y() + dy * k / 4.0)))
    plot.mouseReleaseEvent(_release(plot, (at.x() + dx, at.y() + dy)))
    plot.grab()


def test_a_label_stays_where_it_hangs_when_its_curve_is_hidden(window):
    """Swapping first upscans for later ones: hiding a curve dropped its labels
    on the middle of the plot, and dragging one from there ended the program -
    a TypeError inside a mouse handler, which PySide6 turns into an access
    violation."""
    plot = window.plot
    label, scan = _hang_a_label(window)
    window.lock_framing(True)       # hiding a curve would refit the view
    plot.grab()
    rect = plot.plot_rect()
    before = plot.artist_point(label, rect)
    window.undo.set_props([(scan, "visible", False)], "hide")
    window.refresh()
    plot.grab()
    assert plot._trace_of(scan) is None
    assert plot.artist_point(label, rect) == pytest.approx(before, abs=0.5)
    _drag_from(plot, before, 20.0, 16.0)
    k = plot.page()[2]
    after = plot.artist_point(label, rect)
    assert label.attached
    assert after[0] - before[0] == pytest.approx(20.0 / k, abs=1.0)
    assert after[1] - before[1] == pytest.approx(16.0 / k, abs=1.0)
    # shown again, the curve has it where it was dragged to
    window.undo.set_props([(scan, "visible", True)], "show")
    window.refresh()
    plot.grab()
    assert plot.artist_point(label, rect) == pytest.approx(after, abs=0.5)


def test_a_label_with_no_point_on_its_curve_still_drags(window,
                                                        monkeypatch):
    """No curve in this unit at all: it stands at its own x and y, and a
    drag moves it from there instead of failing on the curve's index."""
    plot = window.plot
    label, _scan = _hang_a_label(window)
    monkeypatch.setattr(plot, "_label_trace", lambda scan: None)
    plot.invalidate()
    plot.grab()
    rect = plot.plot_rect()
    before = plot.artist_point(label, rect)
    _drag_from(plot, before, 24.0, -12.0)
    k = plot.page()[2]
    after = plot.artist_point(label, rect)
    assert after[0] - before[0] == pytest.approx(24.0 / k, abs=1.0)
    assert after[1] - before[1] == pytest.approx(-12.0 / k, abs=1.0)


def test_every_qt_handler_in_the_ui_is_guarded():
    """Each UI module ends with `log.guard_classes`: a method Qt calls by
    itself that raises must reach the log, not end the program."""
    import importlib
    import inspect
    import pkgutil
    from dscpanel import ui
    from dscpanel.core import log
    missed = []
    for info in pkgutil.iter_modules(ui.__path__):
        module = importlib.import_module("dscpanel.ui." + info.name)
        for cls in list(vars(module).values()):
            if not inspect.isclass(cls) or cls.__module__ != module.__name__:
                continue
            for name, attr in vars(cls).items():
                if ((name.endswith("Event") or name in log.HANDLERS)
                        and inspect.isfunction(attr)
                        and not getattr(attr, "guarded", False)):
                    missed.append("{}.{}.{}".format(info.name,
                                                    cls.__name__, name))
    assert not missed, missed


def test_an_error_in_a_handler_is_logged_and_survived(qapp, monkeypatch):
    """PySide6 6.11 ends the process on an error in a method Qt calls by
    itself, without asking `sys.excepthook`. Guarded, the program logs it
    and carries on; a test (no hook) still sees the error."""
    import sys
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication, QWidget
    from dscpanel.core import log

    class Faulty(QWidget):
        def mouseMoveEvent(self, ev):
            raise TypeError("a handler's error")

    assert log.guard_classes({"Faulty": Faulty}, Faulty.__module__) == 1
    with pytest.raises(TypeError):
        Faulty.mouseMoveEvent(None, None)
    heard = []
    monkeypatch.setattr(log, "on_error", heard.append)
    monkeypatch.setattr(sys, "excepthook", log._hook)
    monkeypatch.setattr(log, "_last_guarded", [None, 0.0])
    widget = Faulty()
    widget.show()
    point = QPointF(3.0, 3.0)
    for _ in range(3):
        QApplication.sendEvent(widget, QMouseEvent(
            QMouseEvent.Type.MouseMove, point, point, Qt.NoButton,
            Qt.LeftButton, Qt.NoModifier))
    widget.close()
    # reported once, not once per event
    assert heard == ["TypeError: a handler's error"]
