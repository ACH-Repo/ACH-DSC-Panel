"""Tangent constructions for onset, endset and glass transition.

* The construction is worked out - TRIOS's STORED one for a `.tri`'s own
  analysis, Python's for one made here, none for a `.txt` export's - and
  checked against the numbers. It puts the analysis's POINT: where the
  tangents cross, which may lie off the curve. The figure draws straight
  lines from the dash at each bound, on the trace, to that point (a Tg's
  two: its onset and end) and points the label's arrow at it; without a
  construction, the point on the curve. Or no lines, as the analysis or
  the house style says. Solid, in the axis colour.
* The panel's endset was its onset, and a cooling onset took its baseline
  on the far side: the flat cursor goes by ACQUISITION order.

The synthetic data is in the shape the reader RETURNS (conftest.make_data);
the real files are found by name (conftest.local_file) and the tests that
need them skip without them.
"""

import math

import numpy as np
import pytest

from PySide6.QtCore import QPointF

from conftest import local_file, make_data
from dscpanel.core import measure, model, session, style, trios_analysis
from dscpanel.core import trios_io, units

#: The DSC25 reference run (TRIOS 5.1.1, seven segments, 16 stored
#: analyses), named by a hash of its file name (`conftest.hashed_name`).
DSC_REFERENCE = "sha:b2303c243b22"

STEP_AT = 140.0


def _step_data(points=1200):
    """A heating and a cooling ramp (make_data's layout, the dip at the
    start included), each with a sigmoid STEP in its heat flow at 140 degC:
    a transition with a flat side each way, so an onset and an endset of
    the same interval have somewhere different to be."""
    numdata = []
    for j, up in enumerate((True, False)):
        base = np.linspace(0.0, 1.0, points)
        temp = (30.0 + 220.0 * base) if up else (250.0 - 220.0 * base)
        temp[:6] -= 4.0 if up else -4.0
        temp[-3:] += 1.5 if up else -1.5
        time = np.linspace(0.0, 22.0, points) + j * 22.0
        watts = (-0.004 + 2e-6 * temp
                 + 0.002 / (1.0 + np.exp(-(temp - STEP_AT) / 4.0)))
        numdata.append({
            "prog": "Ramp 10,00 C/min to {} C #{}".format(
                250 if up else 30, j + 1),
            "dims": ["Time", "Temperature", "Heat Flow"],
            "units": ["min", "C", "W"],
            "nums": np.column_stack([time, temp, watts])})
    return {"head": {"Filename": "STEP-1", "samplename": "STEP-1",
                     "instrumenttype": "DSC25", "samplesize": "8,0"},
            "numdata": numdata, "analyses": {}}


def _scans(data=None, path="C:/nowhere/STEP-1.tri"):
    sample = model.Sample(path, data or _step_data())
    return sample, [model.Scan(j, sample, j, "#000000")
                    for j in range(sample.segment_count())]


def _value(fields, key):
    return model.number(fields[key])


# ------------------------------------------------ the endset and the cooling
def test_the_endset_is_not_the_onset():
    """On the same interval an endset's flat side is the LATER one: on a
    heating scan the high cursor. It used to be handed the low cursor like
    the onset, and came out as the onset under another name."""
    _sample, (heat, _cool) = _scans()
    onset = measure.compute("Onset point", heat, 110.0, 170.0)
    endset = measure.compute("Endset point", heat, 110.0, 170.0)
    first, last = _value(onset, "Onset x"), _value(endset, "Endset x")
    assert first < STEP_AT < last
    assert last - first > 8.0
    # its construction starts on the inflection tangent and ends at the flat
    # cursor, as TRIOS stores an endset's
    made = measure.run("Endset point", heat, 110.0, 170.0)
    points = measure.tangent_points(made).points
    assert points[2][0] == pytest.approx(170.0)
    assert points[1][0] == pytest.approx(made.value(), abs=1e-4)


