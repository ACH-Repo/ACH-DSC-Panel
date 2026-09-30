"""The unit of an analysis's number, settings windows that scroll on a
small screen, typed distances for moving decorators, notes that point
where they should and slide along their curve, and a SMILES pasted
without RDKit.
"""

import pytest

from PySide6.QtCore import QPointF

from dscpanel.core import labels, model, session


@pytest.fixture
def window(qapp, sample):
    from dscpanel.ui.window import MainWindow
    win = MainWindow()
    win.resize(900, 560)
    win._sample_loaded(sample)
    win.toggle_segment(sample, 1, True)
    win.undo.clear()
    return win


def _integration(window):
    from dscpanel.core import measure
    scan = window.doc.scans[0]
    analysis = measure.run("Peak Integration (enthalpy)", scan, 80.0, 140.0)
    assert analysis is not None
    return scan, analysis


# ------------------------------------------------ the unit of a number
def test_an_integration_can_be_shown_in_kj_per_mol(window):
    """"I do not see how J/mol or kJ/mol can be set": a Unit choice in the
    analysis's settings. Per mole needs the molar mass, and says so."""
    from dscpanel.ui.dialogs import AnalysisSettings
    scan, analysis = _integration(window)
    doc = window.doc
    per_gram = labels.render(analysis, doc).text
    dialog = AnalysisSettings(window, analysis)
    units_offered = [dialog.unit.itemData(k)
                     for k in range(dialog.unit.count())]
    assert units_offered[:3] == [None, "J/g", "kJ/mol"]
    dialog.unit.setCurrentIndex(dialog.unit.findData("kJ/mol"))
    assert analysis.unit == "kJ/mol"
    rendered = labels.render(analysis, doc)
    assert rendered.text.endswith("? kJ/mol")
    assert any("NO MOLAR MASS" in text for _kind, text in rendered.problems)
    scan.sample.molar_mass = 250.0
    value_j_g = labels.result(analysis)[0]
    shown = labels.render(analysis, doc).text
    assert shown.endswith(" kJ/mol")
    assert "{:.3g}".format(value_j_g * 250.0 / 1000.0).rstrip("0") in shown
    # a unit typed after {} still wins
    analysis.label = "\\Delta*H* = {} J/g"
    assert labels.render(analysis, doc).text == per_gram.replace(
        "?", "").strip() or "J/g" in labels.render(analysis, doc).text


def test_the_unit_survives_a_session(window, tmp_path):
    _scan, analysis = _integration(window)
    analysis.unit = "kJ/mol"
    path = window.save_session(path=str(tmp_path / "u.dscpanel"))
    sample = window.doc.samples[0]
    loaded, problems = session.load(path, lambda _p: sample)
    assert not problems
    (again,) = [a for s in loaded.scans for a in s.analysis_objects
                if a.source == "panel"]
    assert again.unit == "kJ/mol"


# ------------------------------------------- settings that scroll
def test_a_tall_settings_window_scrolls_its_rows(window, monkeypatch):
    """On a small laptop screen the rows scroll past a share of the
    screen's height; the buttons stay in view; small windows never do."""
    from dscpanel.ui import dialogs
    from PySide6.QtWidgets import QDialogButtonBox
    _scan, analysis = _integration(window)
    monkeypatch.setattr(dialogs, "screen_limit", lambda _w: 260)
    dialog = dialogs.AnalysisSettings(window, analysis)
    dialog.show()
    assert dialog._rows_area is not None
    assert dialog.height() <= 260
    buttons = dialog.findChildren(QDialogButtonBox)
    assert buttons and not dialog._rows_area.isAncestorOf(buttons[0])
    dialog.unit.setCurrentIndex(1)              # still live in the area
    assert analysis.unit == "J/g"
    dialog.close()
    monkeypatch.setattr(dialogs, "screen_limit", lambda _w: 5000)
    small = dialogs.AnalysisSettings(window, analysis)
    small.show()
    assert getattr(small, "_rows_area", None) is None
    small.close()


