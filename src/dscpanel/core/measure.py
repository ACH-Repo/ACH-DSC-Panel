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
    keys on. `label` is the caption the finished analysis is given, with the
    markup `ui/plot.py` draws: `*` italic, `_{}` subscript, and a backslash
    name for a Greek letter. It is filled in with PERCENT formatting, not
    `str.format`, because the subscript braces in `*T*_{g}` are exactly what
    `format` would try to substitute - and did.
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
                label="*T*_{onset} = %.1f %s",
                note="tangent from the flat part to the transition"),
    Measurement("Peak Integration (enthalpy)", integrate, title="Integration",
                label=r"\Delta*H* = %.3f %s",
                note="area against a linear baseline"),
    Measurement("Glass transition", glass_transition,
                title="Glass transition",
                label="*T*_{g} = %.1f %s",
                note="onset, midpoint and end of the step"),
    Measurement("Endset point", endset, title="Endset",
                label="*T*_{endset} = %.1f %s",
                note="the tangent construction, from the other side"),
    Measurement("Peak height", peak_height, title="Peak height",
                label="*q*_{peak} = %.3f %s",
                note="height above the baseline between the cursors"),
    Measurement("Signal change", signal_change, title="Signal change",
                label=r"\Delta*q* = %.3f %s",
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
    analysis.label = default_label(entry, analysis)
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
    """The label an analysis should carry once its fields become `fields`.

    A label that is still the default one quotes the OLD number, so it is
    rewritten with the new one. One somebody typed is theirs and is kept.
    Re-measuring used to keep the label as it was, so the figure went on
    showing the number from before the cursors moved.
    """
    entry = by_name(analysis.model_name)
    if entry is None or analysis.label != default_label(entry, analysis):
        return analysis.label
    fresh = model.Analysis(0, analysis.scan, analysis.model_name, fields)
    return default_label(entry, fresh)


def default_label(entry, analysis):
    """The caption a fresh analysis carries, with its number filled in.

    Written the moment it is made rather than left to the automatic summary,
    because it is meant to be EDITED: the figure wants "T_g = 78.9 degC", and
    the fastest way to get whatever wording is wanted is to start from that
    and change it.
    """
    value = analysis.value()
    if value is None or not entry.label:
        return None
    unit = "°C"
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
    return entry.label % (value, unit)
