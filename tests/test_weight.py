"""SDT and TGA runs: the weight on the second y axis.

What drawing an SDT run's weight against a second y axis has to get right,
most of it found by a read-only review:

* which column is the percentage and which the milligrams is decided by the
  column's UNIT, never by its name alone, and neither is made from the other
  without the sample mass (golden rule 4);
* a weight that cannot be drawn says so where it would have been, like a heat
  flow that cannot (`Scan.weight_missing_for`);
* the weight axis's range survives a session, is part of the view, and has
  settings of its own; the weight curves are in the stack;
* TRIOS analyses made on the weight are never drawn on the heat flow;
* NaN - flagged samples - never reaches an offset, a fit, a CSV cell or a
  painter.

Synthetic samples are built in the shape the reader RETURNS (conftest), the
SDT columns and units as `trios_io` names them; the real files are found by
a hash of their name (`conftest.local_file`) and skip when absent.
"""

import json
import os

import numpy as np
import pytest

from dscpanel.core import arrange, export, loader, model, presets, session
from dscpanel.core import units

from conftest import local_file, make_data

# Real files, named by a hash of their file name (`conftest.hashed_name`).
#: The SDT650 reference run: TRIOS 5.1.1, 39001 samples, its .txt export
#: beside it.
SDT_REFERENCE = "sha:6ceef94fd7ce"
SDT_REFERENCE_TXT = "sha:ac9b497e666c"      # its export
#: An SDT run in an open pan, its sample mass derived from the weight.
SDT_OPEN = "sha:06ac54ff3719"
#: An SDT run whose recorded weight is negative: no sample mass.
SDT_NO_MASS = "sha:76aeb809d9b5"
#: The DSC25 reference run: TRIOS 5.1.1, seven segments, 16 stored
#: analyses, a Full .txt export beside it.
DSC_REFERENCE = "sha:b2303c243b22"
#: An indium check run with empty (NaN) samples at the start of segment 1.
INDIUM_CHECK = "sha:2efc47d254b7"
#: An empty-pan DSC25 run whose first segment (Equilibrate) flags its first
#: samples: 5 temperatures, 35 heat flows (TRI-FORMAT.md section 3).
EMPTY_PAN = "sha:2d118ff6fdd5"
DEG_C = "\u00b0C"


def _path(name):
    path = local_file(name)
    if path is None:
        pytest.skip("{} is not on this machine".format(name))
    return path


def sdt_data(points=400, mass_mg=20.0, shape="tri", segments=1):
    """An SDT run as the reader returns it: a heating ramp losing a quarter
    of its weight in one step.

    `shape` "tri" has the binary reader's columns (Weight in mg AND Weight
    Change in %), "txt" an export's (the percentage only, as the text
    reader renames it), "legacy" an export read before that rename - its
    percentage called "Weight", with the unit "%" beside it.
    """
    numdata = []
    # what the instrument weighed, whether or not the file keeps it
    weighed = mass_mg or 20.0
    for j in range(segments):
        base = np.linspace(0.0, 1.0, points)
        temp = 50.0 + 600.0 * base
        time = np.linspace(0.0, 60.0, points) + 60.0 * j
        pct = 100.0 - 25.0 / (1.0 + np.exp(-(base - 0.5) / 0.03))
        watts = -0.002 + 0.001 * np.exp(-((base - 0.4) / 0.05) ** 2)
        if shape == "tri":
            dims = ["Time", "Temperature", "Weight", "Heat Flow",
                    "Weight Change", "Heat Flow (Normalized)"]
            unit = ["min", DEG_C, "mg", "W", "%", "W/g"]
            columns = [time, temp, pct / 100.0 * weighed, watts, pct,
                       watts / (weighed / 1000.0)]
        else:
            dims = ["Time", "Temperature", "Heat Flow (Normalized)",
                    "Weight Change" if shape == "txt" else "Weight"]
            unit = ["min", DEG_C, "W/g", "%"]
            columns = [time, temp, watts / (weighed / 1000.0), pct]
        numdata.append({"prog": "Ramp 10.00 {}/min to 650.000 {} #{}".format(
            DEG_C, DEG_C, j + 1), "dims": dims, "units": unit,
            "nums": np.column_stack(columns)})
    head = {"Filename": "SDT-1", "samplename": "SDT-1",
            "instrumenttype": "SDT650"}
    if mass_mg:
        head["Sample Mass"] = "{:g} mg".format(mass_mg)
        head["mass_source"] = ("derived from the weight" if shape == "tri"
                               else "recorded")
    return {"head": head, "numdata": numdata, "analyses": {}}


def _sample(data, path="C:/nowhere/SDT-1.tri"):
    return model.Sample(path, data)


def _doc(sample, segments=None):
    doc = model.Document()
    doc.add_sample(sample, segments)
    return doc


def _window(qapp, sample, segments=None):
    from dscpanel.ui.window import MainWindow
    win = MainWindow()
    win.resize(900, 560)
    win._sample_loaded(sample)
    for seg in segments or ():
        win.toggle_segment(sample, seg, True)
    win.undo.clear()
    return win


def _csv_rows(path):
    with open(path, "r", encoding="utf-8") as fh:
        lines = [line.rstrip("\n") for line in fh]
    comments = [line for line in lines if line.startswith("#")]
    table = [line.split(",") for line in lines if not line.startswith("#")]
    return comments, table[0], table[1:]


# ------------------------------------------------ F2: % and mg, by unit
def test_a_percentage_is_known_by_its_unit_not_its_name():
    """An export read before the text reader renamed it calls its
    percentage "Weight", with "%" beside it: that is the percentage, and
    the milligrams are made from it and the mass - never 462 % of the mass
    or "99.7 mg"."""
    scan = _doc(_sample(sdt_data(shape="legacy"),
                        "C:/nowhere/SDT-1.txt")).scans[0]
    pct = scan.weight_values(model.WEIGHT_PCT)
    mg = scan.weight_values(model.WEIGHT_MG)
    assert pct is not None and mg is not None
    assert float(pct[0]) == pytest.approx(100.0, abs=0.01)
    assert float(mg[0]) == pytest.approx(20.0, abs=0.01)
    assert float(mg[-1]) == pytest.approx(15.0, abs=0.01)


