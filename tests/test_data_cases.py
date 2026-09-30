"""Three real files, and what each proved.

Every test here is a fact about a real file, so they skip when the file is
not there. Between them they pin the three things that were guesses
until those files existed: which way exotherms point, what a glass-transition
record holds, and what happens to a segment the instrument recorded without a
heat flow - which the indium ramp turned out not to be (its heat flow is
stored with a flags list), so that last one is pinned on the
reader's shape now, and the ramp's own melt beside it.
"""

import os

import numpy as np
import pytest

from dscpanel.core import export, loader, measure, model, units

from conftest import local_file, make_data

# By a hash of the file name only (`conftest.hashed_name`). Where each one
# lives is listed in the uncommitted tests/local_testdata.txt (see
# `conftest.local_file`).
#: The indium calibration run.
INDIUM = "sha:2af8730daad0"
#: A TRIOS 6.0 DSC25 run with its own .txt export beside it: the pair the
#: reader is validated against.
DSC_PAIR = "sha:9f0ad8af1175"
DSC_PAIR_TXT = "sha:f2c2ed49c3ab"      # its export
#: The DSC25 reference run: TRIOS 5.1.1, seven segments, 16 stored
#: analyses, a Full .txt export beside it.
DSC_REFERENCE = "sha:b2303c243b22"


def _path(name):
    path = local_file(name)
    if path is None:
        pytest.skip("{} is not on this machine".format(name))
    return path


def _sample(name):
    return loader.read_sample(_path(name))


# ------------------------------------------------------- the indium run
def test_indium_states_its_exotherm_direction():
    sample = _sample(INDIUM)
    assert sample.exo == units.EXO_DOWN
    assert sample.exo_source == "audit trail"


def test_indium_proves_the_sign_from_the_raw_sensors():
    """The melt is endothermic, so which way it points settles the
    convention for every file from this instrument.

    Heat Flow is a negative multiple of Delta T (correlation -1.000 on the
    isothermal segment of this very file), and the melt is a NEGATIVE
    excursion in Delta T, so it is an UPWARD one in heat flow: endo up, exo
    down.
    """
    sample = _sample(INDIUM)
    doc = model.Document()
    doc.add_sample(sample)
    iso, ramp = doc.scans[0], doc.scans[1]
    heat_flow = iso._column("Heat Flow")
    delta_t = iso._column("Delta T")
    slope = float(np.polyfit(delta_t, heat_flow, 1)[0])
    assert slope < 0
    assert float(np.corrcoef(delta_t, heat_flow)[0, 1]) < -0.99

    t0 = ramp._column("Tzero Temperature")
    dt = ramp._column("Delta T")
    window = (t0 > 140) & (t0 < 175)
    base = np.interp(t0[window], [t0[window][0], t0[window][-1]],
                     [dt[window][0], dt[window][-1]])
    excursion = dt[window] - base
    assert abs(excursion.min()) > abs(excursion.max())     # points down in dT
    # ...so upward in heat flow, and the melt is where indium melts.
    assert 150.0 < float(t0[window][int(excursion.argmin())]) < 170.0


def test_the_panel_points_at_the_export_when_a_segment_is_unusable(
        tmp_path):
    """A segment the instrument recorded without a heat flow: the export of
    the same run is the other place one can come from, so the note line
    says so rather than leaving somebody to wonder.

    The indium ramp was the real case until its heat flow turned out to be
    recorded in flagged arrays (TRI-FORMAT.md section 3, and the test
    below). No file tried lacks one now,
    so this is the reader's SHAPE with the column taken out, and an export
    file of the same name beside it."""
    data = make_data()
    step = data["numdata"][1]
    step["dims"], step["units"] = step["dims"][:2], step["units"][:2]
    step["nums"] = step["nums"][:, :2]
    path = tmp_path / "TEST-1.tri"
    (tmp_path / "test-1.txt").write_text("Filename\tTEST-1\n")
    sample = model.Sample(str(path), data)
    assert loader.segments_without_heat_flow(sample) == [2]
    assert loader.sibling_export(str(path)).lower().endswith("test-1.txt")
    assert "records no heat flow" in loader.summary(sample)
    assert "instead" in loader.summary(sample)
    doc = model.Document()
    doc.add_sample(sample)
    ramp = doc.scans[1]
    assert ramp.missing_for(doc.y_unit, doc.x_axis) == \
        "heat flow in this segment"
    assert ramp.curve(doc.x_axis, doc.y_unit, doc.exo) == (None, None)
    assert any("NO HEAT FLOW" in line for line in export.warnings_for(doc))