# ------------------------------------ typed distances for decorators
def test_a_typed_number_moves_a_decorator_in_axis_units(window):
    """G, then a number: an artist moves that far in the axes' units - x
    with X (the axis's temperature unit), else y (its y unit, up)."""
    plot, doc = window.plot, window.doc
    label = window.add_label(text="melt")
    plot.grab()
    rect = plot.plot_rect()
    before = plot.artist_point(label, rect)
    doc.select_only([label])
    assert plot.start_grab([label])
    plot._move["axis"] = "x"
    plot._move["typed"] = "20"
    plot._update_move(plot._move["start"])
    lo, hi = plot.view_x()
    moved = plot.artist_point(label, rect)
    assert moved[0] - before[0] == pytest.approx(20.0 / (hi - lo)
                                                 * rect.width(), abs=0.5)
    assert moved[1] == pytest.approx(before[1], abs=0.5)
    assert "°C" in plot._move_readout() or "C" in plot._move_readout()
    plot._move["axis"] = None
    plot._move["typed"] = "0.1"
    plot._update_move(plot._move["start"])
    lo, hi = plot.view_y()
    moved = plot.artist_point(label, rect)
    assert before[1] - moved[1] == pytest.approx(0.1 / (hi - lo)
                                                 * rect.height(), abs=0.5)
    plot._finish_move()
    window.undo.undo()
    assert plot.artist_point(label, rect) == pytest.approx(before, abs=0.5)


# ------------------------------------------------------------ notes
def _note_on_curve(window, fraction=0.4):
    plot = window.plot
    plot.grab()
    trace = plot.traces[0]
    i = int(len(trace.px) * fraction)
    on_curve = QPointF(float(trace.px[i]), float(trace.py[i]))
    note = window.add_note("melt", at=on_curve)
    plot.grab()
    return note, trace


def test_a_new_note_points_straight_down_at_its_point(window):
    note, _trace = _note_on_curve(window)
    plot = window.plot
    rect = plot.plot_rect()
    tip = plot.leader_tip(note, rect)
    box = plot.rotated_bounds(note, plot.artist_box(note, rect), rect)
    assert box.center().x() == pytest.approx(tip.x(), abs=1.0)
    assert box.bottom() < tip.y()               # above it
    start = plot.leader_start(note, box, tip)
    assert start.x() == pytest.approx(tip.x(), abs=1.0)


def test_ctrl_l_puts_a_notes_left_edge_over_its_point(window):
    note, _trace = _note_on_curve(window)
    plot, doc = window.plot, window.doc
    doc.select_only([note])
    assert window.ops.get("analysis.flush_left").enabled(window)
    window.set_flush("left")
    rect = plot.plot_rect()
    tip = plot.leader_tip(note, rect)
    box = plot.rotated_bounds(note, plot.artist_box(note, rect), rect)
    assert box.left() == pytest.approx(tip.x(), abs=1.0)
    # on its curve the flush alone places it; its arrow drops straight
    assert note.attached and note.flush == "left"
    window.undo.undo()
    assert note.leader_from == "auto" and note.flush is None


def test_a_notes_point_is_typed_in_its_settings(window):
    from dscpanel.ui.dialogs import LabelSettings
    note, _trace = _note_on_curve(window)
    dialog = LabelSettings(window, note)
    assert dialog.tip_x.isEnabled() and dialog.tip_x.text()
    dialog.tip_x.setText("120")
    dialog.tip_y.setText("0.05")
    dialog._typed_tip()
    assert note.leader[0] == pytest.approx(120.0)
    assert note.leader[1] + note.follow() == pytest.approx(0.05)
    dialog.tip_x.setText("hot")
    dialog._typed_tip()
    assert note.leader[0] == pytest.approx(120.0)      # refused, kept