def test_milligrams_from_a_percentage_need_the_mass_and_say_so():
    scan = _doc(_sample(sdt_data(shape="txt", mass_mg=None),
                        "C:/nowhere/SDT-1.txt")).scans[0]
    assert scan.sample.mass_g is None
    assert scan.weight_values(model.WEIGHT_MG) is None
    assert scan.weight_missing_for(model.WEIGHT_MG) == "sample mass"
    # the export's own percentage is what the file says it is
    assert scan.weight_missing_for(model.WEIGHT_PCT) is None
    assert float(scan.weight_values(model.WEIGHT_PCT)[0]) == \
        pytest.approx(100.0, abs=0.01)


def test_a_percentage_beside_a_weight_needs_the_mass_it_is_of():
    """Where the file records the weight in mg too and no sample mass could
    be had from them (the reader refuses one: some runs record a negative
    weight against a positive percentage), the percentage is of no mass
    anybody knows: not drawn, and said. The milligrams are recorded."""
    data = sdt_data(mass_mg=20.0)
    step = data["numdata"][0]
    step["nums"][:, 2] *= -1.0              # the Weight column, negative
    del data["head"]["Sample Mass"]
    del data["head"]["mass_source"]
    scan = _doc(_sample(data)).scans[0]
    assert scan.weight_values(model.WEIGHT_PCT) is None
    assert scan.weight_missing_for(model.WEIGHT_PCT) == "sample mass"
    mg = scan.weight_values(model.WEIGHT_MG)
    assert mg is not None and float(mg[0]) < 0
    assert scan.weight_missing_for(model.WEIGHT_MG) is None


def test_a_weight_change_in_milligrams_is_not_the_weight():
    """A column called "Weight Change" in mg is a CHANGE of weight, not the
    weight and not a percentage: neither axis takes it."""
    data = sdt_data(shape="txt")
    data["numdata"][0]["units"][3] = "mg"
    scan = _doc(_sample(data, "C:/nowhere/SDT-1.txt")).scans[0]
    assert scan.weight_values(model.WEIGHT_PCT) is None
    assert scan.weight_values(model.WEIGHT_MG) is None
    assert not scan.has_weight()


def test_a_sample_mass_that_is_not_positive_is_no_mass():
    data = sdt_data()
    data["head"]["Sample Mass"] = "-99.8968 mg"
    assert _sample(data).mass_g is None


def test_the_tri_and_its_export_give_the_same_milligrams():
    """The SDT reference run: the export has only the percentage; times the
    export's mass
    it is the .tri's recorded Weight, sample for sample."""
    tri = _doc(loader.read_sample(_path(SDT_REFERENCE))).scans[0]
    txt = _doc(loader.read_sample(_path(SDT_REFERENCE_TXT))).scans[0]
    from_tri = tri.weight_values(model.WEIGHT_MG)
    from_txt = txt.weight_values(model.WEIGHT_MG)
    assert from_txt is not None and len(from_txt) == len(from_tri)
    # the export writes the percentage to 3 decimals: 1e-5 of 21.5 mg
    assert np.nanmax(np.abs(from_txt - from_tri)) < 5e-4
    pct = txt.weight_values(model.WEIGHT_PCT)
    assert float(pct[0]) == pytest.approx(99.71, abs=0.01)
    assert float(np.nanmin(pct)) == pytest.approx(83.729, abs=0.01)


# ------------------------------------- F7: a weight that cannot be drawn
def test_a_weight_says_what_it_is_missing():
    data = sdt_data(shape="txt", mass_mg=None)
    scan = _doc(_sample(data, "C:/nowhere/SDT-1.txt")).scans[0]
    assert scan.weight_missing_for(model.WEIGHT_MG,
                                   model.AXIS_TEMPERATURE) == "sample mass"
    # no temperature in the segment: the isothermal of a run that did not
    # record one
    data = sdt_data()
    step = data["numdata"][0]
    step["nums"][:, 1] = np.nan
    scan = _doc(_sample(data)).scans[0]
    assert scan.weight_missing_for(
        model.WEIGHT_PCT, model.AXIS_TEMPERATURE) == \
        "temperature in this segment"
    assert scan.weight_missing_for(model.WEIGHT_PCT, model.AXIS_TIME) is None
    # every weight sample flagged
    data = sdt_data()
    data["numdata"][0]["nums"][:, 4] = np.nan
    data["numdata"][0]["nums"][:, 2] = np.nan
    scan = _doc(_sample(data)).scans[0]
    assert scan.weight_missing_for(model.WEIGHT_PCT) == \
        "weight in this segment"
    # a DSC segment has no weight to miss
    dsc = _doc(model.Sample("C:/nowhere/TEST-1.tri", make_data())).scans[0]
    assert dsc.weight_missing_for(model.WEIGHT_PCT) == \
        "weight in this segment"