def test_the_indium_export_gives_the_melt_too():
    """Opening the export draws both segments, and its melt comes out at
    indium's own enthalpy - which is also the third independent confirmation
    that these files are exo down."""
    path = loader.sibling_export(_path(INDIUM))
    if path is None or not os.path.isfile(path):
        pytest.skip("no .txt export beside the indium run")
    sample = loader.read_sample(path)
    doc = model.Document()
    doc.add_sample(sample)
    assert sample.mass_g == pytest.approx(0.0108)
    ramp = doc.scans[1]
    assert ramp.missing_for(doc.y_unit, doc.x_axis) is None
    temp = ramp.temperature()
    flow = ramp._column("Heat Flow (Normalized)")
    seconds = ramp.time_min() * 60.0
    window = (temp > 150) & (temp < 168)
    base = np.interp(seconds[window],
                     [seconds[window][0], seconds[window][-1]],
                     [flow[window][0], flow[window][-1]])
    deviation = flow[window] - base
    assert deviation.max() > abs(deviation.min())          # the melt points UP
    enthalpy = abs(float(np.trapz(deviation, seconds[window])))
    assert enthalpy == pytest.approx(28.5, rel=0.05)


def test_the_indium_ramp_is_recorded_and_melts_at_indiums_enthalpy():
    """The ramp was once read as "records no heat flow": its
    Temperature, Heat Flow, Heat Flow Phase and Total Heat Capacity are
    stored with a flags list (the last 5 / 35 samples flagged), which the
    reader did not read (TRI-FORMAT.md section 3). Read, the .tri alone
    draws the ramp and its melt integrates to indium's 28.5 J/g, pointing
    UP in the stored arrays - the recorded heat flow itself now proves exo
    down, without the Delta T argument above."""
    sample = _sample(INDIUM)
    assert loader.segments_without_heat_flow(sample) == []
    assert "records no heat flow" not in loader.summary(sample)
    doc = model.Document()
    doc.add_sample(sample)
    ramp = doc.scans[1]
    assert ramp.missing_for(doc.y_unit, doc.x_axis) is None
    x, y = ramp.curve(doc.x_axis, doc.y_unit, doc.exo)
    assert x is not None and np.all(np.isfinite(y))
    assert not any("NO HEAT FLOW" in line for line in export.warnings_for(doc))
    # 4801 recorded, the flagged tail of 35 trimmed off the END only
    assert len(ramp.temperature()) == 4766
    assert "heat" in ramp.short_program().lower()
    temp = ramp.temperature()
    flow = ramp._column("Heat Flow (Normalized)")
    seconds = ramp.time_min() * 60.0
    window = (temp > 150) & (temp < 168)
    base = np.interp(seconds[window],
                     [seconds[window][0], seconds[window][-1]],
                     [flow[window][0], flow[window][-1]])
    deviation = flow[window] - base
    assert deviation.max() > 100 * abs(deviation.min())    # the melt points UP
    assert 157.5 < float(temp[window][int(deviation.argmax())]) < 159.0
    enthalpy = abs(float(np.trapz(deviation, seconds[window])))
    assert enthalpy == pytest.approx(28.56, abs=0.01)
    # and the panel's own integration says the same
    fields = measure.compute("Peak Integration (enthalpy)", ramp, 150.0, 168.0)
    assert model.number(fields["Enthalpy (normalized)"]) == \
        pytest.approx(28.56, abs=0.01)


# ------------------------------------------------- the glass transition
def test_the_glass_transition_matches_trios():
    """Decoded from the DSC reference run, whose export says Midpoint
    78,911 degC.

    The record holds four (x, y) pairs; the midpoint is the half-height
    crossing between the middle two, not their mean (78.849, which is 0.06 K
    out and would look right).
    """
    sample = _sample(DSC_REFERENCE)
    doc = model.Document()
    doc.add_sample(sample)
    found = [a for scan in doc.scans for a in scan.analyses()
             if "Glass" in a["Model"]]
    assert len(found) == 1
    tg = found[0]
    assert model.number(tg["Onset cursor x"]) == pytest.approx(63.195, abs=5e-3)
    assert model.number(tg["End cursor x"]) == pytest.approx(101.457, abs=5e-3)
    assert model.number(tg["Midpoint"]) == pytest.approx(78.911, abs=5e-3)
    assert model.number(tg["Onset x"]) == pytest.approx(75.678, abs=5e-3)
    assert model.number(tg["End x"]) == pytest.approx(82.020, abs=5e-3)


def test_the_glass_transition_is_drawn():
    from dscpanel.ui.plot import _analysis_marker, _is_decoded
    entry = {"Model": "Glass transition", "Midpoint": "78.9109 \u00b0C"}
    assert _is_decoded(entry)
    label, value = _analysis_marker(entry)
    assert label.startswith("Tg") and value == pytest.approx(78.9109)


