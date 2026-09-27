"""The three real files Christian supplied on 2026-09-23, and what each proved.

Every test here is a fact about a file on his machine, so they skip when the
file is not there. Between them they pin the three things that were guesses
until those files existed: which way exotherms point, what a glass-transition
record holds, and what happens to a segment the instrument recorded without a
heat flow.
"""

import os

import numpy as np
import pytest

from dscpanel.core import export, loader, model, units

from conftest import local_file

# By NAME only. Where each one lives is listed in the uncommitted
# tests/local_testdata.txt (see `conftest.local_file`).
INDIUM = "Indium-03082026(1).tri"
SES2_TRI = "SES-2-ag-16092026.tri"
SES2_TXT = "ses-2-ag-16092026.txt"
OJ12 = "OJ-12-DSC-2-07012026.tri"


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


def test_the_panel_points_at_the_export_when_a_segment_is_unusable():
    """The export of the same run has what the .tri segment does not, so the
    note line says so rather than leaving somebody to wonder."""
    sample = _sample(INDIUM)
    assert loader.segments_without_heat_flow(sample) == [2]
    export = loader.sibling_export(_path(INDIUM))
    if export is None:
        pytest.skip("no .txt export beside the indium run")
    assert os.path.basename(export).lower().endswith(".txt")
    assert "records no heat flow" in loader.summary(sample)
    assert "instead" in loader.summary(sample)


def test_the_indium_export_is_the_measurement_the_tri_cannot_give():
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


def test_a_segment_without_heat_flow_is_reported_not_dropped():
    """The ramp of this calibration run stores only the raw sensors, and the
    file has no Heat Flow T1 to fill it from. The panel must say so."""
    sample = _sample(INDIUM)
    doc = model.Document()
    doc.add_sample(sample)
    ramp = doc.scans[1]
    assert ramp.missing_for(doc.y_unit, doc.x_axis) == "heat flow in this segment"
    assert ramp.curve(doc.x_axis, doc.y_unit, doc.exo) == (None, None)
    assert any("NO HEAT FLOW" in line for line in export.warnings_for(doc))
    # and it is not called isothermal just because nothing measured it
    assert "ramp" in ramp.short_program().lower()


# ------------------------------------------------- the glass transition
def test_the_glass_transition_matches_trios():
    """Decoded 2026-09-23 from OJ-12, whose export says Midpoint 78,911 degC.

    The record holds four (x, y) pairs; the midpoint is the half-height
    crossing between the middle two, not their mean (78.849, which is 0.06 K
    out and would look right).
    """
    sample = _sample(OJ12)
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


# ------------------------------------------------------ the SES-2 pair
def test_the_tri_and_its_export_agree():
    """Same run, both readers: the segments and the onsets have to match."""
    from_tri = _sample(SES2_TRI)
    from_txt = _sample(SES2_TXT)
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
    sample = _sample(SES2_TXT)
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


# ------------------------------------- the driver, run for real (round 12)
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
    path = _path(OJ12)
    win = MainWindow()
    win.resize(900, 560)
    win._sample_loaded(loader.read_sample(path))
    layout = win.doc.figure
    layout.mode, layout.unit = figure.MODE_SIZE, figure.UNIT_CM
    layout.width, layout.height = 8.0, 6.0
    layout.margin_left, layout.margin_right = 1.8, 0.4
    layout.margin_top, layout.margin_bottom = 0.4, 1.5
    win.doc.offset_markers = True      # the template's own call, run
    # the legend and a label with markup, run through matplotlib (round 19)
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