def test_a_cooling_onset_takes_its_baseline_on_the_high_side():
    """Cooling, the instrument meets the HIGH cursor first: that is the
    onset's flat side. Sorting the cursors put the baseline on the side
    after the transition."""
    _sample, (heat, cool) = _scans()
    assert cool.direction() == "down"
    cooling = measure.run("Onset point", cool, 110.0, 170.0)
    heating = measure.run("Onset point", heat, 110.0, 170.0)
    assert cooling.value() > STEP_AT > heating.value()
    flat, transition = measure.flat_and_transition(cool, 110.0, 170.0)
    assert (flat, transition) == (170.0, 110.0)
    points = measure.tangent_points(cooling).points
    assert points[0][0] == pytest.approx(170.0)         # onset: flat first
    # the baseline tangent IS the high side's: at the curve's height there,
    # and about as steep as the baseline (0.25 mW/g/K), not as the step
    # (15.6 mW/g/K)
    _t, temperature, flow = measure._series(cool)
    high = trios_analysis._at(temperature, flow, 170.0)
    assert points[0][1] == pytest.approx(high, abs=2e-3)
    slope = (points[1][1] - points[0][1]) / (points[1][0] - points[0][0])
    assert abs(slope) < 1e-3


def test_a_cooling_glass_transition_starts_on_the_high_side():
    """The same care for a Tg: its onset is where the tangent at the cursor
    met FIRST crosses the inflection tangent. The midpoint does not move."""
    _sample, (heat, cool) = _scans()
    down = measure.compute("Glass transition", cool, 110.0, 170.0)
    up = measure.compute("Glass transition", heat, 110.0, 170.0)
    assert _value(down, "Onset x") > _value(down, "Midpoint") \
        > _value(down, "End x")
    assert _value(up, "Onset x") < _value(up, "Midpoint") < _value(up, "End x")
    assert _value(down, "Midpoint") == pytest.approx(STEP_AT, abs=0.5)
    assert _value(up, "Midpoint") == pytest.approx(STEP_AT, abs=0.5)


def test_measured_along_the_curve_the_samples_say_which_came_first():
    _sample, (heat, cool) = _scans()
    assert measure.acquisition_order(heat, 170.0, 110.0) == (110.0, 170.0)
    assert measure.acquisition_order(cool, 110.0, 170.0) == (170.0, 110.0)
    temperature = cool.temperature()
    a = int(np.argmin(np.abs(temperature - 170.0)))
    b = int(np.argmin(np.abs(temperature - 110.0)))
    assert measure.acquisition_order(cool, 110.0, 170.0, span=(b, a)) \
        == (170.0, 110.0)


def test_the_panel_endset_matches_trios_on_the_reference_run():
    """The DSC reference run's first heating, on the cursors of its stored
    endset (Transition 93.465, Onset cursor 116.637): TRIOS says 108.024. The
    panel said 94.83 - its onset - under the name of an endset."""
    path = local_file(DSC_REFERENCE)
    if path is None:
        pytest.skip("the DSC reference run is not on this machine")
    sample = model.Sample(path, trios_io.read_tri(path))
    scan = model.Scan(1, sample, 0, "#000000")
    endset = measure.compute("Endset point", scan, 93.4654, 116.6373)
    onset = measure.compute("Onset point", scan, 93.4654, 116.6373)
    assert _value(endset, "Endset x") == pytest.approx(108.024, abs=0.1)
    assert abs(_value(onset, "Onset x") - _value(endset, "Endset x")) > 5.0


# ------------------------------------------------------ the construction
def test_the_python_construction_has_trioss_shape():
    """TRIOS's three points (TRI-FORMAT.md section 5): the flat point at
    the flat cursor ON the baseline tangent, the crossing (the result), and
    the far point where the inflection tangent reaches the curve's height
    at the transition cursor. Mirrored for an endset."""
    _sample, (heat, _cool) = _scans()
    _t, temperature, flow = measure._series(heat)
    for kind, flat, transition in (("onset", 110.0, 170.0),
                                   ("endset", 170.0, 110.0)):
        result = trios_analysis.onset_point(temperature, flow, flat,
                                            transition, kind=kind)
        points = result["construction"]
        key = "Endset x" if kind == "endset" else "Onset x"
        near, far = (points[2], points[0]) if kind == "endset" \
            else (points[0], points[2])
        assert points[1][0] == pytest.approx(result[key], abs=1e-9)
        assert near[0] == pytest.approx(flat)
        slope, intercept = result["tangent_cursor"]
        assert near[1] == pytest.approx(slope * flat + intercept)
        curve = trios_analysis._at(temperature, flow, transition)
        assert far[1] == pytest.approx(curve, rel=1e-9)
        slope, intercept = result["tangent_inflection"]
        assert far[1] == pytest.approx(slope * far[0] + intercept, rel=1e-9)