def test_a_weight_that_cannot_be_drawn_is_said_where_it_would_be(
        qapp, tmp_path):
    """No mass, the axis in mg: no curve, no legend entry for one, the
    outliner row and the plot say NO SAMPLE MASS, and the exports admit it -
    the way a heat flow that cannot be drawn does (golden rule 4)."""
    sample = _sample(sdt_data(shape="txt", mass_mg=None),
                     "C:/nowhere/SDT-1.txt")
    win = _window(qapp, sample)
    win.toggle_signal(model.SIGNAL_HEAT)        # its W/g heat flow draws
    win.set_weight_unit(model.WEIGHT_MG)
    doc, plot = win.doc, win.plot
    (mass,) = [s for s in doc.scans if s.is_mass]
    assert mass.missing_for(doc.unit_for(mass), doc.x_axis) == "sample mass"
    assert mass not in [s for s, _t in doc.legend.entries(doc)]
    assert (mass, "sample mass") in doc.scans_missing()
    assert plot._blink_timer.isActive()
    rows = [win.outliner.topLevelItem(0)]
    texts = []
    while rows:
        item = rows.pop()
        texts.append((item.text(0), item.text(1)))
        rows.extend(item.child(k) for k in range(item.childCount()))
    assert (mass.display_name(), "NO SAMPLE MASS") in texts
    warnings = export.warnings_for(doc)
    assert any("NO SAMPLE MASS" in w and "mass is not drawn" in w
               for w in warnings)
    path = str(tmp_path / "curves.csv")
    export.curves_csv(doc, path)
    comments, header, _rows = _csv_rows(path)
    assert not any("Mass/" in h for h in header)
    assert any("is not drawn" in c for c in comments)
    plot.grab()                                 # paints, alarm and all


def test_the_negative_weight_run_draws_no_inverted_curve(qapp):
    """A run whose recorded weight is negative: the reader finds no
    sample mass, so the W/g heat flow and the percentage are placeholders
    that say so - not a curve upside down under the exo arrow."""
    sample = loader.read_sample(_path(SDT_NO_MASS))
    assert sample.mass_g is None
    win = _window(qapp, sample)
    win.toggle_signal(model.SIGNAL_HEAT)
    doc, plot = win.doc, win.plot
    (mass,) = [s for s in doc.scans if s.is_mass]
    (heat,) = [s for s in doc.scans if not s.is_mass]
    assert doc.y_unit == units.UNIT_W_G
    assert heat.missing_for(doc.y_unit, doc.x_axis) == "sample mass"
    assert mass.missing_for(doc.weight_unit, doc.x_axis) == "sample mass"
    assert not plot.drawable()
    win.set_weight_unit(model.WEIGHT_MG)
    assert [t.scan for t in plot.drawable()] == [mass]   # recorded mg
    lo, hi = plot.data_y2()
    assert hi < 0


# --------------------------------------- F4: the weight range in a session
def test_the_weight_range_survives_a_session(qapp, tmp_path):
    sample = _sample(sdt_data())
    win = _window(qapp, sample)
    win.plot.set_view_y2(80.0, 100.0)
    win.plot.commit_view()
    path = win.save_session(path=str(tmp_path / "w.dscpanel"))
    with open(path, "r", encoding="utf-8") as fh:
        saved = json.load(fh)
    assert saved["view"]["y2"] == [80.0, 100.0]
    assert saved["view"]["y2_unit"] == model.WEIGHT_PCT
    other = _window(qapp, _sample(sdt_data()))
    other.open_session(path)
    assert other.plot._view_y2 == (80.0, 100.0)
    assert not other.is_modified()


def test_a_weight_range_saved_without_its_unit_comes_back(tmp_path):
    """An older session has no "y2_unit": its range is in the
    weight unit saved beside it."""
    doc = _doc(_sample(sdt_data()))
    state = session.to_state(doc)
    state["view"] = {"x": None, "y": None, "y2": [70.0, 101.0],
                     "context": []}
    path = str(tmp_path / "old.dscpanel")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh)

    def read(_path):
        return _sample(sdt_data())
    loaded, _problems = session.load(path, read)
    assert loaded.view["y2"] == (70.0, 101.0)
    assert loaded.view["y2_unit"] == model.WEIGHT_PCT


# ---------------------------------------- F10: a y2-only view is a view
def test_a_weight_only_framing_is_saved_and_is_a_change(qapp):
    win = _window(qapp, _sample(sdt_data()))
    win.mark_clean()
    win.plot.set_view_y2(85.0, 95.0)
    assert win._current_view() is not None
    assert win._current_view()["y2"] == (85.0, 95.0)
    assert win.is_modified()


# --------------------------------------------- F5: analyses on the weight
def _weight_analyses_data():
    data = sdt_data()
    data["analyses"] = {"Ramp": {
        "Onset point": [
            {"Onset cursor x": "300.0000 \u00b0C",
             "Transition cursor x": "360.0000 \u00b0C",
             "Onset x": "340.0000 \u00b0C", "segment": 1,
             "variable": "Weight Change"},
            {"Onset cursor x": "100.0000 \u00b0C",
             "Transition cursor x": "200.0000 \u00b0C",
             "Onset x": "150.0000 \u00b0C", "segment": 1}],
        "Peak Integration (enthalpy)": [
            {"Baseline cursor x": "250.0000 \u00b0C",
             "Baseline cursor x1": "350.0000 \u00b0C",
             "Enthalpy (normalized)": "12.0000 J/g",
             "Peak temperature": "290.0000 \u00b0C", "segment": 1,
             "variable": "Heat Flow (Normalized)"}]}}
    return data


def test_an_analysis_made_on_the_weight_is_not_a_heat_flow_one():
    """A file's analysis goes to the scan of the curve it was made on: the
    onset of mass loss is the MASS scan's."""
    doc = _doc(_sample(_weight_analyses_data()),
               [0, (0, model.SIGNAL_MASS)])
    scan, mass = doc.scans
    heat = [a.model_name for a in scan.analysis_objects]
    assert "Peak Integration (enthalpy)" in heat
    assert [a.fields.get("variable") for a in mass.analysis_objects] == \
        ["Weight Change"]
    assert all(a.fields.get("variable") != "Weight Change"
               for a in scan.analysis_objects)
    # an onset whose curve the file does not state, on a run that has two:
    # offered, but not as certain
    (unknown,) = [a for a in scan.analysis_objects
                  if a.model_name == "Onset point"]
    assert not unknown.certain
    unknown.visible = True
    assert not unknown.certain
    # the integration is a heat flow's whatever the file says: J/g
    (integration,) = [a for a in scan.analysis_objects
                      if "Integration" in a.model_name]
    assert integration.certain


