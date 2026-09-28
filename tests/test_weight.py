"""SDT and TGA runs: the weight on the second y axis (round 25, finished).

Round 25 drew an SDT run's weight against a second y axis, on the desktop,
without tests. These pin what it has to get right, most of it found by the
read-only review of 2026-09-28 (its findings F2-F13):

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
name (`conftest.local_file`) and skip when absent.
"""

import json
import os

import numpy as np
import pytest

from dscpanel.core import arrange, export, loader, model, presets, session
from dscpanel.core import units

from conftest import local_file, make_data

CN81_TRI = "CN-81-I-0.45-SDT.tri"
CN81_TXT = "cn-81-i-0.45-sdt.txt"
DESY_OPEN = "CN-123-EXAFS-SDT_OPEN.tri"
DESY_NO_MASS = "CN-112_119-EXAFS-ag-SDT.tri"
OJ12 = "OJ-12-DSC-2-07012026.tri"
INDIUM_CHECK = "CN-INDIUM-CHECK.tri"
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
    be had from them (the reader refuses one: the DESY runs' negative
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
    """CN-81: the export has only the percentage; times the export's mass
    it is the .tri's recorded Weight, sample for sample."""
    tri = _doc(loader.read_sample(_path(CN81_TRI))).scans[0]
    txt = _doc(loader.read_sample(_path(CN81_TXT))).scans[0]
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
    win.set_weight_unit(model.WEIGHT_MG)
    doc, plot = win.doc, win.plot
    scan = doc.scans[0]
    assert not plot.y2_shown()
    assert not [e for e, _t in doc.legend.entries(doc)
                if isinstance(e, model.WeightCurve)]
    assert doc.weights_missing() == [(scan, "sample mass")]
    assert plot._blink_timer.isActive()
    rows = [win.outliner.topLevelItem(0)]
    texts = []
    while rows:
        item = rows.pop()
        texts.append((item.text(0), item.text(1)))
        rows.extend(item.child(k) for k in range(item.childCount()))
    assert ("Weight", "NO SAMPLE MASS") in texts
    warnings = export.warnings_for(doc)
    assert any("NO SAMPLE MASS" in w and "weight" in w for w in warnings)
    path = str(tmp_path / "curves.csv")
    export.curves_csv(doc, path)
    comments, header, _rows = _csv_rows(path)
    assert not any("Weight" in h for h in header)
    assert any("weight is not drawn" in c for c in comments)
    plot.grab()                                 # paints, alarm and all


def test_the_negative_weight_run_draws_no_inverted_curve(qapp):
    """A DESY run whose recorded weight is negative: the reader finds no
    sample mass, so the W/g heat flow and the percentage are placeholders
    that say so - not a curve upside down under the exo arrow."""
    sample = loader.read_sample(_path(DESY_NO_MASS))
    assert sample.mass_g is None
    win = _window(qapp, sample)
    doc, plot = win.doc, win.plot
    scan = doc.scans[0]
    assert doc.y_unit == units.UNIT_W_G
    assert scan.missing_for(doc.y_unit, doc.x_axis) == "sample mass"
    assert scan.weight_missing_for(doc.weight_unit, doc.x_axis) == \
        "sample mass"
    assert not plot.drawable() and not plot.y2_shown()
    win.set_weight_unit(model.WEIGHT_MG)
    assert plot.y2_shown()                   # the recorded milligrams
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
    """A session written by round 25 has no "y2_unit": its range is in the
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
    scan = _doc(_sample(_weight_analyses_data())).scans[0]
    heat = [a.model_name for a in scan.analysis_objects]
    assert "Peak Integration (enthalpy)" in heat
    assert [a.fields.get("variable") for a in scan.weight_analyses] == \
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


def test_weight_analyses_are_listed_honestly_and_never_drawn(qapp):
    from dscpanel.ui.dialogs import ScanSettings
    sample = _sample(_weight_analyses_data())
    win = _window(qapp, sample)
    doc = win.doc
    scan = doc.scans[0]
    weight_row = None
    rows = [win.outliner.topLevelItem(0)]
    while rows:
        item = rows.pop()
        if item.text(0) == "Weight":
            weight_row = item
        rows.extend(item.child(k) for k in range(item.childCount()))
    assert weight_row is not None and weight_row.childCount() == 1
    child = weight_row.child(0)
    assert "on the weight, not drawn" in child.text(1)
    assert not (child.flags() & 0x10)            # Qt.ItemIsUserCheckable
    dialog = ScanSettings(win, scan, doc.y_unit)
    texts = [dialog.analyses.item(k).text()
             for k in range(dialog.analyses.count())]
    assert any("on the weight, not drawn" in t for t in texts)
    # showing every analysis of the scan never reaches the weight's
    doc.select_only([scan])
    win.set_analyses(True)
    assert not any(a.visible for a in scan.weight_analyses)
    assert all(a not in doc.analyses() for a in scan.weight_analyses)


def test_cn81s_onsets_are_on_the_weight(qapp):
    sample = loader.read_sample(_path(CN81_TRI))
    scan = _doc(sample).scans[0]
    assert sorted(round(a.value(), 3) for a in scan.weight_analyses) == \
        [415.587, 476.281]
    assert [a.model_name for a in scan.analysis_objects] == \
        ["Peak Integration (enthalpy)"]


# ---------------------------------------------- F8: the weight axis's own
def test_the_weight_axis_settings_are_the_weight_axis(qapp):
    from dscpanel.ui.dialogs import AxisSettings, CaptionSettings
    from dscpanel.ui.dialogs import NumberSettings
    win = _window(qapp, _sample(sdt_data()))
    doc, plot = win.doc, win.plot
    axis = doc.axes["y2"]
    dialog = AxisSettings(win, axis, doc)
    lo, hi = plot.view_y2()
    assert dialog._step_shown() == pytest.approx(plot.tick_step(axis, lo, hi))
    assert dialog._step_shown() != pytest.approx(
        plot.tick_step(doc.axes["y"], *plot.view_y()))
    assert dialog.mirror.isHidden() and dialog.mirror_ticks.isHidden()
    assert NumberSettings(win, axis, doc).windowTitle() == \
        "Weight axis numbers"
    assert CaptionSettings(win, axis, doc).windowTitle() == \
        "Weight axis caption"
    assert not AxisSettings(win, doc.axes["y"], doc).mirror.isHidden()


# ---------------------------------------------------- F9: in the stack
def test_the_weight_curves_are_in_the_stack(qapp):
    win = _window(qapp, _sample(sdt_data()))
    doc = win.doc
    scan = doc.scans[0]
    assert scan.weight in win.stack_objects()
    doc.select_only([doc.legend])
    win.restack("back")
    assert scan.weight.z is not None
    stack = win.stack_objects()
    assert stack.index(scan.weight) < stack.index(doc.legend) or \
        doc.legend.z == 0.0
    doc.select_only([scan.weight])
    assert win.layered_selected() == [scan.weight]
    win.restack("front")
    assert win.stack_objects()[-1] is scan.weight


# ------------------------------------------------- F11: NaN, everywhere
def _gappy_data():
    """Flagged samples where the real files have them: at the start of a
    DSC segment (four GQ runs, CN-INDIUM-CHECK), and a stretch in the
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
    """CN-INDIUM-CHECK flags its first samples: 38 'nan' cells before."""
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
    doc = _doc(_sample(data))
    scan = doc.scans[0]
    assert scan.missing_for(doc.y_unit, doc.x_axis) == \
        "heat flow in this segment"
    path = str(tmp_path / "tga.csv")
    assert export.curves_csv(doc, path) == path
    _comments, header, rows = _csv_rows(path)
    assert header[0].endswith("Temperature/C")
    assert header[1].endswith("Weight/%")
    assert float(rows[0][1]) == pytest.approx(100.0, abs=0.01)


def test_the_csv_says_where_the_mass_came_from(tmp_path):
    doc = _doc(_sample(sdt_data()))
    path = str(tmp_path / "sdt.csv")
    export.curves_csv(doc, path)
    comments, header, _rows = _csv_rows(path)
    assert any("mass 20 mg (derived from the weight)" in c
               for c in comments)
    assert header[2].endswith("Weight/%")


# ------------------------------------------------ the scan's settings
def test_the_scan_settings_show_and_dash_the_weight(qapp):
    from dscpanel.ui.dialogs import ScanSettings
    sample = _sample(sdt_data(segments=2))
    win = _window(qapp, sample, segments=[1])
    doc = win.doc
    first, second = doc.scans
    doc.select_only([first, second])
    dialog = ScanSettings(win, first, doc.y_unit)
    dialog.set_group([second])
    assert dialog.weight_shown.isChecked() and dialog.weight_dashed.isChecked()
    dialog.weight_dashed.setChecked(False)
    assert not first.weight.dashed and not second.weight.dashed
    dialog.weight_shown.setChecked(False)
    assert not first.weight.visible and not second.weight.visible
    win._live_dialog_done(dialog, first, "scan settings",
                          dialog.snapshot(), None, 1)
    assert not second.weight.visible
    win.undo.undo()
    assert first.weight.visible and second.weight.visible
    assert first.weight.dashed and second.weight.dashed
    # a DSC scan has no weight rows
    dsc = model.Sample("C:/nowhere/TEST-1.tri", make_data())
    other = _window(qapp, dsc)
    assert ScanSettings(other, other.doc.scans[0],
                        other.doc.y_unit).weight_shown is None


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
    scan = doc.scans[0]
    scan.keep = (0.1, 0.9)
    win.refresh()
    (trace,) = plot.weight_traces
    assert len(trace.hidden) == 2
    doc.select_only([scan])
    assert trace in plot.hidden_weights_shown()
    doc.select_only([])
    assert not plot.hidden_weights_shown()
    plot.grab()


# ---------------------------------------------------- the real files
@pytest.mark.parametrize("name", [CN81_TRI, CN81_TXT, DESY_OPEN,
                                  DESY_NO_MASS, OJ12, INDIUM_CHECK])
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
