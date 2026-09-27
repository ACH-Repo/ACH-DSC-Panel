"""Analyses computed HERE, from two cursors on one scan.

UI-free: the window collects the two temperatures with its gizmos and calls
`run`; everything below is arithmetic, and it is the SAME arithmetic the
reader uses for the analyses TRIOS stored, because both go through
`trios_analysis`. An onset made in this panel and an onset read out of a
`.tri` are then the same kind of thing, drawn by the same code, and neither
is a second implementation of the other.

What each model needs is declared in `MODELS`, so the quick-select list, the
enabling rules and the dispatch all read one table.
"""

import numpy as np

from . import model
from . import trios_analysis


class Measurement(object):
    """One entry in the quick-select list.

    `title` is what the list shows - the short word somebody is looking for,
    "Onset" and "Integration" rather than the TRIOS model string - and `name`
    is the model as the file writes it, which is what everything downstream
    keys on. What the finished analysis's label says is `core/labels.py`'s
    business: a template per kind, with the measured value filled in.
    """

    def __init__(self, name, run, needs=2, note="", title="", label=""):
        self.name = name
        self.title = title or name
        self.label = label
        self.run = run
        #: How many cursors it takes. Everything here takes two so far; a
        #: one-cursor model (a value at a point) fits without changing
        #: anything else.
        self.needs = needs
        self.note = note


def _series(scan, span=None):
    """`(time_min, temperature, heat_flow_per_gram)` for a scan, or None.

    In the file's own units, ALWAYS: minutes, degrees Celsius and W/g,
    whatever the axes happen to be showing. An analysis is about the
    measurement, so it is computed in the measurement's units and converted
    for display like every stored one.

    Time in MINUTES because that is what `trios_analysis` takes - it converts
    to seconds itself. Handing it seconds gives an enthalpy sixty times too
    large, which is exactly as wrong as it sounds and looks entirely
    plausible on screen.
    """
    temperature = scan.temperature()
    minutes = scan.time_min()
    values, base = scan.heat_flow()
    if temperature is None or values is None:
        return None
    if base != "W/g":
        if not scan.sample.mass_g:
            return None
        values = values / float(scan.sample.mass_g)
    if minutes is None:
        minutes = np.arange(len(values), dtype=float)
    # Only what is DRAWN: a truncated end is gone from the analyses too, and
    # a span (the samples a drag ran between) narrows it to exactly those.
    lo, hi = scan.kept_range(len(values))
    if span is not None:
        lo = max(lo, int(min(span)))
        hi = min(hi, int(max(span)) + 1)
    if hi - lo < 3:
        return None
    return minutes[lo:hi], temperature[lo:hi], values[lo:hi]


def onset(scan, x0, x1, kind="onset", span=None):
    series = _series(scan, span)
    if series is None:
        return None
    _t, temperature, flow = series
    result = trios_analysis.onset_point(temperature, flow, x0, x1, kind=kind)
    key = "Endset x" if kind == "endset" else "Onset x"
    if key not in result:
        return None
    return {"Model": "Endset point" if kind == "endset" else "Onset point",
            "Onset cursor x": "{:.4f} °C".format(x0),
            "Transition cursor x": "{:.4f} °C".format(x1),
            key: "{:.4f} °C".format(result[key])}


def endset(scan, x0, x1, span=None):
    return onset(scan, x0, x1, kind="endset", span=span)


def integrate(scan, x0, x1, span=None):
    series = _series(scan, span)
    if series is None:
        return None
    minutes, temperature, flow = series
    result = trios_analysis.peak_integration(minutes, temperature, flow,
                                             x0, x1)
    if not result:
        return None
    return {"Model": "Peak Integration (enthalpy)",
            "Baseline cursor x": "{:.4f} °C".format(x0),
            "Baseline cursor x1": "{:.4f} °C".format(x1),
            "Enthalpy (normalized)": "{:.4f} J/g".format(
                abs(result["Enthalpy (normalized)"])),
            "Peak temperature": "{:.4f} °C".format(
                result["Peak temperature"])}


def glass_transition(scan, x0, x1, span=None):
    series = _series(scan, span)
    if series is None:
        return None
    _t, temperature, flow = series
    result = trios_analysis.glass_transition(temperature, flow, x0, x1)
    if not result or "Midpoint" not in result:
        return None
    return {"Model": "Glass transition",
            "Onset cursor x": "{:.4f} °C".format(x0),
            "End cursor x": "{:.4f} °C".format(x1),
            "Onset x": "{:.4f} °C".format(result["Onset x"]),
            "End x": "{:.4f} °C".format(result["End x"]),
            "Step height": "{:.4f} W/g".format(result["Step height"]),
            "Midpoint": "{:.4f} °C".format(result["Midpoint"])}


def signal_change(scan, x0, x1, span=None):
    series = _series(scan, span)
    if series is None:
        return None
    _t, temperature, flow = series
    result = trios_analysis.signal_change(temperature, flow, x0, x1)
    if not result:
        return None
    first = next(iter(result.items()))
    return {"Model": "Signal change",
            "Cursor x": "{:.4f} °C".format(x0),
            "Cursor x1": "{:.4f} °C".format(x1),
            first[0]: "{:.4f}".format(first[1])
            if isinstance(first[1], float) else str(first[1])}


def peak_height(scan, x0, x1, span=None):
    series = _series(scan, span)
    if series is None:
        return None
    _t, temperature, flow = series
    result = trios_analysis.peak_height(temperature, flow, x0, x1)
    if not result:
        return None
    out = {"Model": "Peak height",
           "Cursor x": "{:.4f} °C".format(x0),
           "Cursor x1": "{:.4f} °C".format(x1)}
    for key, value in result.items():
        out[key] = ("{:.4f}".format(value) if isinstance(value, float)
                    else str(value))
    return out