def test_weight_analyses_are_the_mass_scans_and_drawn_on_it(qapp):
    """Listed under the MASS scan like any analysis, with a box; shown, it
    is drawn on the mass curve; the heat flow's settings never list it."""
    from PySide6.QtCore import Qt
    from dscpanel.ui.dialogs import ScanSettings
    sample = _sample(_weight_analyses_data())
    win = _window(qapp, sample)
    win.toggle_signal(model.SIGNAL_HEAT)
    doc, plot = win.doc, win.plot
    (mass,) = [s for s in doc.scans if s.is_mass]
    (heat,) = [s for s in doc.scans if not s.is_mass]
    (onset,) = mass.analysis_objects
    rows = [win.outliner.topLevelItem(0)]
    found = None
    while rows:
        item = rows.pop()
        if item.data(0, Qt.UserRole) == ("analysis", id(onset)):
            found = item
        rows.extend(item.child(k) for k in range(item.childCount()))
    assert found is not None
    assert found.parent().data(0, Qt.UserRole) == ("scan", id(mass))
    dialog = ScanSettings(win, heat, doc.y_unit)
    texts = [dialog.analyses.item(k).text()
             for k in range(dialog.analyses.count())]
    assert not any("340" in t for t in texts)
    doc.select_only([mass])
    win.set_analyses(True)
    assert onset.visible
    plot.grab()                         # drawn against the mass axis


def test_cn81s_onsets_are_on_the_weight(qapp):
    sample = loader.read_sample(_path(SDT_REFERENCE))
    doc = _doc(sample, [0, (0, model.SIGNAL_MASS)])
    heat, mass = doc.scans
    assert sorted(round(a.value(), 3) for a in mass.analysis_objects) == \
        [415.587, 476.281]
    assert [a.model_name for a in heat.analysis_objects] == \
        ["Peak Integration (enthalpy)"]


# ---------------------------------------------- F8: the weight axis's own
def test_the_weight_axis_settings_are_the_weight_axis(qapp):
    from dscpanel.ui.dialogs import AxisSettings, CaptionSettings
    from dscpanel.ui.dialogs import NumberSettings
    win = _window(qapp, _sample(sdt_data()))
    win.toggle_signal(model.SIGNAL_HEAT)
    doc, plot = win.doc, win.plot
    axis = doc.axes["y2"]
    dialog = AxisSettings(win, axis, doc)
    lo, hi = plot.view_y2()
    assert dialog._step_shown() == pytest.approx(plot.tick_step(axis, lo, hi))
    assert dialog._step_shown() != pytest.approx(
        plot.tick_step(doc.axes["y"], *plot.view_y()))
    # it may close the box when it is the only y axis
    assert not dialog.mirror.isHidden()
    assert NumberSettings(win, axis, doc).windowTitle() == \
        "Mass axis numbers"
    assert CaptionSettings(win, axis, doc).windowTitle() == \
        "Mass axis caption"
    assert not AxisSettings(win, doc.axes["y"], doc).mirror.isHidden()


# ------------------------------------------ the mass is a scan of its own
def test_an_sdt_run_opens_with_its_mass_alone(qapp):
    """The m% data is the main curve of an SDT run: an SDT file opens
    with the first heating's MASS, on one y axis on the main side and no
    heat flow axis at all; the heat flow is one tick away. Both shown, the
    mass keeps the main (left) side and the heat flow goes right."""
    win = _window(qapp, _sample(sdt_data()))
    doc, plot = win.doc, win.plot
    (mass,) = doc.scans
    assert mass.is_mass and mass.visible
    assert [a.which for a in plot.shown_axes()] == ["x", "y2"]
    assert plot.axis_side(doc.axes["y2"]) == "left"
    assert plot.main_axis() == "y2"
    assert plot.y_mirrored(doc.axes["y2"]) == bool(doc.axes["y2"].mirror)
    win.toggle_signal(model.SIGNAL_HEAT)
    assert [a.which for a in plot.shown_axes()] == ["x", "y2", "y"]
    assert plot.axis_side(doc.axes["y"]) == "right"
    assert not plot.y_mirrored(doc.axes["y2"])
    win.undo.undo()
    assert [a.which for a in plot.shown_axes()] == ["x", "y2"]
    plot.grab()


def test_the_wheel_frames_the_mass_axis_when_it_is_the_main_one(qapp):
    win = _window(qapp, _sample(sdt_data()))
    plot = win.plot
    before = plot.view_y2()
    plot.scale_y(2.0)
    assert plot.view_y2() == pytest.approx((before[0] / 2, before[1] / 2))


def test_a_mass_scan_moves_stacks_and_converts_in_its_own_unit(qapp):
    """Its offset is in % (or mg): G by pixels uses the mass axis, S spreads
    mass scans in %, and switching the axis to mg carries the offsets by
    the sample mass (20 mg: 10 % is 2 mg), one undo step."""
    sample = _sample(sdt_data(segments=2))
    win = _window(qapp, sample)
    win.toggle_segment(sample, 1, True, model.SIGNAL_MASS)
    doc, plot = win.doc, win.plot
    first, second = doc.scans
    assert first.is_mass and second.is_mass
    rect = plot.plot_rect()
    assert plot.y_per_px(rect, first) == pytest.approx(
        (plot.view_y2()[1] - plot.view_y2()[0]) / rect.height())
    doc.select_only([first, second])
    assert plot.start_spread([first, second])
    plot._scale["typed"] = "10"
    plot._update_transform()
    plot._finish_transform()
    # tied: the outliner's first on top, the lowest stays where it was
    assert (first.offset, second.offset) == (10.0, 0.0)
    moved = first if first.offset else second
    win.set_weight_unit(model.WEIGHT_MG)
    assert moved.offset == pytest.approx(2.0)
    win.undo.undo()
    assert moved.offset == pytest.approx(10.0)