@pytest.mark.parametrize("name", [
    DSC_REFERENCE,
    "sha:9f0ad8af1175",    # a TRIOS 6.0 DSC25 run with its own export
    "sha:5f4207088616",    # a TRIOS 6.0 DSC25 run with an audit line
])
def test_python_and_trios_draw_the_same_construction(name):
    """On the reference files: every stored onset and endset is drawn from
    TRIOS's own points (the crossing IS the stored result, the flat point
    at the flat cursor, which TRIOS calls "Onset cursor x" for both), and
    the same interval measured here is drawn from Python's points, of the
    same shape, crossing at the panel's own number."""
    path = local_file(name)
    if path is None:
        pytest.skip(name + " is not on this machine")
    sample = model.Sample(path, trios_io.read_tri(path))
    checked = 0
    for seg in range(sample.segment_count()):
        scan = model.Scan(seg, sample, seg, "#000000")
        for stored in list(scan.analysis_objects):
            if stored.model_name not in ("Onset point", "Endset point"):
                continue
            endset = "Endset" in stored.model_name
            trios = measure.tangent_points(stored, scan)
            assert trios.points == stored.stored_construction
            assert trios.base == units.UNIT_W_G
            flat = model.number(stored.fields["Onset cursor x"])
            assert trios.points[1][0] == pytest.approx(stored.value(),
                                                       abs=1e-4)
            assert trios.points[2 if endset else 0][0] == pytest.approx(
                flat, abs=1e-3)
            made = measure.run(stored.model_name, scan,
                               *sorted(stored.cursors()))
            python = measure.tangent_points(made, scan)
            assert python.reason == ""
            assert python.points[1][0] == pytest.approx(made.value(),
                                                        abs=1e-4)
            assert python.points[2 if endset else 0][0] == pytest.approx(
                flat, abs=1e-6)
            # 0.03 to 2.6 K apart on these files (report_tangents)
            assert abs(python.points[1][0] - trios.points[1][0]) < 3.0
            checked += 1
    assert checked


def test_a_tri_analysis_draws_trioss_points_and_a_panel_one_pythons():
    """Decision 2: whose construction follows who made the number."""
    data = _step_data()
    points = [[110.0, -0.2], [131.0, -0.19], [139.0, 0.0]]
    data["analyses"] = {"Ramp 10,00 C/min to 250 C #1": {"Onset point": [
        {"segment": 1, "Onset cursor x": "110.0000 \u00b0C",
         "Transition cursor x": "170.0000 \u00b0C",
         "Onset x": "131.0000 \u00b0C",
         "variable": "Heat Flow (Normalized)", "construction": points}]}}
    _sample, (heat, _cool) = _scans(data)
    (analysis,) = heat.analysis_objects
    found = measure.tangent_points(analysis)
    assert found.points == points and found.base == units.UNIT_W_G
    assert found.reason == ""
    # recomputed here (a gizmo moved), it is the panel's: Python's points
    analysis.source = "panel"
    python = measure.tangent_points(analysis)
    assert python.points != points and python.reason == ""
    # a construction on the raw heat flow is in watts
    analysis.source = "file"
    analysis.fields["variable"] = "Heat Flow"
    assert measure.tangent_points(analysis).base == units.BASE_UNIT
    # one made on the weight has no place on the heat-flow axes
    analysis.fields["variable"] = "Weight Change"
    assert measure.tangent_points(analysis).points is None
    assert measure.tangent_points(analysis).reason == measure.ON_THE_WEIGHT


def test_an_export_has_no_tangents_and_says_so():
    data = _step_data()
    data["analyses"] = {"Ramp 10,00 C/min to 250 C": {"Onset point": [
        {"Onset cursor x": "110,0 \u00b0C",
         "Transition cursor x": "170,0 \u00b0C",
         "Onset x": "131,0 \u00b0C"}]}}
    _sample, (heat, _cool) = _scans(data, "C:/nowhere/STEP-1.txt")
    (analysis,) = heat.analysis_objects
    found = measure.tangent_points(analysis)
    assert found.points is None
    assert found.reason == measure.NO_TANGENTS_EXPORT
    assert len(found.reason) < 60                       # one short line


def test_tangents_in_w_g_on_a_run_without_a_mass_are_not_papered_over():
    """A run with no sample mass draws in mW, but TRIOS's points are in W/g
    (the construction of an analysis made on the normalised curve): they
    cannot be put on that axis."""
    data = _step_data()
    del data["head"]["samplesize"]
    data["analyses"] = {"Ramp 10,00 C/min to 250 C #1": {"Onset point": [
        {"segment": 1, "Onset cursor x": "110.0000 \u00b0C",
         "Transition cursor x": "170.0000 \u00b0C",
         "Onset x": "131.0000 \u00b0C", "variable": "Heat Flow (Normalized)",
         "construction": [[110.0, -0.2], [131.0, -0.19], [139.0, 0.0]]}]}}
    sample, (heat, _cool) = _scans(data)
    assert sample.mass_g is None
    (analysis,) = heat.analysis_objects
    found = measure.tangent_points(analysis)
    assert found.points and found.base == units.UNIT_W_G
    assert heat.axes_points(found.points, found.base, units.UNIT_MW,
                            units.EXO_DOWN) == (None, None)


