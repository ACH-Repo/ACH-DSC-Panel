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

import collections

import numpy as np

from . import dtg as dtg_module
from . import model
from . import style
from . import trios_analysis
from . import units


class Measurement(object):
    """One entry in the quick-select list.

    `title` is what the list shows - the short word somebody is looking for,
    "Onset" and "Integration" rather than the TRIOS model string - and `name`
    is the model as the file writes it, which is what everything downstream
    keys on. What the finished analysis's label says is `core/labels.py`'s
    business: a template per kind, with the measured value filled in.
    """

    def __init__(self, name, run, needs=2, note="", title="", label="",
                 signals=(model.SIGNAL_HEAT,)):
        self.name = name
        self.title = title or name
        self.label = label
        self.run = run
        #: How many cursors it takes: two for an interval, one for a value
        #: at a point (the mass at a temperature, which stores its one
        #: temperature as both cursors).
        self.needs = needs
        self.note = note
        #: Which curves it is offered on: a heat flow's, a mass's.
        self.signals = tuple(signals)


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

    MEASURED samples only: a flagged sample is NaN (TRI-FORMAT.md section
    3; a DSC run's last segment ends in some, a few runs start with some),
    and one NaN in a least-squares window makes every tangent NaN. They are
    dropped after the slicing, so the kept range and the span still count
    in the segment's own indices.
    """
    temperature = scan.temperature()
    minutes = scan.time_min()
    if getattr(scan, "is_mass", False):
        # A MASS scan is measured on its mass: % of the sample mass where
        # the file has it, else the recorded mg (`series_unit`).
        values = scan.weight_values(model.WEIGHT_PCT)
        if values is None:
            values = scan.weight_values(model.WEIGHT_MG)
        if temperature is None or values is None:
            return None
    else:
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
    minutes, temperature, values = (minutes[lo:hi], temperature[lo:hi],
                                    values[lo:hi])
    with np.errstate(invalid="ignore"):
        measured = (np.isfinite(minutes) & np.isfinite(temperature)
                    & np.isfinite(values))
    if measured.sum() < 3:
        return None
    if not measured.all():
        minutes, temperature, values = (minutes[measured],
                                        temperature[measured],
                                        values[measured])
    return minutes, temperature, values


def series_unit(scan):
    """The unit `_series` measures in: W/g for a heat flow, % (or the
    recorded mg, where the file has no percentage it can trust) for a
    mass."""
    if getattr(scan, "is_mass", False):
        return (model.WEIGHT_PCT
                if scan.weight_values(model.WEIGHT_PCT) is not None
                else model.WEIGHT_MG)
    return units.UNIT_W_G


def acquisition_order(scan, x0, x1, span=None):
    """`(earlier, later)`: two cursor temperatures in the order the
    instrument MET them.

    What decides which side of a transition is its flat side: an onset's
    baseline is the one BEFORE it, an endset's the one after, and on a
    cooling scan "before" is the high temperature. Sorting the cursors and
    taking the low one as flat made the panel's endset the onset under
    another name, and put a cooling onset's baseline on the far side.

    Measured along the curve (`span`, two sample indices), the samples say
    it; otherwise the scan's direction does. An isothermal or unmeasurable
    one counts as heating.
    """
    low, high = sorted((float(x0), float(x1)))
    span = clean_span(span)
    temperature = scan.temperature()
    if span is not None and temperature is not None \
            and span[1] < len(temperature):
        first = float(temperature[span[0]])
        last = float(temperature[span[1]])
        if np.isfinite(first) and np.isfinite(last) and first != last:
            return (low, high) if first < last else (high, low)
    if scan.direction() == "down":
        return high, low
    return low, high


def flat_and_transition(scan, x0, x1, kind="onset", span=None):
    """`(flat, transition)` cursors of an onset or an endset: the flat one
    is the earlier for an onset and the later for an endset."""
    earlier, later = acquisition_order(scan, x0, x1, span)
    return (later, earlier) if kind == "endset" else (earlier, later)


def onset(scan, x0, x1, kind="onset", span=None):
    """An onset or endset between the cursors `x0 <= x1`.

    The fields keep the cursors low first, as every panel analysis does
    (the gizmos and the Start / End fields read them in that order); which
    one is FLAT is worked out here, by acquisition order, and again by
    `tangent_points` - never taken from the field names.
    """
    series = _series(scan, span)
    if series is None:
        return None
    _t, temperature, flow = series
    flat, transition = flat_and_transition(scan, x0, x1, kind, span)
    result = trios_analysis.onset_point(temperature, flow, flat, transition,
                                        kind=kind)
    key = "Endset x" if kind == "endset" else "Onset x"
    if key not in result or not np.isfinite(result[key]):
        return None
    return {"Model": "Endset point" if kind == "endset" else "Onset point",
            "Onset cursor x": "{:.4f} \u00b0C".format(x0),
            "Transition cursor x": "{:.4f} \u00b0C".format(x1),
            key: "{:.4f} \u00b0C".format(result[key])}


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
            "Baseline cursor x": "{:.4f} \u00b0C".format(x0),
            "Baseline cursor x1": "{:.4f} \u00b0C".format(x1),
            "Enthalpy (normalized)": "{:.4f} J/g".format(
                abs(result["Enthalpy (normalized)"])),
            "Peak temperature": "{:.4f} \u00b0C".format(
                result["Peak temperature"])}


def glass_transition(scan, x0, x1, span=None):
    series = _series(scan, span)
    if series is None:
        return None
    _t, temperature, flow = series
    # The onset is the side met FIRST: the high one on a cooling scan.
    earlier, later = acquisition_order(scan, x0, x1, span)
    result = trios_analysis.glass_transition(temperature, flow, earlier,
                                             later)
    if not result or "Midpoint" not in result:
        return None
    return {"Model": "Glass transition",
            "Onset cursor x": "{:.4f} \u00b0C".format(x0),
            "End cursor x": "{:.4f} \u00b0C".format(x1),
            "Onset x": "{:.4f} \u00b0C".format(result["Onset x"]),
            "End x": "{:.4f} \u00b0C".format(result["End x"]),
            "Step height": "{:.4f} W/g".format(result["Step height"]),
            "Midpoint": "{:.4f} \u00b0C".format(result["Midpoint"])}


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
            "Cursor x": "{:.4f} \u00b0C".format(x0),
            "Cursor x1": "{:.4f} \u00b0C".format(x1),
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
           "Cursor x": "{:.4f} \u00b0C".format(x0),
           "Cursor x1": "{:.4f} \u00b0C".format(x1)}
    for key, value in result.items():
        out[key] = ("{:.4f}".format(value) if isinstance(value, float)
                    else str(value))
    return out


DTG_PEAK = "DTG peak temperature"


def dtg_peak(scan, x0, x1, span=None):
    """The peak of a DTG between the cursors: the measured sample farthest
    from the straight line joining the two ends of the stretch - where the
    mass changes fastest, a loss (up: DTG = -dm/dt) or a gain alike. Its
    temperature in degC, and the DTG there in %/degC.

    Over the drawn samples only, between the two a drag ran between
    (`span`), else between the two temperatures (typed cursors). The line
    is taken in the order the run went: a cooling segment runs backwards."""
    if not getattr(scan, "is_dtg", False):
        return None
    temperature = scan.temperature()
    values = scan.dtg_values(dtg_module.PER_DEGREE)
    if temperature is None or values is None:
        return None
    temperature = np.asarray(temperature, dtype=float)
    values = np.asarray(values, dtype=float)
    lo, hi = scan.kept_range(len(values))
    if span is not None:
        lo = max(lo, int(min(span)))
        hi = min(hi, int(max(span)) + 1)
    temperature, values = temperature[lo:hi], values[lo:hi]
    with np.errstate(invalid="ignore"):
        keep = np.isfinite(temperature) & np.isfinite(values)
        if span is None:
            keep &= ((temperature >= min(x0, x1))
                     & (temperature <= max(x0, x1)))
    if keep.sum() < 3:
        return None
    t, v = temperature[keep], values[keep]
    if abs(t[-1] - t[0]) > 1e-9:
        base = v[0] + (v[-1] - v[0]) * (t - t[0]) / (t[-1] - t[0])
    else:
        base = np.linspace(v[0], v[-1], len(v))
    k = int(np.argmax(np.abs(v - base)))
    return {"Model": DTG_PEAK,
            "Cursor x": "{:.4f} \u00b0C".format(x0),
            "Cursor x1": "{:.4f} \u00b0C".format(x1),
            "Peak temperature": "{:.4f} \u00b0C".format(float(t[k])),
            "DTG at peak": "{:.6g} {}".format(float(v[k]),
                                              dtg_module.PER_DEGREE)}


MASS_AT = "Mass at temperature"


def mass_at(scan, x0, x1=None, span=None):
    """The mass of a MASS scan at one temperature (the template's
    `add_annot`): the first MEASURED sample at or past `x0` degC
    in the order the run went (heating: the first at or above it), its
    temperature, and its mass in % and in mg where the file has them. The
    offset is not in it: this is the measurement."""
    if not getattr(scan, "is_mass", False):
        return None
    temperature = scan.temperature()
    if temperature is None or not len(temperature):
        return None
    percent = scan.weight_values(model.WEIGHT_PCT)
    grams = scan.weight_values(model.WEIGHT_MG)
    if percent is None and grams is None:
        return None
    lo, hi = scan.kept_range(len(temperature))
    temp = np.asarray(temperature, dtype=float)
    known = np.zeros(len(temp), dtype=bool)
    for column in (percent, grams):
        if column is not None:
            with np.errstate(invalid="ignore"):
                known |= np.isfinite(np.asarray(column, dtype=float))
    with np.errstate(invalid="ignore"):
        known &= np.isfinite(temp)
        if scan.direction() == "down":
            past = temp <= float(x0)
        else:
            past = temp >= float(x0)
    index = np.flatnonzero(known & past)
    index = index[(index >= lo) & (index < hi)]
    if not len(index):
        return None
    k = int(index[0])
    at = "{:.4f} \u00b0C".format(float(temp[k]))
    out = {"Model": MASS_AT, "Cursor x": at, "Cursor x1": at,
           "Sample": str(k)}
    if percent is not None and np.isfinite(percent[k]):
        out["Mass"] = "{:.4f} %".format(float(percent[k]))
    if grams is not None and np.isfinite(grams[k]):
        out["Mass (mg)"] = "{:.5f} mg".format(float(grams[k]))
    if "Mass" not in out and "Mass (mg)" not in out:
        return None
    return out


#: The quick-select list, in the order it is offered. Onset first because it
#: is what a Tg run is analysed with, then the integral, then the rest.
MODELS = (
    Measurement("Onset point", onset, title="Onset",
                note="tangent from the flat part to the transition",
                signals=(model.SIGNAL_HEAT, model.SIGNAL_MASS)),
    Measurement("Peak Integration (enthalpy)", integrate, title="Integration",
                note="area against a linear baseline"),
    Measurement("Glass transition", glass_transition,
                title="Glass transition",
                note="onset, midpoint and end of the step"),
    Measurement("Endset point", endset, title="Endset",
                note="the tangent construction, from the other side",
                signals=(model.SIGNAL_HEAT, model.SIGNAL_MASS)),
    Measurement("Peak height", peak_height, title="Peak height",
                note="height above the baseline between the cursors"),
    Measurement("Signal change", signal_change, title="Signal change",
                note="how much the signal moved between the cursors"),
    Measurement(MASS_AT, mass_at, needs=1, title="Mass at temperature",
                note="the m% at one temperature",
                signals=(model.SIGNAL_MASS,)),
    Measurement(DTG_PEAK, dtg_peak, title="Peak temperature",
                note="where the mass changes fastest",
                signals=(model.SIGNAL_DTG,)),
)


def models_for(scan):
    """The models offered on `scan`'s curve: a heat flow's or a mass's."""
    signal = getattr(scan, "signal", model.SIGNAL_HEAT)
    return [entry for entry in MODELS if signal in entry.signals]


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
    if entry.needs == 1:
        # A value at a point: no interval to mark.
        analysis.show_interval = False
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


#: What `tangent_points` returns. `points` is `[[degC, y], ...]` - three for
#: an onset or endset, four for a glass transition, in TRIOS's order - or
#: None; `base` is the unit of y, as `units.factor` takes it ("W/g", or "W"
#: for a file analysis made on the raw heat flow); `reason` says in one
#: short line why there are no points, for the analysis window.
Construction = collections.namedtuple("Construction", "points base reason")

#: The reasons, one short line each, as the settings say them.
NO_TANGENTS_EXPORT = "A TRIOS export stores no tangents: drawn as chords."
NO_TANGENTS_FILE = "The file stores no tangents for it: drawn as chords."
ON_THE_WEIGHT = "Made on the weight curve: drawn as chords."
NOT_FITTED = "No tangents could be fitted here: drawn as chords."
DEGENERATE = ("The tangents cross far outside the interval: drawn as "
              "chords.")

#: The unit a stored construction's y is in, by the reader's `variable`.
_BASE_OF = {"Heat Flow (Normalized)": units.UNIT_W_G,
            "Heat Flow": units.BASE_UNIT,
            # An onset of mass loss, made on the weight (the reader's name
            # for TRIOS's Weight (%) is "Weight Change"): drawn on the MASS
            # scan it belongs to.
            "Weight Change": model.WEIGHT_PCT,
            "Weight": model.WEIGHT_MG}


def tangent_points(analysis, scan=None):
    """The tangent construction of an onset, endset or Tg: a `Construction`.

    Whose construction it is follows who made the number:

    * **a `.tri`'s own analysis** draws TRIOS's STORED points (the reader's
      `construction`, `Analysis.stored_construction`), never a Python
      recomputation: those meet at the number TRIOS reported, and a Python
      fit misses it by up to a few K.
    * **one made here** draws the Python construction on its own cursors
      and span - the same fit its number came from, so again they meet.
    * **a `.txt` export's** has no points (the export stores none), and a
      Python construction whose tangents cross far outside the interval
      (near-parallel lines) is not drawn either: `points` is None and
      `reason` says why, and the window draws chords.

    Recomputed only when something it depends on changes: the model, the
    cursors, the span, the scan's kept range and its sample mass.
    """
    scan = scan if scan is not None else analysis.scan
    if not analysis.marks_a_point:
        return Construction(None, None, "")
    if analysis.source != "panel":
        return _stored_construction(analysis, scan)
    key = (analysis.model_name, tuple(analysis.cursors()),
           tuple(analysis.span) if analysis.span else None,
           tuple(scan.keep), scan.sample.mass_g, id(scan))
    memo = getattr(analysis, "_tangent_memo", None)
    if memo is not None and memo[0] == key:
        return memo[1]
    found = _python_construction(analysis, scan)
    analysis._tangent_memo = (key, found)
    return found


def lines_note(analysis, doc=None):
    """Why an analysis that is to be drawn with tangents gets chords, in one
    short line, or "" - for its settings. Besides `tangent_points`'
    reasons, the one the axes add: points in W/g on an mW axis need the
    sample mass, which is never made up."""
    if not analysis.marks_a_point or style.value(
            doc, analysis, "construction") != style.LINES_TANGENTS:
        return ""
    found = tangent_points(analysis)
    if not found.points:
        return found.reason
    scan = analysis.scan
    if getattr(scan, "is_mass", False):
        unit = getattr(doc, "weight_unit", model.WEIGHT_PCT)
        missing = (None if unit == found.base or scan.sample.mass_g
                   else "sample mass")
    else:
        unit = getattr(doc, "y_unit", units.UNIT_W_G)
        missing = units.factor(unit, found.base, scan.sample.mass_g,
                               scan.molar_mass)[1]
    if missing:
        return "Drawing them needs the {}: drawn as chords.".format(missing)
    return ""


def _stored_construction(analysis, scan):
    points = analysis.stored_construction
    if not points:
        export = str(scan.sample.path).lower().endswith(".txt")
        return Construction(None, None, NO_TANGENTS_EXPORT if export
                            else NO_TANGENTS_FILE)
    variable = analysis.fields.get("variable")
    base = _BASE_OF.get(variable)
    on_mass = base in (model.WEIGHT_PCT, model.WEIGHT_MG)
    if base is None or on_mass != bool(getattr(scan, "is_mass", False)):
        # A construction in % has no place on heat-flow axes, nor one in
        # W/g on a mass's.
        return Construction(None, None, ON_THE_WEIGHT
                            if on_mass else NO_TANGENTS_FILE)
    wanted = 4 if "Glass" in analysis.model_name else 3
    try:
        cleaned = [[float(x), float(y)] for x, y in points]
    except (TypeError, ValueError):
        cleaned = []
    if len(cleaned) != wanted or not np.all(np.isfinite(cleaned)):
        return Construction(None, None, NO_TANGENTS_FILE)
    return Construction(cleaned, base, "")


def _python_construction(analysis, scan):
    cursors = analysis.cursors()
    if len(cursors) != 2:
        return Construction(None, None, NOT_FITTED)
    series = _series(scan, clean_span(analysis.span))
    if series is None:
        return Construction(None, None, NOT_FITTED)
    _t, temperature, flow = series
    name = analysis.model_name
    try:
        with np.errstate(all="ignore"):
            if "Glass" in name:
                earlier, later = acquisition_order(scan, cursors[0],
                                                   cursors[1], analysis.span)
                result = trios_analysis.glass_transition(
                    temperature, flow, earlier, later)
                crossings = (result.get("Onset x"), result.get("End x"))
            else:
                kind = "endset" if "Endset" in name else "onset"
                flat, transition = flat_and_transition(
                    scan, cursors[0], cursors[1], kind, analysis.span)
                result = trios_analysis.onset_point(
                    temperature, flow, flat, transition, kind=kind)
                crossings = (result.get("Endset x" if kind == "endset"
                                        else "Onset x"),)
    except (ValueError, IndexError, FloatingPointError, ZeroDivisionError,
            np.linalg.LinAlgError):
        return Construction(None, None, NOT_FITTED)
    if not result or any(c is None for c in crossings):
        return Construction(None, None, NOT_FITTED)
    # Near-parallel tangents meet a long way off, or not at all: more than
    # one interval's width outside the interval is not a construction.
    low, high = sorted(cursors)
    width = high - low
    if any(not np.isfinite(c) or c < low - width or c > high + width
           for c in crossings):
        return Construction(None, None, DEGENERATE)
    points = result.get("construction")
    if not points or not np.all(np.isfinite(points)):
        return Construction(None, None, NOT_FITTED)
    return Construction([[float(x), float(y)] for x, y in points],
                        series_unit(scan), "")


def relabelled(analysis, fields):
    """The label an analysis carries once its fields become `fields`: the
    same one. A label is a template (`core/labels.py`) and its `{}` is the
    measurement, so a re-measured analysis cannot keep an old number."""
    return analysis.label


def legacy_label(analysis):
    """The label an older panel analysis was GIVEN, number and all
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
    """True for a caption in the exact shape the panel once GENERATED -
    its default words, a number, the old unit - whatever the
    number. Such a label was never typed, and its number may be stale."""
    import re
    if not label:
        return False
    for template in _LEGACY.values():
        prefix = template.split("%")[0]
        pattern = (re.escape(prefix)
                   + r"-?\d+(?:\.\d+)? (?:\u00b0C|J/g|W/g)$")
        if re.match(pattern, str(label)):
            return True
    return False