def test_a_round_25_weight_opens_as_a_mass_scan(tmp_path):
    doc = _doc(_sample(sdt_data()), [0])
    state = session.to_state(doc)
    for entry in state["scans"]:
        entry.pop("signal", None)
        entry["weight"] = {"visible": True, "dashed": True, "z": None}
    path = str(tmp_path / "r25.dscpanel")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    loaded, _problems = session.load(path, lambda _p: _sample(sdt_data()))
    assert [s.signal for s in loaded.scans] == [model.SIGNAL_HEAT,
                                                model.SIGNAL_MASS]


# ---------------------------------------------------- F9: in the stack
def test_the_mass_scans_are_in_the_stack(qapp):
    win = _window(qapp, _sample(sdt_data()))
    doc = win.doc
    (scan,) = doc.scans
    assert scan in win.stack_objects()
    doc.select_only([scan])
    assert win.layered_selected() == [scan]
    win.restack("front")
    assert win.stack_objects()[-1] is scan


# ------------------------------------------------- F11: NaN, everywhere
def _gappy_data():
    """Flagged samples where the real files have them: at the start of a
    DSC segment (empty-pan and indium check runs), and a stretch in the
    middle, which the drawing breaks at."""
    data = make_data(points=400)
    for step in data["numdata"]:
        step["nums"][:5, 1:] = np.nan
        step["nums"][200:210, 2] = np.nan
    return data


def test_align_and_stack_step_ignore_flagged_samples():
    doc = _doc(model.Sample("C:/nowhere/GAP-1.tri", _gappy_data()), [0, 1])
    first, second = doc.scans

    def curve(scan):
        return scan.kept_curve(doc.x_axis, doc.y_unit, doc.exo, doc.x_unit)
    changes = arrange.align_to(first, [first, second], curve)
    assert changes and all(np.isfinite(value) for _s, _a, value in changes)
    step = arrange.suggested_step([first, second], curve)
    assert np.isfinite(step) and step > 0
    x, y = arrange._monotonic([1.0, np.nan, 3.0, 2.0],
                              [1.0, 2.0, np.nan, 4.0])
    assert list(x) == [1.0, 2.0] and list(y) == [1.0, 4.0]


def test_a_segment_with_nothing_measured_is_missing_not_a_crash(qapp):
    """Every temperature of the first segment flagged: the fit ignores it,
    the plot paints (a NaN range made `_nice_step` raise in paintEvent,
    which aborts the program), and the scan says what it lacks."""
    data = make_data()
    data["numdata"][0]["nums"][:, 1] = np.nan
    sample = model.Sample("C:/nowhere/NAN-1.tri", data)
    doc = _doc(sample, [0, 1])
    empty = doc.scans[0]
    assert empty.missing_for(doc.y_unit, doc.x_axis) == \
        "temperature in this segment"
    data = make_data()
    data["numdata"][1]["nums"][:, 2] = np.nan
    doc2 = _doc(model.Sample("C:/nowhere/NAN-2.tri", data), [0, 1])
    assert doc2.scans[1].missing_for(doc2.y_unit, doc2.x_axis) == \
        "heat flow in this segment"
    from dscpanel.ui.plot import PlotWidget
    plot = PlotWidget(doc)
    plot.resize(700, 450)
    plot.rebuild(keep_view=False)
    lo, hi = plot.data_x()
    assert np.isfinite(lo) and np.isfinite(hi)
    assert all(np.isfinite(plot.data_y()))
    plot.grab()


def test_the_fits_and_the_picking_skip_flagged_samples(qapp):
    from dscpanel.ui.plot import PlotWidget
    doc = _doc(model.Sample("C:/nowhere/GAP-1.tri", _gappy_data()), [0, 1])
    plot = PlotWidget(doc)
    plot.resize(700, 450)
    plot.rebuild(keep_view=False)
    for pair in (plot.data_x(), plot._curves_y(), plot.data_y()):
        assert all(np.isfinite(pair))
    plot.grab()
    trace = plot.traces[0]
    from PySide6.QtCore import QPointF
    at = QPointF(plot.x_to_px(float(trace.x[100])),
                 plot.y_to_px(float(trace.y[100])))
    assert plot.sample_at(trace, at) == trace.first + 100


def test_an_analysis_over_flagged_samples_is_drawn_on_measured_ones(qapp):
    """An integration whose stretch holds flagged heat flows (an indium
    check run's first 34 samples have a temperature and no heat flow): its
    shading, the side its label goes and the point its arrow lands on come
    from the measured samples - a NaN there drew the shading and the arrow
    nowhere and put the label on the peak's side."""
    from dscpanel.core import measure
    from dscpanel.ui.plot import PlotWidget
    found = {}
    for flagged in (False, True):
        data = _gappy_data() if flagged else make_data(points=400)
        doc = _doc(model.Sample("C:/nowhere/GAP-1.tri", data))
        # the other way up, so the peak is drawn upwards
        doc.arrow.direction = ("up" if doc.arrow.direction == "down"
                               else "down")
        scan = doc.scans[0]
        plot = PlotWidget(doc)
        plot.resize(700, 450)
        plot.rebuild(keep_view=False)
        temp = scan.temperature()
        analysis = measure.run("Peak Integration (enthalpy)", scan,
                               float(temp[120]), float(temp[260]),
                               span=(120, 260))
        plot.rebuild(keep_view=True)
        plot.grab()
        trace = plot.traces[0]
        xs, ys = plot._covered(trace, analysis)
        assert np.all(np.isfinite(xs)) and np.all(np.isfinite(ys))
        rect = plot.plot_rect()
        # x of a sample whose heat flow is flagged (205): the nearest
        # MEASURED sample is the one the curve has there
        at = plot._curve_y_at(trace, float(trace.x[205 - trace.first]), rect)
        assert at is not None and np.isfinite(at)
        found[flagged] = plot.peak_points_up(analysis, trace)
    assert found[True] == found[False] is True