def test_tangents_that_barely_cross_are_not_a_construction():
    """A curve with no transition: the tangents are (nearly) parallel and
    meet far away or nowhere. No lines from that - chords, and why."""
    data = _step_data()
    step = data["numdata"][0]["nums"]
    step[:, 2] = -0.004 + 2e-6 * step[:, 1]            # a straight line
    _sample, (heat, _cool) = _scans(data)
    analysis = model.Analysis(1, heat, "Onset point", {
        "Onset cursor x": "110.0000 \u00b0C",
        "Transition cursor x": "170.0000 \u00b0C",
        "Onset x": "140.0000 \u00b0C"}, source="panel",
        attribution="measured here")
    found = measure.tangent_points(analysis)
    assert found.points is None and found.reason == measure.DEGENERATE


def test_the_construction_is_worked_out_once_per_interval():
    _sample, (heat, _cool) = _scans()
    made = measure.run("Onset point", heat, 110.0, 170.0)
    first = measure.tangent_points(made)
    assert measure.tangent_points(made) is first            # memoised
    temperature = heat.temperature()
    made.span = (int(np.argmin(np.abs(temperature - 112.0))),
                 int(np.argmin(np.abs(temperature - 170.0))))
    again = measure.tangent_points(made)
    assert again is not first                               # the span moved


def test_flagged_samples_do_not_poison_a_fit():
    """A flagged sample is NaN; one inside a least-squares window made the
    tangent NaN, and one inside an integral the enthalpy. The measurement
    runs on the measured samples."""
    clean = _step_data()
    flagged = _step_data()
    nums = flagged["numdata"][0]["nums"]
    temperature = nums[:, 1]
    inside = int(np.argmin(np.abs(temperature - 150.0)))
    nums[:4, 2] = np.nan                       # flagged at the start
    nums[inside, 2] = np.nan                   # and one in the window
    nums[-7:, 2] = np.nan                      # and the tail
    _s, (good, _c) = _scans(clean)
    _s, (bad, _c) = _scans(flagged)
    for name, key in (("Onset point", "Onset x"),
                      ("Peak Integration (enthalpy)",
                       "Enthalpy (normalized)")):
        want = _value(measure.compute(name, good, 110.0, 170.0), key)
        got = _value(measure.compute(name, bad, 110.0, 170.0), key)
        assert np.isfinite(got)
        assert got == pytest.approx(want, rel=2e-3, abs=0.05)


def test_a_point_taken_off_the_curve_lands_on_it_in_every_unit(document):
    """`Scan.axes_points` maps (degC, heat flow) exactly as `Scan.curve`
    maps the scan: mW, W/g and W/mol, exo flipped, offset, K. A point AT a
    sample - given in watts or in W/g - is that sample of the drawn
    curve."""
    scan = document.scans[0]
    sample = scan.sample
    sample.molar_mass = 250.0
    scan.offset = 0.7
    temperature = scan.temperature()
    watts = scan.heat_flow()[0]
    k = 150
    for unit in units.UNITS:
        for exo in (units.EXO_DOWN, units.EXO_UP):
            for x_unit in (units.TEMP_C, units.TEMP_K):
                x, y = scan.curve(model.AXIS_TEMPERATURE, unit, exo, x_unit)
                for base, value in ((units.BASE_UNIT, watts[k]),
                                    (units.UNIT_W_G,
                                     watts[k] / sample.mass_g)):
                    px, py = scan.axes_points([[temperature[k], value]],
                                              base, unit, exo, x_unit)
                    assert px[0] == pytest.approx(x[k], abs=1e-12)
                    assert py[0] == pytest.approx(y[k], rel=1e-12)
    # a unit that needs a number the scan lacks: refused, never substituted
    sample.molar_mass = None
    assert scan.axes_points([[temperature[k], watts[k]]], units.BASE_UNIT,
                            units.UNIT_W_MOL, units.EXO_DOWN) == (None, None)