def test_a_notes_arrow_has_its_own_start_and_colour(window, tmp_path):
    from dscpanel.ui.dialogs import LabelSettings
    note, _trace = _note_on_curve(window)
    plot = window.plot
    dialog = LabelSettings(window, note)
    dialog.leader_from.setCurrentIndex(dialog.leader_from.findData(
        "right"))
    assert note.leader_from == "right"
    dialog._set_leader_colour("#ff0000")
    assert note.leader_colour == "#ff0000"
    assert plot.leader_colour(note).name() != plot.label_colour(note).name()
    rect = plot.plot_rect()
    box = plot.rotated_bounds(note, plot.artist_box(note, rect), rect)
    start = plot.leader_start(note, box, plot.leader_tip(note, rect))
    assert start.x() == pytest.approx(box.right(), abs=0.5)
    path = window.save_session(path=str(tmp_path / "n.dscpanel"))
    loaded, _problems = session.load(path, lambda p: window.doc.samples[0])
    (again,) = loaded.labels
    assert (again.leader_from, again.leader_colour) == ("right", "#ff0000")
    plot.grab()


def test_g_then_x_slides_a_note_along_its_curve(window):
    """"You cannot grab it and move it along the DSC trace": G, X - the
    tip walks along the curve and the text goes with it; one undo step
    puts both back."""
    note, trace = _note_on_curve(window, 0.3)
    plot, doc = window.plot, window.doc
    rect = plot.plot_rect()
    tip_before = plot.leader_tip(note, rect)
    text_before = plot.artist_point(note, rect)
    leader_before = list(note.leader)
    at_before = tuple(note.at)
    doc.select_only([note])
    assert plot.start_grab([note])
    plot._move["axis"] = "x"
    start = plot._move["start"]
    plot._update_move(QPointF(start.x() + 80.0, start.y()))
    tip = plot.leader_tip(note, rect)
    assert tip.x() > tip_before.x() + 40.0
    # still ON the curve
    index = plot.sample_at(trace, tip, rect)
    on = plot._sample_point(trace, index, rect)
    assert (on.x(), on.y()) == (pytest.approx(tip.x(), abs=1.0),
                                pytest.approx(tip.y(), abs=1.0))
    text = plot.artist_point(note, rect)
    assert text[0] - text_before[0] == pytest.approx(
        tip.x() - tip_before.x(), abs=1.0)
    plot._finish_move()
    # on its curve the note slides by its sample
    assert note.attached and tuple(note.at) != at_before
    window.undo.undo()
    assert plot.leader_tip(note, rect).x() == pytest.approx(
        tip_before.x(), abs=0.5)
    assert note.leader == pytest.approx(leader_before)


# ----------------------------------------------- SMILES without RDKit
def test_a_smiles_is_recognised_without_rdkit():
    from dscpanel.core import chem
    for text in ("CCO", "O=C(O)CCCCC(O)=O", "c1ccccc1", "[Na+].[Cl-]",
                 "CO"):
        assert chem.plausible_smiles(text), text
    for text in ("Hello", "C", "C1CC", "OH", "Heat Flow", "99%", "ZIF-62",
                 "C(C", ""):
        assert not chem.plausible_smiles(text), text