#: The quick-select list, in the order it is offered. Onset first because it
#: is what a Tg run is analysed with, then the integral, then the rest.
MODELS = (
    Measurement("Onset point", onset, title="Onset",
                note="tangent from the flat part to the transition"),
    Measurement("Peak Integration (enthalpy)", integrate, title="Integration",
                note="area against a linear baseline"),
    Measurement("Glass transition", glass_transition,
                title="Glass transition",
                note="onset, midpoint and end of the step"),
    Measurement("Endset point", endset, title="Endset",
                note="the tangent construction, from the other side"),
    Measurement("Peak height", peak_height, title="Peak height",
                note="height above the baseline between the cursors"),
    Measurement("Signal change", signal_change, title="Signal change",
                note="how much the signal moved between the cursors"),
)


def by_name(name):
    for entry in MODELS:
        if entry.name == name:
            return entry
    return None


def run(name, scan, x0, x1, span=None):
    """Compute one analysis and attach it to `scan`, or return None.

    The cursors arrive in DEGREES CELSIUS, whatever the axis is showing; the
    caller converts. The result is an `Analysis` with `source = "panel"` and
    an attribution that says it was made here, so a figure can always say
    which numbers came out of the instrument and which out of this program.
    """
    entry = by_name(name)
    fields = compute(name, scan, x0, x1, span)
    if entry is None or not fields:
        return None
    analysis = model.Analysis(id(fields) % 1000000, scan,
                              fields.get("Model", name), fields,
                              source="panel", attribution="measured here")
    analysis.span = clean_span(span)
    analysis.visible = True
    # No label of its own: the default template of its kind, whose `{}` is
    # always the current measurement (`core/labels.py`).
    analysis.label = None
    scan.analysis_objects.append(analysis)
    return analysis


def clean_span(span):
    """Two sample indices, lowest first, or None."""
    if not span or len(span) != 2 or None in tuple(span):
        return None
    low, high = sorted(int(i) for i in span)
    return (low, high) if high > low else None


def compute(name, scan, x0, x1, span=None):
    """The result fields of one analysis between two cursors, or None.

    `run` without making an object: what moving an existing analysis's
    interval needs, so the analysis is updated IN PLACE and whatever holds it
    (its open settings, the outliner, the selection) keeps holding it.
    """
    entry = by_name(name)
    if entry is None:
        return None
    low, high = (x0, x1) if x0 <= x1 else (x1, x0)
    try:
        fields = entry.run(scan, low, high, span=clean_span(span))
    except Exception:
        return None
    return fields or None


def relabelled(analysis, fields):
    """The label an analysis carries once its fields become `fields`: the
    same one. A label is a template (`core/labels.py`) and its `{}` is the
    measurement, so a re-measured analysis cannot keep an old number."""
    return analysis.label


def legacy_label(analysis):
    """The label a panel analysis was GIVEN before round 15, number and all
    ("*T*_{onset} = 61.1 degC"), or None.

    Only for reading old sessions: a label equal to this was never the
    user's words, so it is dropped for the default template, whose number
    follows the measurement. One the user changed is kept as theirs.
    """
    entry = by_name(analysis.model_name)
    if entry is None:
        return None
    value = analysis.value()
    if value is None:
        return None
    unit = "\u00b0C"
    if "Integration" in entry.name:
        value = model.number(analysis.fields.get("Enthalpy (normalized)"))
        unit = "J/g"
    elif "height" in entry.name.lower() or "change" in entry.name.lower():
        for key, text in analysis.fields.items():
            if key in ("Model", "Cursor x", "Cursor x1"):
                continue
            number = model.number(text)
            if number is not None:
                value, unit = number, "W/g"
                break
    if value is None:
        return None
    return _LEGACY.get(entry.name, "") % (value, unit) if _LEGACY.get(
        entry.name) else None


#: The pre-round-15 captions, for `legacy_label` alone.
_LEGACY = {
    "Onset point": "*T*_{onset} = %.1f %s",
    "Peak Integration (enthalpy)": "\\Delta*H* = %.3f %s",
    "Glass transition": "*T*_{g} = %.1f %s",
    "Endset point": "*T*_{endset} = %.1f %s",
    "Peak height": "*q*_{peak} = %.3f %s",
    "Signal change": "\\Delta*q* = %.3f %s",
}


def walk_to(values, start, target, lo=0, hi=None, slack=0.5):
    """The index reached walking ALONG `values` from `start` towards the
    value `target`, either way, inside `[lo, hi)`: the one that gets closest
    before the curve turns away for good.

    How a typed cursor temperature becomes a SAMPLE on a curve that doubles
    back: the walk stays on the branch the cursor is on, where looking the
    temperature up would take whichever branch comes first. A temperature
    jitters sample to sample, so going back by less than `slack` degrees
    is walked through.
    """
    hi = len(values) if hi is None else int(hi)
    lo = int(lo)
    start = int(min(max(int(start), lo), hi - 1))
    best = start
    for step in (1, -1):
        j = start
        while lo <= j + step < hi:
            j += step
            gap = abs(float(values[j]) - target)
            if gap < abs(float(values[best]) - target):
                best = j
            elif gap > abs(float(values[best]) - target) + slack:
                break
    return best


def is_legacy_label(label):
    """True for a caption in the exact shape the panel GENERATED before
    round 15 - its default words, a number, the old unit - whatever the
    number. Such a label was never typed, and its number may be stale."""
    import re
    if not label:
        return False
    for template in _LEGACY.values():
        prefix = template.split("%")[0]
        pattern = (re.escape(prefix)
                   + r"-?\d+(?:\.\d+)? (?:°C|J/g|W/g)$")
        if re.match(pattern, str(label)):
            return True
    return False
