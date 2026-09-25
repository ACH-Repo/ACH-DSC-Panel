"""The house style: where a size comes from, and that it survives a restart.

UI-free, like `core/style.py` itself. Every test runs against its own
preferences file (the `own_preferences` fixture in conftest), so nothing here
can change how the person running the suite has their figures set up.
"""

import json

import pytest

from dscpanel.core import measure, model, session, style


def test_a_value_comes_from_the_object_then_the_figure_then_the_default():
    doc = model.Document()
    axis = doc.axes["x"]
    assert axis.tick_size is None                       # nothing chosen
    assert style.value(doc, axis, "tick_size") == 8.0   # the built-in value
    style.set_preference("tick_size", 11.0)
    assert style.value(doc, axis, "tick_size") == 11.0  # the user's default
    doc.style.tick_size = 7.0
    assert style.value(doc, axis, "tick_size") == 7.0   # this figure
    axis.tick_size = 14.0
    assert style.value(doc, axis, "tick_size") == 14.0  # this axis
    axis.tick_size = None
    doc.style.tick_size = None
    assert style.value(doc, axis, "tick_size") == 11.0


def test_every_styled_attribute_starts_unchosen():
    """None is "ask the house style". A number here would pin the object and
    the defaults would never reach it."""
    doc = model.Document()
    for (kind, attr), key in style.FIELDS.items():
        assert key in style.BY_KEY
    assert doc.legend.size is None
    assert doc.axes["y"].label_size is None
    assert doc.add_label("note").size is None


def test_the_defaults_survive_a_restart(own_preferences):
    style.set_preference("analysis_size", 7.5)
    style.set_preference("analysis_flush", style.FLUSH_RIGHT)
    assert style.save_preferences() == own_preferences
    style.restore_preferences({})
    assert style.preference("analysis_size") == 9.0
    style.load_preferences()
    assert style.preference("analysis_size") == 7.5
    assert style.preference("analysis_flush") == style.FLUSH_RIGHT


def test_a_default_set_back_to_the_builtin_is_forgotten():
    style.set_preference("legend_size", 12.0)
    style.set_preference("legend_size", 9.0)
    assert "legend_size" not in style.preferences()


def test_a_damaged_preferences_file_is_the_builtin_style(own_preferences):
    with open(own_preferences, "w", encoding="utf-8") as fh:
        fh.write("{ not json")
    assert style.load_preferences() == {}
    with open(own_preferences, "w", encoding="utf-8") as fh:
        json.dump({"style": {"tick_size": "big",
                             "analysis_flush": "sideways",
                             "line_width": 99, "no_such_thing": 3}}, fh)
    loaded = style.load_preferences()
    assert "tick_size" not in loaded
    assert "analysis_flush" not in loaded
    assert loaded["line_width"] == 8.0                  # clamped, not refused


def test_auto_flush_follows_the_template_per_kind():
    doc = model.Document()
    for name, side in (("Onset point", "left"), ("Endset point", "left"),
                       ("Glass transition", "left"),
                       ("Peak Integration (enthalpy)", "center"),
                       ("Peak height", "center")):
        analysis = model.Analysis(1, None, name, {})
        flush = style.value(doc, analysis, "flush")
        assert flush == style.FLUSH_AUTO
        assert style.flush_for(analysis, flush) == side


# ------------------------------------------------------------ in a session
def _reopen(doc, path, sample):
    session.save(doc, str(path))
    reopened, problems = session.load(
        str(path), lambda _p: model.Sample(sample.path, sample.data))
    return reopened, problems


def test_the_figure_style_and_unchosen_sizes_round_trip(tmp_path, sample):
    doc = model.Document()
    doc.add_sample(sample, [0])
    doc.style.analysis_size = 7.0
    doc.style.analysis_flush = style.FLUSH_RIGHT
    doc.axes["y"].tick_size = 12.0
    reopened, problems = _reopen(doc, tmp_path / "styled.dscpanel", sample)
    assert problems == []
    assert reopened.style.analysis_size == 7.0
    assert reopened.style.analysis_flush == style.FLUSH_RIGHT
    assert reopened.style.legend_size is None
    assert reopened.axes["y"].tick_size == 12.0
    # not chosen stays not chosen, so the next defaults still reach it
    assert reopened.axes["x"].tick_size is None
    assert reopened.legend.size is None
    assert reopened.scans[0].line_width is None


def test_a_version_1_session_does_not_pin_the_old_sizes(tmp_path, sample):
    """Version 1 wrote every size whether or not it was chosen. Read
    literally, a figure saved then would ignore every default set since."""
    doc = model.Document()
    doc.add_sample(sample, [0])
    path = tmp_path / "old.dscpanel"
    session.save(doc, str(path))
    with open(str(path), encoding="utf-8") as fh:
        state = json.load(fh)
    state["version"] = 1
    state.pop("style")
    state["axes"]["x"]["tick_size"] = 8.0                # the old built-in
    state["axes"]["y"]["tick_size"] = 12.0               # really chosen
    state["legend"]["size"] = 9.0
    state["scans"][0]["line_width"] = 1.0
    with open(str(path), "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    reopened, _problems = session.load(
        str(path), lambda _p: model.Sample(sample.path, sample.data))
    assert reopened.axes["x"].tick_size is None
    assert reopened.axes["y"].tick_size == 12.0
    assert reopened.legend.size is None
    assert reopened.scans[0].line_width is None


def test_an_analysis_made_here_is_still_there_after_reopening(tmp_path,
                                                             sample):
    """It exists nowhere but in the panel, and used to be dropped from the
    session file - so every analysis the double-click-drag made was lost."""
    doc = model.Document()
    doc.add_sample(sample, [0])
    scan = doc.scans[0]
    made = measure.run("Peak Integration (enthalpy)", scan, 70.0, 150.0)
    made.flush = style.FLUSH_LEFT
    made.label_size = 11.0
    made.label = "first melt"
    reopened, problems = _reopen(doc, tmp_path / "measured.dscpanel", sample)
    assert problems == []
    again = [a for a in reopened.scans[0].analysis_objects
             if a.source == "panel"]
    assert len(again) == 1
    back = again[0]
    # recomputed from the re-read file, not copied: the same number anyway
    assert model.number(back.fields["Enthalpy (normalized)"]) == \
        pytest.approx(model.number(made.fields["Enthalpy (normalized)"]))
    assert back.cursors() == pytest.approx(made.cursors())
    assert back.flush == style.FLUSH_LEFT
    assert back.label_size == 11.0
    assert back.label == "first melt"
    assert back.visible