# ------------------------------------------- a .tri and its own export
def test_the_tri_and_its_export_agree():
    """Same run, both readers: the segments and the onsets have to match."""
    from_tri = _sample(DSC_PAIR)
    from_txt = _sample(DSC_PAIR_TXT)
    assert from_tri.segment_count() == from_txt.segment_count()
    for seg in range(from_tri.segment_count()):
        a = from_tri.data["numdata"][seg]["nums"]
        b = from_txt.data["numdata"][seg]["nums"]
        rows = min(len(a), len(b))
        # The last segment is the partial one: TRIOS exports the 2605 rows it
        # displays and the reader keeps all 2640 it recorded, so the overlap
        # is what can be compared.
        ai = from_tri.data["numdata"][seg]["dims"].index("Temperature")
        bi = from_txt.data["numdata"][seg]["dims"].index("Temperature")
        assert np.allclose(a[:rows, ai], b[:rows, bi], atol=5e-4)
    tri_onsets = sorted(model.number(a["Onset x"])
                        for scan_seg in range(from_tri.segment_count())
                        for a in from_tri.analyses_for(scan_seg)
                        if a["Model"] == "Onset point")
    txt_onsets = sorted(model.number(a["Onset x"])
                        for models in from_txt.data["analyses"].values()
                        for a in models.get("Onset point", []))
    assert len(tri_onsets) == 3
    assert tri_onsets == pytest.approx(txt_onsets, abs=1e-3)


def test_an_export_carries_its_mass_and_draws_in_every_unit():
    """A TRIOS export stores W/g and no watts, and puts the mass in
    [Procedure]. Both used to make it undrawable."""
    sample = _sample(DSC_PAIR_TXT)
    assert sample.mass_g == pytest.approx(0.0047)
    doc = model.Document()
    doc.add_sample(sample)
    scan = doc.scans[0]
    assert scan.heat_flow()[1] == units.UNIT_W_G
    for unit in (units.UNIT_MW, units.UNIT_W_G):
        assert scan.curve(doc.x_axis, unit, doc.exo)[1] is not None
    assert scan.missing_for(units.UNIT_W_MOL) == "molar mass"
    sample.molar_mass = 150.2
    scan._cache_key = None
    assert scan.curve(doc.x_axis, units.UNIT_W_MOL, doc.exo)[1] is not None


# ------------------------------------------- the driver, run for real
def test_the_exported_driver_runs_and_builds_the_same_figure(qapp, tmp_path):
    """Export the DSC_Plotter.py driver for a figure of exact size, RUN it
    with matplotlib, and measure its SVG: 8 x 6 cm, the axes box at the
    panel's margins. The old driver called functions the template never had
    and stopped at its second line - and no test ran it, which is how."""
    import re
    import subprocess
    import sys
    pytest.importorskip("achdsc")
    pytest.importorskip("matplotlib")
    from dscpanel.core import figure
    from dscpanel.ui.window import MainWindow
    path = _path(DSC_REFERENCE)
    win = MainWindow()
    win.resize(900, 560)
    win._sample_loaded(loader.read_sample(path))
    layout = win.doc.figure
    layout.mode, layout.unit = figure.MODE_SIZE, figure.UNIT_CM
    layout.width, layout.height = 8.0, 6.0
    layout.margin_left, layout.margin_right = 1.8, 0.4
    layout.margin_top, layout.margin_bottom = 0.4, 1.5
    win.doc.offset_markers = True      # the template's own call, run
    # the legend and a label with markup, run through matplotlib
    from PySide6.QtCore import QPointF
    win.doc.legend.visible = True
    win.doc.legend.line_width = 2.0
    label = win.add_label("\\Delta*H*_{m} and $x^2$", at=QPointF(200, 80))
    label.rotation = 15.0
    win.refresh()
    win.plot.grab()
    driver = win.export_driver(str(tmp_path / "DSC_Plotter.py"))
    with open(driver, encoding="utf-8") as fh:
        text = fh.read()
    if "def quickplot" not in text:
        pytest.skip("achdsc could not render a whole template here")
    text = text.replace("'silent':       False", "'silent':       True", 1)
    with open(driver, "w", encoding="utf-8") as fh:
        fh.write(text)
    run = subprocess.run([sys.executable, driver], cwd=str(tmp_path),
                         env=dict(os.environ, MPLBACKEND="Agg"),
                         capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr[-2000:]
    with open(str(tmp_path / "dsc.svg"), encoding="utf-8") as fh:
        svg = fh.read()
    pt = lambda cm: cm / 2.54 * 72.0
    size = dict(re.findall(r'(width|height)="([\d.]+)pt"',
                           re.search(r"<svg\b[^>]*>", svg).group(0)))
    assert float(size["width"]) == pytest.approx(pt(8.0), abs=1e-3)
    assert float(size["height"]) == pytest.approx(pt(6.0), abs=1e-3)
    box = re.search(r'<g id="patch_2">\s*<path d="M ([\d.]+) ([\d.]+)\s*'
                    r'L ([\d.]+) ([\d.]+)\s*L ([\d.]+) ([\d.]+)', svg)
    x0, y0, x1, _y1, _x2, y2 = map(float, box.groups())
    assert min(x0, x1) == pytest.approx(pt(1.8), abs=1e-3)
    assert max(x0, x1) == pytest.approx(pt(8.0 - 0.4), abs=1e-3)
    assert min(y0, y2) == pytest.approx(pt(0.4), abs=1e-3)
    assert max(y0, y2) == pytest.approx(pt(6.0 - 1.5), abs=1e-3)