# ------------------------------------------------------------- the window
@pytest.fixture
def window(qapp, sample):
    """test_window's: both segments of the conftest sample on the plot."""
    from dscpanel.ui.window import MainWindow
    win = MainWindow()
    win.resize(900, 560)
    win._sample_loaded(sample)
    win.toggle_segment(sample, 1, True)
    win.undo.clear()
    return win


@pytest.fixture
def step_window(qapp):
    """A window with the step data's heating scan."""
    from dscpanel.ui.window import MainWindow
    win = MainWindow()
    win.resize(900, 560)
    win._sample_loaded(model.Sample("C:/nowhere/STEP-1.tri", _step_data()))
    win.undo.clear()
    return win


def _trace(window, scan):
    window.refresh()
    window.plot.grab()
    return [t for t in window.plot.traces if t.scan is scan][0]


def _distance(a, b):
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def _centres(dashes):
    return [QPointF(d[0].x(), (d[0].y() + d[1].y()) / 2.0) for d in dashes]


def test_an_onset_is_drawn_from_its_dashes_to_its_point(step_window):
    """A to B to C: from the dash at each bound, ON the trace, to the point
    its construction puts the onset at - where the tangents cross, which
    may lie off the curve, as TRIOS draws it - and the label's arrow
    points there too (Christian: "keep that, as long as A and C are drawn
    on the trace"). The tangents drawn before ran from their own end
    points, not the dashes."""
    window = step_window
    scan = window.doc.scans[0]
    onset = measure.run("Onset point", scan, 110.0, 170.0)
    trace = _trace(window, scan)
    plot = window.plot
    rect = plot.plot_rect()
    dashes, lines = plot.interval_marks(trace, onset, rect)
    assert len(dashes) == 2 and len(lines) == 2
    a, c = _centres(dashes)
    (a0, b0), (b1, c1) = lines
    assert _distance(a0, a) < 1e-6 and _distance(c1, c) < 1e-6
    assert _distance(b0, b1) < 1e-9
    (crossing,) = plot.construction_points(trace, onset, rect)
    assert _distance(b0, crossing) < 1e-9
    assert b0.x() == pytest.approx(
        plot.x_to_px(plot.to_axis(onset.value()), rect), abs=0.01)
    place = plot._label_place(trace, onset, rect)
    assert place[5] == pytest.approx(b0.y())          # the arrow's tip


def test_without_a_construction_the_point_is_on_the_curve(window):
    """A `.txt` export stores no tangents: its point is the curve's."""
    scan = window.doc.scans[0]
    scan._analyses = None
    scan.sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C #1": {"Onset point": [{
            "segment": 1, "Onset cursor x": "60.0000 \u00b0C",
            "Transition cursor x": "120.0000 \u00b0C",
            "Onset x": "95.0000 \u00b0C"}]}}
    (onset,) = scan.analysis_objects
    onset.visible = True
    trace = _trace(window, scan)
    plot = window.plot
    rect = plot.plot_rect()
    assert plot.construction_points(trace, onset, rect) is None
    lines = plot.interval_marks(trace, onset, rect)[1]
    x = plot.to_axis(onset.value())
    assert lines[0][1].x() == pytest.approx(plot.x_to_px(x, rect))
    assert lines[0][1].y() == pytest.approx(plot._curve_y_at(trace, x, rect))
    assert plot._label_place(trace, onset, rect)[5] == pytest.approx(
        lines[0][1].y())


def _file_tg(window):
    """A stored glass transition with TRIOS's four points, on the first
    scan of the conftest sample."""
    scan = window.doc.scans[0]
    scan._analyses = None
    scan.sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C #1": {"Glass transition": [{
            "segment": 1, "Onset cursor x": "100.0000 \u00b0C",
            "End cursor x": "180.0000 \u00b0C",
            "Onset x": "130.0000 \u00b0C", "End x": "150.0000 \u00b0C",
            "Midpoint": "140.0000 \u00b0C",
            "variable": "Heat Flow (Normalized)",
            "construction": [[100.0, -0.52], [130.0, -0.50],
                             [150.0, -0.40], [180.0, -0.39]]}]}}
    (tg,) = scan.analysis_objects
    tg.visible = True
    return scan, tg