@pytest.mark.parametrize("name", [INDIUM_CHECK, EMPTY_PAN])
def test_a_run_that_flags_its_first_samples_picks_marks_and_measures(
        qapp, name):
    """The real runs with leading NaN (stage 1's NaN risks 1, 4 and 5): a
    click among the first samples picks a measured one, the offset marker
    sits on a measured sample, and an analysis over the start measures."""
    from PySide6.QtCore import QPointF
    from dscpanel.core import measure
    sample = loader.read_sample(_path(name))
    win = _window(qapp, sample)
    if not any(s.seg == 0 for s in win.doc.scans):
        win.toggle_segment(sample, 0, True)
    doc, plot = win.doc, win.plot
    (scan,) = [s for s in doc.scans if s.seg == 0]
    values, _base = scan.heat_flow()
    assert np.isnan(values[0]) and np.isnan(scan.temperature()[0])
    doc.offset_markers = True
    win.refresh()
    plot.grab()
    trace = plot._trace_of(scan)
    at = QPointF(float(plot.x_to_px(float(trace.x[20 - trace.first]))),
                 float(plot.y_to_px(float(np.nanmean(trace.y[:60])))))
    index = plot.sample_at(trace, at)
    assert index is not None and np.isfinite(values[index])
    k = plot.marker_sample(scan.marker, trace)
    assert k is not None and np.isfinite(trace.x[k]) and np.isfinite(
        trace.y[k])
    temp = scan.temperature()
    low, high = float(np.nanmin(temp[:200])), float(np.nanmax(temp[:200]))
    for model_name in ("Onset point", "Peak Integration (enthalpy)",
                       "Glass transition"):
        analysis = measure.run(model_name, scan, low, high, span=(0, 200))
        assert analysis is not None and np.isfinite(analysis.value())
        assert not any("nan" in str(v).lower()
                       for v in analysis.fields.values())
    win.refresh()
    plot.grab()


def test_an_axis_number_at_zero_has_no_sign(qapp):
    """Ticks are stepped in floating point, so the one at zero can be
    -2.8e-17: an empty-pan run's heat-flow axis said "-0" (found in a
    pass over the leading-NaN runs)."""
    from dscpanel.ui.plot import PlotWidget
    axis = model.Document().axes["y"]
    assert axis.number_format in (None, "")
    for which in ("x", "y", "y2"):
        assert PlotWidget.tick_text(axis, -0.1 + 0.1 - 2.7e-17, which) == "0"
        assert PlotWidget.tick_text(axis, -0.0, which) == "0"
    assert PlotWidget.tick_text(axis, -0.1, "y") == "-0.1"


def test_the_hidden_ends_are_drawn_without_flagged_samples():
    from dscpanel.ui.plot import _finite_runs
    runs = _finite_runs(np.array([np.nan, 1.0, 2.0, np.nan, 4.0, 5.0, 6.0]),
                        np.array([0.0, 1.0, 2.0, 3.0, np.nan, 5.0, 6.0]))
    assert [list(x) for x, _y in runs] == [[1.0, 2.0], [5.0, 6.0]]


def test_the_csv_leaves_flagged_samples_empty(tmp_path):
    doc = _doc(model.Sample("C:/nowhere/GAP-1.tri", _gappy_data()), [0, 1])
    path = str(tmp_path / "gap.csv")
    export.curves_csv(doc, path)
    _comments, header, rows = _csv_rows(path)
    cells = [cell for row in rows for cell in row]
    assert "nan" not in cells
    assert rows[0][0] == "" and rows[0][1] == ""        # flagged start
    assert rows[205][1] == "" and rows[205][0] != ""    # a gap in the flow


def test_the_indium_check_exports_no_nan(tmp_path):
    """The indium check run flags its first samples: 38 'nan' cells
    before."""
    sample = loader.read_sample(_path(INDIUM_CHECK))
    doc = _doc(sample)
    path = str(tmp_path / "indium.csv")
    export.curves_csv(doc, path)
    _comments, _header, rows = _csv_rows(path)
    assert "nan" not in [cell for row in rows for cell in row]


# ------------------------------------------- F12: a weight with no flow
def test_the_csv_writes_the_weight_of_a_segment_without_heat_flow(tmp_path):
    data = sdt_data()
    step = data["numdata"][0]
    keep = [0, 1, 2, 4]                     # no Heat Flow of either kind
    step["dims"] = [step["dims"][i] for i in keep]
    step["units"] = [step["units"][i] for i in keep]
    step["nums"] = step["nums"][:, keep]
    doc = _doc(_sample(data), [0, (0, model.SIGNAL_MASS)])
    scan = doc.scans[0]
    assert scan.missing_for(doc.y_unit, doc.x_axis) == \
        "heat flow in this segment"
    path = str(tmp_path / "tga.csv")
    assert export.curves_csv(doc, path) == path
    _comments, header, rows = _csv_rows(path)
    assert header[0].endswith("Temperature/C")
    assert header[1].endswith("Mass/%")
    assert float(rows[0][1]) == pytest.approx(100.0, abs=0.01)


def test_a_weight_with_no_heat_flow_beside_it_is_fitted_in_x(qapp):
    """A segment that recorded a weight and no heat flow, or whose heat
    flow cannot be drawn (the negative-weight run in W/g, its weight in
    the recorded mg): F frames the weight curve that IS drawn, not the
    0-100 of an empty plot, which showed a TGA step cut off at 100."""
    data = sdt_data()
    step = data["numdata"][0]
    keep = [0, 1, 2, 4]                     # no Heat Flow of either kind
    step["dims"] = [step["dims"][i] for i in keep]
    step["units"] = [step["units"][i] for i in keep]
    step["nums"] = step["nums"][:, keep]
    win = _window(qapp, _sample(data))
    plot = win.plot
    assert [t.scan.is_mass for t in plot.drawable()] == [True]
    lo, hi = plot.data_x()
    assert lo == pytest.approx(50.0) and hi == pytest.approx(650.0)
    win.run_op("view.fit")
    assert plot.view_x()[1] >= 650.0 - 1e-6
    plot.grab()


