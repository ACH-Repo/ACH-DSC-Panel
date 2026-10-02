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
    assert model.number("58,4977 \u00b0C") == pytest.approx(58.4977)
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
            "Onset point": [{"segment": 1, "Onset x": "61,08 \u00b0C"}]}}
    assert len(sample.analyses_for(0)) == 1
    assert sample.analyses_for(1) == []


def test_text_export_analyses_are_matched_by_step_name(sample):
    sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C": {
            "Onset point": [{"Onset x": "61,08 \u00b0C"}]}}
    first = sample.analyses_for(0)
    assert len(first) == 1 and first[0]["attribution"] == "by step name"
    assert sample.analyses_for(1) == []


def test_trios_construction_is_kept_out_of_the_text_fields(document):
    """The reader hands a `.tri`'s onset its construction as a list of
    [x, y] floats. `fields` are text, listed as results: the list there
    showed up as a result called "construction", worth its first number."""
    from dscpanel.core import labels
    sample = document.samples[0]
    points = [[53.4029, 0.21003], [61.0851, 0.22756], [68.0461, 0.27806]]
    sample.data["analyses"] = {
        "Ramp 10,00 C/min to 250 C #1": {
            "Onset point": [{"segment": 1, "Onset cursor x": "53.4029 \u00b0C",
                             "Transition cursor x": "68.0859 \u00b0C",
                             "Onset x": "61.0851 \u00b0C",
                             "variable": "Heat Flow (Normalized)",
                             "construction": points}]}}
    scan = document.scans[0]
    scan._analyses = None
    (analysis,) = scan.analysis_objects
    assert analysis.stored_construction == points
    assert "construction" not in analysis.fields
    assert [name for name, _text in labels.results(analysis)] == ["Onset"]
    assert analysis.key() == "Onset point|53.4029|68.0859"
    # and the reader's own record is left alone
    assert "construction" in sample.data["analyses"][
        "Ramp 10,00 C/min to 250 C #1"]["Onset point"][0]


def _nan_data():
    """Two segments; the second with the reader's flagged samples: NaN at
    its START (some runs flag the first samples of segment 1 too), in the
    middle, and a tail where the temperature ends 5 samples and the heat
    flow 12 before the end - the DSC25 pattern (5 and 35)."""
    from conftest import make_data
    data = make_data(points=60)
    nums = data["numdata"][1]["nums"]
    nums[:3, 1] = np.nan
    nums[20, 2] = np.nan
    nums[-5:, 1] = np.nan
    nums[-12:, 2] = np.nan
    return data


def test_only_the_flagged_tail_is_trimmed():
    """The tail where temperature OR heat flow is NaN goes; the start and a
    gap in the middle stay, so every sample keeps its index counted from the
    segment's start (a session stores sample spans). An older reader
    trimmed the start too, and by the temperature only."""
    data = _nan_data()
    before = data["numdata"][1]["nums"].copy()
    model.Sample("C:/nowhere/TEST-1.tri", data)
    after = data["numdata"][1]["nums"]
    assert len(after) == 60 - 12
    assert np.array_equal(after, before[:48], equal_nan=True)
    assert np.isnan(after[:3, 1]).all() and np.isnan(after[20, 2])
    assert len(data["numdata"][0]["nums"]) == 60      # nothing to trim


def test_a_flagged_first_sample_does_not_turn_a_heating_into_a_cooling():
    """A heating ramp whose first samples are flagged (NaN) was called
    "cool": the direction compared the last temperature with a NaN. The
    default scan (the first up-scan) and an isothermal's label ("iso nan
    degC") had the same trap."""
    from conftest import make_data
    data = make_data(segments=4, points=60)
    first = data["numdata"][0]["nums"]
    first[:, 1] = first[::-1, 1].copy()             # segment 1 cools
    data["numdata"][2]["nums"][:4, 1] = np.nan      # segment 3 heats
    iso = data["numdata"][3]
    iso["prog"] = "Isothermal 1,0 min #4"
    iso["nums"][:, 1] = 100.0
    iso["nums"][:4, 1] = np.nan
    sample = model.Sample("C:/nowhere/TEST-1.tri", data)
    assert model.first_upscan(sample) == 2
    heating = model.Scan(1, sample, 2, "#000000")
    assert heating.direction() == "up"
    assert heating.short_program().split()[1] == "heat"
    assert model.Scan(2, sample, 3, "#000000").short_program() == \
        "#4 iso 100 \u00b0C"


def test_the_note_line_says_a_mass_was_derived():
    """An SDT run has no sample-size field; a mass read off Weight / Weight
    Change is an inference, and the note line says so."""
    from conftest import make_data
    from dscpanel.core import loader
    data = make_data()
    data["head"].pop("samplesize")
    data["head"].update({"Sample Mass": "21.5473 mg",
                         "mass_source": "derived from the weight"})
    sample = model.Sample("C:/nowhere/TEST-1.tri", data)
    assert "21.5473 mg (derived from the weight)" in loader.summary(sample)
    data["head"]["mass_source"] = "recorded"
    sample = model.Sample("C:/nowhere/TEST-1.tri", data)
    assert "derived" not in loader.summary(sample)


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