def test_a_glass_transition_is_drawn_through_its_onset_and_end(window):
    """From the dashes to TRIOS's two crossings - its onset and its end -
    and between them along the inflection tangent; its arrow points at
    the midpoint, on the curve."""
    scan, tg = _file_tg(window)
    trace = _trace(window, scan)
    plot = window.plot
    rect = plot.plot_rect()
    dashes, lines = plot.interval_marks(trace, tg, rect)
    assert len(dashes) == 2 and len(lines) == 3
    a, c = _centres(dashes)
    assert _distance(lines[0][0], a) < 1e-6 and _distance(lines[2][1], c) < 1e-6
    for point, key in ((lines[0][1], "Onset x"), (lines[1][1], "End x")):
        assert plot.px_to_x(point.x(), rect) == pytest.approx(
            model.number(tg.fields[key]), abs=1e-6)
    midpoint = plot.to_axis(tg.value())
    assert plot._label_place(trace, tg, rect)[5] == pytest.approx(
        plot._curve_y_at(trace, midpoint, rect))


def test_the_reference_runs_lines_meet_at_trioss_numbers(qapp):
    """The real thing: the DSC reference run's endset (first heating) and its
    Tg (the 50 K/min heating, given an offset): their lines meet at the
    numbers TRIOS reported - in W/g and in mW."""
    path = local_file(DSC_REFERENCE)
    if path is None:
        pytest.skip("the DSC reference run is not on this machine")
    from dscpanel.ui.window import MainWindow
    sample = model.Sample(path, trios_io.read_tri(path))
    win = MainWindow()
    win.resize(1000, 700)
    win._sample_loaded(sample)
    win.toggle_segment(sample, 6, True)
    scans = {s.seg: s for s in win.doc.scans}
    scans[6].offset = 0.6
    wanted = {(0, "Endset point"): ("Endset x",),
              (6, "Glass transition"): ("Onset x", "End x")}
    for unit in (units.UNIT_W_G, units.UNIT_MW):
        if win.doc.y_unit != unit:
            win.set_unit(unit)
        for (seg, name), keys in wanted.items():
            scan = scans[seg]
            (analysis,) = [a for a in scan.analysis_objects
                           if a.model_name == name]
            analysis.visible = True
            trace = _trace(win, scan)
            plot = win.plot
            rect = plot.plot_rect()
            lines = plot.interval_marks(trace, analysis, rect)[1]
            assert len(lines) == len(keys) + 1
            for k, key in enumerate(keys):
                assert plot.px_to_x(lines[k][1].x(), rect) == pytest.approx(
                    model.number(analysis.fields[key]), abs=1e-3)


def test_the_lines_and_the_dashes_are_separate_choices(window):
    from dscpanel.ui import plot as plot_module
    scan, tg = _file_tg(window)
    trace = _trace(window, scan)
    plot = window.plot
    rect = plot.plot_rect()
    dashes, lines = plot.interval_marks(trace, tg, rect)
    assert len(lines) == 3 and lines[0][1] == lines[1][0]
    # the lines end where the dashes sit, on the curve
    assert lines[0][0].x() == pytest.approx(dashes[0][0].x())
    tg.construction = style.LINES_NONE
    none = plot.interval_marks(trace, tg, rect)
    assert none[1] == [] and none[0] == dashes  # the dashes do not change
    # the house style decides for an analysis that chose nothing ...
    tg.construction = None
    window.doc.style.analysis_construction = style.LINES_NONE
    assert plot.interval_marks(trace, tg, rect)[1] == []
    # ... and an analysis's own choice wins
    tg.construction = style.LINES_CHORDS
    assert len(plot.interval_marks(trace, tg, rect)[1]) == 3
    # one that asked for tangents, as was possible, gets the same lines
    tg.construction = style.LINES_TANGENTS
    assert plot.interval_marks(trace, tg, rect)[1] == lines

    drawn = []

    class Painter(object):
        def setPen(self, pen):
            drawn.append(("pen", pen.color().name(), pen.style()))

        def drawLine(self, *args):
            drawn.append(("line",))

    # "Show interval markers" off: the lines are still drawn, the dashes not
    tg.show_interval = False
    tg.selected = True                       # and never orange
    plot._paint_interval(Painter(), rect, trace, tg)
    assert [d for d in drawn if d[0] == "line"] == [("line",)] * 3
    pens = [d for d in drawn if d[0] == "pen"]
    assert pens and all(name == plot_module._AXIS.name()
                        for _k, name, _s in pens)
    from PySide6.QtCore import Qt
    assert all(kind == Qt.SolidLine for _k, _n, kind in pens)
    drawn[:] = []
    tg.construction = style.LINES_NONE
    plot._paint_interval(Painter(), rect, trace, tg)
    assert drawn == []