def test_the_csv_says_where_the_mass_came_from(tmp_path):
    doc = _doc(_sample(sdt_data()), [0, (0, model.SIGNAL_MASS)])
    path = str(tmp_path / "sdt.csv")
    export.curves_csv(doc, path)
    comments, header, _rows = _csv_rows(path)
    assert any("mass 20 mg (derived from the weight)" in c
               for c in comments)
    assert header[3].endswith("Mass/%")


# ------------------------------------------------ the scan's settings
def test_a_mass_scans_settings_are_in_its_own_unit(qapp):
    from dscpanel.ui.dialogs import ScanSettings
    win = _window(qapp, _sample(sdt_data()))
    doc = win.doc
    (mass,) = doc.scans
    dialog = ScanSettings(win, mass, doc.unit_for(mass))
    dialog.offset.setValue(-20.0)
    assert mass.offset == -20.0
    assert "%" in dialog.offset.suffix()


# ------------------------------------------------------------ presets
def test_a_preset_carries_the_weight_axis():
    doc = _doc(_sample(sdt_data()))
    doc.axes["y2"].tick_size = 14.0
    doc.axes["y2"].minor_ticks = False
    preset = presets.from_figure(doc, "big weight")
    state = presets.to_state(preset)
    assert state["objects"]["axis_y2"]["tick_size"] == 14.0
    assert "side" not in state["objects"]["axis_y2"]
    again = presets.from_state(json.loads(json.dumps(state)))
    fresh = _doc(_sample(sdt_data()))
    changes = presets.changes(fresh, again)
    assert (fresh.axes["y2"], "tick_size", 14.0) in changes
    assert (fresh.axes["y2"], "minor_ticks", False) in changes


# ------------------------------------------ the weight's hidden ends
def test_a_truncated_weights_hidden_ends_show_on_hover(qapp):
    win = _window(qapp, _sample(sdt_data()))
    doc, plot = win.doc, win.plot
    (scan,) = doc.scans
    scan.keep = (0.1, 0.9)
    win.refresh()
    (trace,) = plot.traces
    assert len(trace.hidden) == 2
    doc.select_only([scan])
    assert trace in plot.hidden_shown()
    doc.select_only([])
    assert not plot.hidden_shown()
    plot.grab()


# ---------------------------------------------------- the real files
@pytest.mark.parametrize("name", [SDT_REFERENCE, SDT_REFERENCE_TXT, SDT_OPEN,
                                  SDT_NO_MASS, DSC_REFERENCE, INDIUM_CHECK,
                                  EMPTY_PAN])
def test_a_real_file_goes_through_everything(qapp, tmp_path, name):
    """Open, toggle the weights, % and mg, M with the weight row, F, a
    session there and back, CSV, PNG and SVG: nothing raises, nothing NaN
    reaches a range, no CSV cell says nan."""
    sample = loader.read_sample(_path(name))
    win = _window(qapp, sample)
    plot = win.plot
    plot.grab()
    for op in ("view.weights", "view.weights", "view.weight_mg",
               "view.weight_percent"):
        if win.ops.get(op).enabled(win):
            win.run_op(op)
            plot.grab()
    dialog = win.x_range_dialog()
    lo, hi = plot.view_x()
    y2 = None
    if dialog.y2_low_edit is not None:
        y2 = (float(dialog.y2_low_edit.text()) - 1.0,
              float(dialog.y2_high_edit.text()) + 1.0)
    win.set_x_range(lo, hi, y=None, y2=y2)
    plot.reset_view()
    plot.reset_view()
    for pair in (plot.view_x(), plot.view_y(), plot.view_y2()):
        assert all(np.isfinite(pair))
    path = win.save_session(path=str(tmp_path / "s.dscpanel"))
    win.open_session(path)
    assert not win.is_modified()
    csv = str(tmp_path / "c.csv")
    if export.curves_csv(win.doc, csv):
        _comments, _header, rows = _csv_rows(csv)
        assert "nan" not in [cell for row in rows for cell in row]
    assert win.export_image(str(tmp_path / "f.png"), light=True)
    assert win.export_image(str(tmp_path / "f.svg"), light=True)


# ------------------------------------------------ mass at a temperature
def test_the_mass_at_a_temperature_is_the_curves_without_its_offset():
    """The template's `add_annot`: the first measured sample at or past the
    temperature, its m% - the measurement, the offset not in it."""
    from dscpanel.core import labels, measure
    doc = _doc(_sample(sdt_data()), [(0, model.SIGNAL_MASS)])
    (mass,) = doc.scans
    mass.offset = -20.0
    analysis = measure.run(measure.MASS_AT, mass, 350.0, 350.0)
    at = float(analysis.fields["Cursor x"].split()[0])
    assert at >= 350.0 and at - 350.0 < 600.0 / 399 + 1e-9
    # the step is centred on 350 degC (100 - 25 / 2 = 87.5 there); the
    # first sample past it has lost a little more
    assert float(analysis.fields["Mass"].split()[0]) == pytest.approx(
        87.5, abs=0.6)             # samples are 1.5 K apart there
    assert labels.render(analysis, doc).text == "87 %"
    assert analysis.quantity == "mass" and not analysis.marks_a_point
    assert not analysis.show_interval
    doc.set_weight_unit(model.WEIGHT_MG)
    assert labels.render(analysis, doc).text == "17 mg"   # 87.24 % of 20 mg
    assert measure.run(measure.MASS_AT, mass, 900.0, 900.0) is None
    # a heat flow's curve is not offered the model
    heat = model.Scan(1, mass.sample, 0, "#ffffff")
    assert measure.MASS_AT not in [m.name for m in measure.models_for(heat)]
    assert measure.MASS_AT in [m.name for m in measure.models_for(mass)]


