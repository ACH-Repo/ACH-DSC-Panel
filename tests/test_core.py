"""The parts that have no window: units, the model, arranging, undo, sessions."""

import numpy as np
import pytest

from dscpanel.core import arrange, model, session, undo, units


# ------------------------------------------------------------------- units
def test_per_mole_needs_a_molar_mass():
    factor, missing = units.factor(units.UNIT_W_MOL, mass_g=0.008,
                                   molar_mass=None)
    assert factor is None and missing == "molar mass"
    factor, missing = units.factor(units.UNIT_W_MOL, mass_g=0.008,
                                   molar_mass=150.0)
    assert missing is None
    # W/g times g/mol
    assert factor == pytest.approx(150.0 / 0.008)


def test_no_unit_invents_a_mass():
    assert units.missing(units.UNIT_W_G, mass_g=None) == "sample mass"
    assert units.missing(units.UNIT_MW) is None


def test_exo_and_endo_name_the_same_picture():
    assert units.orientation("exo", "down") == units.EXO_DOWN
    assert units.orientation("endo", "up") == units.EXO_DOWN
    assert units.orientation("exo", "up") == units.EXO_UP
    assert units.orientation("endo", "down") == units.EXO_UP


def test_offsets_follow_a_change_of_unit(document):
    scan = document.scans[0]
    scan.offset = 0.5                      # W/g
    changes = document.set_unit(units.UNIT_MW)
    assert changes and changes[0][2] == pytest.approx(0.5 * 1000.0 * 0.008)


# ------------------------------------------------------------------- model
def test_number_reads_german_decimals_and_units():
    assert model.number("58,4977 °C") == pytest.approx(58.4977)
    assert model.number("13.2611 J/g") == pytest.approx(13.2611)
    assert model.number(None) is None


def test_direction_survives_the_dip_at_the_start(document):
    assert document.scans[0].direction() == "up"
    assert document.scans[1].direction() == "down"
    assert "heat" in document.scans[0].short_program()
    assert "cool" in document.scans[1].short_program()


def test_curve_is_not_normalised(document):
    scan = document.scans[0]
    _x, y = scan.curve(document.x_axis, units.UNIT_W_G, units.EXO_DOWN)
    watts = scan.heat_flow_w()
    assert np.allclose(y, watts / scan.sample.mass_g)
    # ...and emphatically not scaled to its own extremum
    assert abs(float(np.max(np.abs(y))) - 1.0) > 0.1


def test_exo_flip_is_a_sign_flip(document):
    scan = document.scans[0]
    _x, down = scan.curve(document.x_axis, units.UNIT_W_G, units.EXO_DOWN)
    _x, up = scan.curve(document.x_axis, units.UNIT_W_G, units.EXO_UP)
    assert np.allclose(down, -up)


def test_a_scan_without_m_reports_instead_of_guessing(document):
    scan = document.scans[0]
    x, y = scan.curve(document.x_axis, units.UNIT_W_MOL, units.EXO_DOWN)
    assert x is None and y is None
    assert scan.missing_for(units.UNIT_W_MOL) == "molar mass"
    scan.sample.molar_mass = 150.0
    x, _y = scan.curve(document.x_axis, units.UNIT_W_MOL, units.EXO_DOWN)
    assert x is not None


def test_analyses_segment_numbers_are_one_based(sample):
    """The reader writes `segment = j + 1`. Reading it as 0-based draws every
    onset one scan down, which is how this was found."""
    sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C #1": {
            "Onset point": [{"segment": 1, "Onset x": "61,08 °C"}]}}
    assert len(sample.analyses_for(0)) == 1
    assert sample.analyses_for(1) == []


def test_text_export_analyses_are_matched_by_step_name(sample):
    sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C": {
            "Onset point": [{"Onset x": "61,08 °C"}]}}
    first = sample.analyses_for(0)
    assert len(first) == 1 and first[0]["attribution"] == "by step name"
    assert sample.analyses_for(1) == []


# --------------------------------------------------------------- arranging
def test_align_puts_curves_on_top_of_one_another(document):
    a, b = document.scans[0], document.scans[1]
    b.offset = 3.0

    def curve_of(scan):
        return scan.curve(document.x_axis, document.y_unit, document.exo)

    changes = arrange.align_to(a, [b], curve_of)
    assert changes
    b.offset = changes[0][2]
    _x, ya = curve_of(a)
    _x, yb = curve_of(b)
    assert abs(float(np.mean(ya)) - float(np.mean(yb))) < 0.5


def test_distribute_keeps_the_ends_and_evens_the_middle():
    class Fake(object):
        def __init__(self, offset):
            self.offset = offset
    scans = [Fake(0.0), Fake(0.3), Fake(3.0)]
    changes = arrange.distribute(scans)
    assert changes == [(scans[1], "offset", pytest.approx(1.5))]


# --------------------------------------------------------------------- undo
def test_a_drag_is_one_undo_step(document):
    stack = undo.UndoStack()
    scan = document.scans[0]
    stack.begin()
    for value in (0.1, 0.2, 0.3):
        stack.set_props([(scan, "offset", value)], "move")
    stack.seal()
    assert stack.depth() == 1
    assert scan.offset == pytest.approx(0.3)
    stack.undo()
    assert scan.offset == 0.0


def test_two_different_actions_are_two_steps(document):
    stack = undo.UndoStack()
    scan = document.scans[0]
    stack.set_props([(scan, "offset", 1.0)], "move")
    stack.set_props([(scan, "colour", "#ff0000")], "colour")
    assert stack.depth() == 2
    stack.undo()
    assert scan.colour != "#ff0000" and scan.offset == pytest.approx(1.0)


# ------------------------------------------------------------------ session
def test_session_round_trip(document, tmp_path, sample):
    document.scans[0].offset = 1.25
    document.scans[0].label = "the good one"
    document.samples[0].molar_mass = 150.2
    document.arrow.word = units.WORD_ENDO
    document.arrow.direction = units.EXO_UP
    path = tmp_path / "figure.dscpanel"
    session.save(document, str(path))

    def read_sample(_path):
        return model.Sample(sample.path, sample.data)

    reopened, problems = session.load(str(path), read_sample)
    assert not problems
    assert len(reopened.scans) == len(document.scans)
    assert reopened.scans[0].offset == pytest.approx(1.25)
    assert reopened.scans[0].label == "the good one"
    assert reopened.samples[0].molar_mass == pytest.approx(150.2)
    assert reopened.exo == units.EXO_DOWN      # endo up is exo down