def test_a_zoomed_svg_export_keeps_the_lines_inside_the_clip(
        step_window, tmp_path, monkeypatch):
    """Qt's SVG writer ignores clipping, so an onset's lines are painted
    inside the axes' fence (`_clip_mark`) and cut to the box: zoomed in,
    they run off the view and must not reach the margins."""
    window = step_window
    scan = window.doc.scans[0]
    onset = measure.run("Onset point", scan, 110.0, 170.0)
    trace = _trace(window, scan)
    plot = window.plot
    plot.set_view_x(128.0, 136.0)                    # the point, close up
    state = {"open": False, "calls": []}
    real_mark, real_interval = plot._clip_mark, plot._paint_interval

    def mark(p, rect, opening):
        state["open"] = opening
        return real_mark(p, rect, opening)

    class Recorder(object):
        def __init__(self, painter):
            self.painter, self.lines = painter, []

        def setPen(self, pen):
            self.painter.setPen(pen)

        def drawLine(self, a, b):
            self.lines.append((QPointF(a), QPointF(b)))
            self.painter.drawLine(a, b)

    def interval(p, rect, trace_, analysis):
        recorder = Recorder(p)
        uncut = plot.interval_marks(trace_, analysis, rect)[1]
        real_interval(recorder, rect, trace_, analysis)
        state["calls"].append((state["open"], p.hasClipping(), rect,
                               uncut, recorder.lines))

    monkeypatch.setattr(plot, "_clip_mark", mark)
    monkeypatch.setattr(plot, "_paint_interval", interval)
    path = window.export_image(str(tmp_path / "zoomed.svg"), light=True)
    assert state["calls"]
    for fenced, clipped, rect, uncut, painted in state["calls"]:
        assert fenced and clipped
        box = rect.adjusted(-1e-6, -1e-6, 1e-6, 1e-6)
        assert painted and all(box.contains(a) and box.contains(b)
                               for a, b in painted)
        # the view really does cut them
        assert any(not box.contains(a) or not box.contains(b)
                   for a, b in uncut)
    text = open(path, encoding="utf-8").read()
    assert "<clipPath" in text
    assert onset.visible and trace is not None


def test_lines_in_the_settings_mirror_a_group_in_one_undo_step(window):
    scan = window.doc.scans[0]
    scan._analyses = None
    scan.sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C #1": {"Onset point": [
            {"segment": 1, "Onset x": "90,0 \u00b0C",
             "Onset cursor x": "70,0 \u00b0C",
             "Transition cursor x": "110,0 \u00b0C"},
            {"segment": 1, "Onset x": "150,0 \u00b0C",
             "Onset cursor x": "130,0 \u00b0C",
             "Transition cursor x": "170,0 \u00b0C"}]}}
    first, second = scan.analysis_objects[:2]
    first.visible = second.visible = True
    second.construction = style.LINES_NONE          # its own, before
    first.label_size = 14.0                         # a field left alone
    window.refresh()
    window.plot.grab()
    window.doc.select_only([first, second])
    window.edit_object(first)
    dialog = window._dialogs[-1]
    assert dialog.group == [second]
    assert dialog.lines.isEnabled()
    dialog.lines.set_value(style.LINES_CHORDS)
    assert first.construction == second.construction == style.LINES_CHORDS
    assert first.label_size == 14.0 and second.label_size is None
    dialog.accept()
    window.undo.undo()                              # ONE step for both
    assert first.construction is None
    assert second.construction == style.LINES_NONE


def test_the_settings_offer_lines_only_where_there_are_some(window):
    """An integration has no lines; an onset has, to its point."""
    from dscpanel.ui.dialogs import AnalysisSettings
    scan = window.doc.scans[0]
    integral = measure.run("Peak Integration (enthalpy)", scan, 70.0, 150.0)
    dialog = AnalysisSettings(window, integral)
    assert not dialog.lines.isEnabled()
    dialog.close()
    scan._analyses = None
    scan.sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C #1": {"Onset point": [{
            "segment": 1, "Onset cursor x": "60.0000 \u00b0C",
            "Transition cursor x": "120.0000 \u00b0C",
            "Onset x": "95.0000 \u00b0C"}]}}
    (onset,) = scan.analysis_objects
    dialog = AnalysisSettings(window, onset)
    assert dialog.lines.isEnabled()
    assert "to the point" in dialog.lines.combo.itemText(0)  # the default's
    dialog.lines.set_value(style.LINES_NONE)
    assert onset.construction == style.LINES_NONE
    dialog.close()