def test_a_smiles_pasted_without_rdkit_says_so(window, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from dscpanel.core import chem
    monkeypatch.setattr(chem, "available", lambda: False)
    told = []
    window.missing_rdkit = lambda: told.append(True)
    QApplication.clipboard().setText("O=C(O)CCCCC(O)=O")
    labels_before = len(window.doc.labels)
    assert window.paste() is None
    assert told == [True]
    assert len(window.doc.labels) == labels_before
    # words are still a label, and Ctrl+Shift+V takes the SMILES as text
    QApplication.clipboard().setText("second heating")
    assert isinstance(window.paste(), model.TextLabel)
    QApplication.clipboard().setText("O=C(O)CCCCC(O)=O")
    assert isinstance(window.paste(as_text=True), model.TextLabel)
    assert told == [True]


# ------------------------------------------------------- a marker line
def test_a_marker_line_stands_at_a_temperature(window, tmp_path):
    """The template's `mark_peak`: a dashed vertical line across the axes
    at a temperature, its text upright on it; sideways moves the line, up
    and down slides the text; picked anywhere along the line."""
    plot, doc = window.plot, window.doc
    plot.grab()
    rect = plot.plot_rect()
    at = QPointF(plot.x_to_px(100.0, rect), rect.center().y())
    line = window.add_marker_line("*T*_{m}", at=at)
    assert line.vline == pytest.approx(100.0, abs=0.5)
    assert line.rotation == 90.0 and line.is_vline
    plot.grab()
    x = plot.vline_px(line, rect)
    assert x == pytest.approx(at.x(), abs=0.5)
    hit = plot.objects_at(QPointF(x + 2.0, rect.top() + 10.0))
    assert hit and hit[0] is line
    # sideways: the line; up and down: the text along it
    doc.select_only([line])
    assert plot.start_grab([line])
    start = plot._move["start"]
    plot._update_move(QPointF(start.x() + 40.0, start.y() + 30.0))
    plot._finish_move()
    assert line.vline > 100.0 + 1.0
    assert plot.artist_point(line, rect)[0] == pytest.approx(
        plot.vline_px(line, rect), abs=0.5)
    window.undo.undo()
    assert line.vline == pytest.approx(100.0, abs=0.5)
    # typed in its settings, in any unit
    from dscpanel.ui.dialogs import LabelSettings
    dialog = LabelSettings(window, line)
    dialog.line_at.setText("400 K")
    dialog._typed_line()
    assert line.vline == pytest.approx(126.85, abs=0.01)
    dialog.line_dashed.setChecked(False)
    assert not line.line_dashed
    sample = doc.samples[0]
    path = window.save_session(path=str(tmp_path / "v.dscpanel"))
    loaded, _problems = session.load(path, lambda _p: sample)
    (again,) = loaded.labels
    assert again.vline == pytest.approx(126.85, abs=0.01)
    assert not again.line_dashed
    # off the view it is not drawn, and not picked
    plot.set_view_x(150.0, 200.0)
    assert plot.vline_px(line) is None
    plot.grab()


# --------------------------------------------------- fit margins and more
def _sdt_window(qapp):
    from test_weight import _sample, _window, sdt_data
    return _window(qapp, _sample(sdt_data(segments=2)))


def test_a_new_axis_gets_room_on_an_exact_figure(qapp):
    """Adding an SDT run's heat flow puts its axis on the right; on an
    exact figure whose right margin was set for no axis there, that margin
    grows to fit it - in the same undo step as showing the curve."""
    from dscpanel.core import figure as figure_module
    win = _sdt_window(qapp)
    layout = win.doc.figure
    layout.mode = figure_module.MODE_SIZE
    layout.margin_right = 0.3
    win.refresh()
    win.plot.fit_page()
    win.undo.clear()
    win.toggle_signal(model.SIGNAL_HEAT)
    assert layout.margin_right > 0.3
    assert not [o for o in win.plot.overflow() if o[0] == "right"]
    win.undo.undo()
    assert layout.margin_right == pytest.approx(0.3)
    assert all(not s.visible for s in win.doc.scans if not s.is_mass)


def test_a_right_click_marks_every_selected_mass_curve(qapp):
    win = _sdt_window(qapp)
    sample = win.doc.samples[0]
    win.toggle_segment(sample, 1, True, model.SIGNAL_MASS)
    doc, plot = win.doc, win.plot
    first, second = doc.scans
    doc.select_only([first, second])
    plot.grab()
    trace = plot._trace_of(first)
    at = plot._sample_point(trace, trace.first + len(trace.x) // 2)
    made = win.mass_here(first, at)
    assert len(made) == 2
    assert {a.scan for a in made} == {first, second}
    t0, t1 = (float(a.fields["Cursor x"].split()[0]) for a in made)
    assert t0 == pytest.approx(t1, abs=2.0)


def test_the_fit_margins_are_the_templates_side_margins(window):
    """A margin is the SHARE OF THE AXIS left empty: left 0.1 is the
    first tenth of the x axis."""
    plot, doc = window.plot, window.doc
    doc.style.fit_left = doc.style.fit_right = 0.0
    lo, hi = plot.data_x()
    doc.style.fit_left = 0.1
    doc.style.fit_top = 0.2
    lo2, hi2 = plot.data_x()
    assert (lo - lo2) / (hi2 - lo2) == pytest.approx(0.1)
    assert hi2 == pytest.approx(hi)
    y_lo, y_hi = plot._curves_y()
    doc.style.fit_top = 0.05
    base_lo, base_hi = plot._curves_y()
    assert y_hi > base_hi
    # Two margins that would leave the data no room are scaled down.
    doc.style.fit_left = doc.style.fit_right = 0.9
    a, b = plot.fit_pads("left", "right")
    assert a + b == pytest.approx(0.95) and a == pytest.approx(b)
    from dscpanel.core import style
    keys = [s.key for s in style.SETTINGS]
    assert {"fit_left", "fit_right", "fit_bottom", "fit_top"} <= set(keys)


def test_nothing_rescales_the_plot_but_f(window):
    """"No matter what you do, the plot is automatically rescaled without
    even pressing F" - and a lengthened analysis arrow rescaled y. The fit
    is kept; F works it out again; a curve shown or hidden does too."""
    from dscpanel.core import measure
    plot, doc = window.plot, window.doc
    scan = doc.scans[0]
    analysis = measure.run("Peak Integration (enthalpy)", scan, 80.0, 140.0)
    window.refresh()
    plot.grab()
    before = plot.view_y()
    analysis.label_dy = -400.0                 # a very long arrow
    window.refresh()
    plot.grab()
    assert plot.view_y() == before
    window.undo.set_props([(scan, "offset", 5.0)], "move")
    plot.grab()
    assert plot.view_y() == before
    plot.reset_view()                           # F: x first
    plot.reset_view()                           # then y
    assert plot.view_y() != before
    fitted = plot.view_y()
    window.toggle_segment(doc.samples[0], 1, False)
    plot.grab()
    assert plot.view_y() != fitted              # the curves on it changed


def test_a_spread_of_mass_curves_is_about_their_own_level(qapp):
    """S on m% curves: the axis runs near 100 %, where a distance from
    y = 0 made the steps awkward; the neutral line is the level of the
    curve that stays put."""
    win = _sdt_window(qapp)
    sample = win.doc.samples[0]
    win.toggle_segment(sample, 1, True, model.SIGNAL_MASS)
    doc, plot = win.doc, win.plot
    first, second = doc.scans
    plot.grab()
    lo, hi = plot.view_y2()
    assert lo > 0.0                             # 0 is off the axis
    assert plot.start_spread([first, second])
    state = plot._scale
    assert lo <= state["level"] <= hi
    rect = plot.plot_rect()
    assert rect.top() <= state["zero"] <= rect.bottom()
    # the step follows the pointer's distance from that line: the start
    # distance is the starting step, twice as far twice the step
    base, start = state["base"], state["start"]
    x = rect.center().x()
    plot._update_spread(QPointF(x, state["zero"] - start))
    assert state["step"] == pytest.approx(base)
    plot._update_spread(QPointF(x, state["zero"] - 2.0 * start))
    assert state["step"] == pytest.approx(2.0 * base)
    plot.grab()
    plot._finish_transform(cancel=True)


def test_the_background_is_one_click_white_or_the_themes(window, tmp_path):
    from dscpanel.ui import plot as plot_module
    plot, doc = window.plot, window.doc
    assert doc.theme == plot_module.THEME_DARK
    window.set_background("#ffffff")
    assert plot.page_colour().name() == "#ffffff"
    # dark theme, white paper: the ink is the light theme's
    assert window.drawing_theme() == plot_module.THEME_LIGHT
    assert plot_module.THEME == plot_module.THEME_LIGHT
    image = plot.grab().toImage()
    assert image.pixelColor(2, 2).name() == "#ffffff"
    window.undo.undo()
    assert doc.background is None
    assert plot_module.THEME == plot_module.THEME_DARK
    window.set_background("#123456")
    sample = doc.samples[0]
    path = window.save_session(path=str(tmp_path / "b.dscpanel"))
    loaded, _problems = session.load(path, lambda _p: sample)
    assert loaded.background == "#123456"


def test_the_empty_plot_menu_offers_the_background_not_open(window):
    menu = window.context_menu_for(None)
    texts = [a.text() for a in menu.actions()]
    assert not any("Open" in t for t in texts)
    assert not any("Select everything" in t for t in texts)
    assert "Background" in texts
    assert [a.text() for a in menu._paper.actions()] == [
        "White", "The theme's", "Other colour..."]