def test_typed_temperatures_mark_every_chosen_mass_curve_in_one_step(
        qapp, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    sample = _sample(sdt_data(segments=2))
    win = _window(qapp, sample)
    win.toggle_segment(sample, 1, True, model.SIGNAL_MASS)
    win.undo.clear()
    doc, plot = win.doc, win.plot
    first, second = doc.scans
    monkeypatch.setattr(QInputDialog, "getText",
                        lambda *a, **k: ("261, 360; 480 630", True))
    assert win.ops.get("analysis.mass_at").enabled(win)
    made = win.ask_mass_temperatures()
    assert len(made) == 8
    assert [len(s.analysis_objects) for s in (first, second)] == [4, 4]
    plot.grab()
    # the label hangs ABOVE its point
    trace = plot._trace_of(first)
    assert plot.label_offset(made[0], trace, plot.plot_rect()) < 0
    win.undo.undo()
    assert not first.analysis_objects and not second.analysis_objects
    # only the selected curve, when one is selected
    doc.select_only([second])
    monkeypatch.setattr(QInputDialog, "getText",
                        lambda *a, **k: ("300", True))
    win.run_op("analysis.mass_at")
    assert (len(first.analysis_objects), len(second.analysis_objects)) == \
        (0, 1)


def test_the_temperatures_are_split_without_eating_decimal_commas():
    from dscpanel.ui.window import parse_temperatures
    assert parse_temperatures("261, 360, 480, 630", units.TEMP_C) == \
        [261.0, 360.0, 480.0, 630.0]
    assert parse_temperatures("261,5 300", units.TEMP_C) == [261.5, 300.0]
    assert parse_temperatures("98 F; 400 K", units.TEMP_C) == \
        pytest.approx([36.667, 126.85], abs=1e-3)
    assert parse_temperatures("hot", units.TEMP_C) is None


def test_a_right_click_puts_a_marker_where_it_was(qapp):
    win = _window(qapp, _sample(sdt_data()))
    doc, plot = win.doc, win.plot
    (mass,) = doc.scans
    plot.grab()
    trace = plot._trace_of(mass)
    k = len(trace.x) // 2
    at = plot._sample_point(trace, trace.first + k)
    (made,) = win.mass_here(mass, at)
    assert float(made.fields["Cursor x"].split()[0]) == pytest.approx(
        float(trace.x[k]), abs=2.0)


def test_a_mass_marker_survives_a_session(qapp, tmp_path):
    from dscpanel.core import labels
    win = _window(qapp, _sample(sdt_data()))
    (mass,) = win.doc.scans
    win.add_mass_markers([mass], [350.0])
    path = win.save_session(path=str(tmp_path / "m.dscpanel"))
    loaded, problems = session.load(path, lambda _p: _sample(sdt_data()))
    assert not problems
    (again,) = [a for s in loaded.scans for a in s.analysis_objects]
    assert again.model_name == "Mass at temperature"
    assert labels.render(again, loaded).text == "87 %"


def test_a_marker_on_a_run_with_no_mass_says_its_recorded_mg(qapp):
    """The negative-weight run has no sample mass, so no percentage;
    its mg are recorded, and a marker in mg says them."""
    from dscpanel.core import labels, measure
    sample = loader.read_sample(_path(SDT_NO_MASS))
    doc = _doc(sample, [(0, model.SIGNAL_MASS)])
    doc.set_weight_unit(model.WEIGHT_MG)
    (mass,) = doc.scans
    analysis = measure.run(measure.MASS_AT, mass, 100.0, 100.0)
    assert "Mass" not in analysis.fields and "Mass (mg)" in analysis.fields
    assert labels.render(analysis, doc).text.endswith(" mg")
    assert not labels.render(analysis, doc).text.startswith("?")
    doc.weight_unit = model.WEIGHT_PCT
    assert labels.render(analysis, doc).text == "? %"


# ---------------------------------------------- onsets on the mass
def test_trioss_mass_onsets_draw_their_construction_on_the_mass(qapp):
    """The SDT reference run's two onsets were made in TRIOS on the
    weight: they are the MASS scan's, and draw TRIOS's stored
    construction in % on its curve."""
    from dscpanel.core import labels, measure
    win = _window(qapp, loader.read_sample(_path(SDT_REFERENCE)))
    doc, plot = win.doc, win.plot
    (mass,) = doc.scans
    onsets = [a for a in mass.analysis_objects if a.model_name == "Onset point"]
    assert len(onsets) == 2
    for analysis in onsets:
        found = measure.tangent_points(analysis)
        assert found.points and found.base == model.WEIGHT_PCT
        analysis.visible = True
    assert sorted(labels.render(a, doc).text for a in onsets) == \
        ["*T*_{on} = 416 °C", "*T*_{on} = 476 °C"]
    win.refresh()
    plot.grab()
    trace = plot._trace_of(mass)
    for analysis in onsets:
        lines = plot.tangent_lines(trace, analysis)
        assert lines and len(lines) == 2


def test_an_onset_is_measured_on_a_mass_curve():
    from dscpanel.core import measure
    doc = _doc(_sample(sdt_data()), [(0, model.SIGNAL_MASS)])
    (mass,) = doc.scans
    assert "Onset point" in [m.name for m in measure.models_for(mass)]
    analysis = measure.run("Onset point", mass, 250.0, 360.0)
    # the step's steepest point is at 350 degC; its onset a little before
    onset = float(analysis.fields["Onset x"].split()[0])
    assert 310.0 < onset < 350.0
    found = measure.tangent_points(analysis)
    assert found.points and found.base == model.WEIGHT_PCT
    # a heat flow's construction is never drawn on the mass, nor the other
    # way round
    analysis.source = "file"
    analysis.stored_construction = found.points
    analysis.fields["variable"] = "Heat Flow (Normalized)"
    assert measure.tangent_points(analysis).points is None