def test_the_render_cache_follows_the_lines(window):
    scan = window.doc.scans[0]
    onset = measure.run("Onset point", scan, 60.0, 120.0)
    window.refresh()
    plot = window.plot
    before = plot._key()
    onset.construction = style.LINES_NONE
    assert plot._key() != before
    before = plot._key()
    onset.show_interval = False
    assert plot._key() != before
    before = plot._key()
    window.doc.style.analysis_construction = style.LINES_NONE
    assert plot._key() != before


def test_the_settings_page_lists_the_lines(window):
    from dscpanel.ui.settings import SettingsDialog
    page = SettingsDialog(window)
    assert page.default_value("analysis_construction") == \
        style.LINES_CHORDS
    assert "tangent_overshoot" not in style.BY_KEY
    combo = page.defaults["analysis_construction"].combo
    assert [combo.itemText(i) for i in range(combo.count())] == [
        style.LINES_TITLES[c] for c in style.LINES]
    page.set_default("analysis_construction", style.LINES_NONE)
    assert style.preference("analysis_construction") == style.LINES_NONE
    page.revert()
    assert style.preference("analysis_construction") == style.LINES_CHORDS
    # a default of "tangents", saved before, is the lines to the point
    assert style.BY_KEY["analysis_construction"].clean(
        style.LINES_TANGENTS) is None


# ------------------------------------------------------------ the session
def _reopen(doc, sample, tmp_path, edit=None):
    import json
    path = tmp_path / "lines.dscpanel"
    session.save(doc, str(path))
    if edit is not None:
        state = json.loads(path.read_text(encoding="utf-8"))
        edit(state)
        path.write_text(json.dumps(state), encoding="utf-8")
    reopened, problems = session.load(
        str(path), lambda _p: model.Sample(sample.path, sample.data))
    assert not problems
    return reopened


def test_the_lines_survive_a_session(document, sample, tmp_path):
    scan = document.scans[0]
    made = measure.run("Onset point", scan, 60.0, 120.0)
    made.construction = style.LINES_CHORDS
    endset = measure.run("Endset point", scan, 60.0, 120.0)
    endset.construction = style.LINES_TANGENTS
    reopened = _reopen(document, sample, tmp_path)
    by_model = {a.model_name: a for a in reopened.scans[0].analysis_objects}
    assert by_model["Onset point"].construction == style.LINES_CHORDS
    # "tangents", saved before, follows the figure: lines to the point
    assert by_model["Endset point"].construction is None
    # a panel endset is measured again on load: flat side by acquisition
    # order, so a session saved with the old endset reopens corrected
    assert by_model["Endset point"].value() != by_model["Onset point"].value()

    def bad(state):
        for saved in state["scans"][0]["analyses"]:
            saved["construction"] = "dotted"

    reopened = _reopen(document, sample, tmp_path, bad)
    assert all(a.construction is None
               for a in reopened.scans[0].analysis_objects)


def test_an_older_session_without_markers_opens_without_lines(
        document, sample, tmp_path):
    """"Show interval markers" was once the dashes AND the
    lines. A session from then with it off had no lines, and keeps none;
    with it on the lines follow the house style."""
    scan = document.scans[0]
    off = measure.run("Onset point", scan, 60.0, 120.0)
    off.show_interval = False
    on = measure.run("Glass transition", scan, 60.0, 180.0)
    assert on is not None

    def old(state):
        for saved in state["scans"][0]["analyses"]:
            saved.pop("construction", None)

    reopened = _reopen(document, sample, tmp_path, old)
    by_model = {a.model_name: a for a in reopened.scans[0].analysis_objects}
    assert by_model["Onset point"].construction == style.LINES_NONE
    assert not by_model["Onset point"].show_interval
    assert by_model["Glass transition"].construction is None


def test_a_file_analysiss_lines_are_styling_like_the_rest(tmp_path):
    data = make_data()
    data["analyses"] = {"Ramp 10,00 C/min to 250 C #1": {"Onset point": [
        {"segment": 1, "Onset cursor x": "60.0000 \u00b0C",
         "Transition cursor x": "120.0000 \u00b0C",
         "Onset x": "95.0000 \u00b0C"}]}}
    sample = model.Sample("C:/nowhere/TEST-1.tri", data)
    doc = model.Document()
    doc.add_sample(sample)
    (analysis,) = doc.scans[0].analysis_objects
    analysis.construction = style.LINES_NONE
    reopened = _reopen(doc, sample, tmp_path)
    (again,) = reopened.scans[0].analysis_objects
    assert again.construction == style.LINES_NONE
