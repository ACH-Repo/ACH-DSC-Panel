"""Against a REAL `.tri`, when one is on this machine.

Skipped when there is none, because measurements are not committed. What is
checked here cannot be checked against anything invented: that the segments
come out, that a stored analysis lands on the scan it was actually run on,
and that the exotherm direction is read from the file rather than assumed
when the file says so.
"""

import numpy as np
import pytest

from dscpanel.core import loader, model, units


@pytest.fixture(scope="module")
def sample(real_tri):
    return loader.read_sample(real_tri)


def test_a_real_file_opens_with_its_segments(sample):
    assert sample.segment_count() >= 1
    assert sample.mass_g, "a DSC file states its sample mass"
    doc = model.Document()
    doc.add_sample(sample)
    for scan in doc.scans:
        x, y = scan.curve(doc.x_axis, units.UNIT_W_G, doc.exo)
        assert x is not None and len(x) == len(y)
        assert scan.direction() in ("up", "down", "iso")


def test_temperature_really_is_not_monotonic(sample):
    """The reason this program cannot use `searchsorted`. If a file ever
    comes along whose segments ARE monotonic, this test says so rather than
    the assumption quietly going unexercised."""
    reversals = 0
    doc = model.Document()
    doc.add_sample(sample)
    for scan in doc.scans:
        temp = scan.temperature()
        steps = np.diff(temp)
        signs = np.sign(steps[np.abs(steps) > 1e-6])
        if len(signs) > 1:
            reversals += int(np.sum(signs[1:] != signs[:-1]))
    assert reversals > 0


def test_a_stored_integration_sits_on_the_scan_it_was_run_on(sample):
    """The 1-based `segment` trap, checked by arithmetic rather than by
    reading the index: integrate between the stored cursors on the scan the
    analysis was attributed to, and the result has to be the enthalpy TRIOS
    recorded. On the wrong segment it is not.
    """
    doc = model.Document()
    doc.add_sample(sample)
    checked = 0
    for scan in doc.scans:
        for entry in scan.analyses():
            if "Integration" not in str(entry.get("Model", "")):
                continue
            stored = model.number(entry.get("Enthalpy (normalized)"))
            x0 = model.number(entry.get("Baseline cursor x"))
            x1 = model.number(entry.get("Baseline cursor x1"))
            if stored is None or x0 is None or x1 is None:
                continue
            temp = scan.temperature()
            seconds = scan.time_min() * 60.0
            watts = scan.heat_flow_w() / scan.sample.mass_g
            lo, hi = sorted((x0, x1))
            window = (temp >= lo) & (temp <= hi)
            if window.sum() < 10:
                continue
            t, q = seconds[window], watts[window]
            base = np.interp(t, [t[0], t[-1]], [q[0], q[-1]])
            area = abs(float(np.trapz(q - base, t)))
            # A straight line between the endpoints is not exactly TRIOS's
            # baseline, so this is a generous tolerance. It is still far
            # tighter than the factor of two a neighbouring segment gives.
            assert area == pytest.approx(stored, rel=0.25), (
                "{}: {:.2f} J/g here, {:.2f} J/g stored".format(
                    scan.short_program(), area, stored))
            checked += 1
    if not checked:
        pytest.skip("this file holds no decoded peak integration")


def test_the_exotherm_direction_comes_from_the_file_when_it_can(real_tri):
    direction, source = loader.detect_exotherm(real_tri)
    assert direction in (units.EXO_DOWN, units.EXO_UP)
    assert source in ("audit trail", "export header", "assumed")
