"""What the window is looking at: samples, scans, and the drawn objects.

UI-free. Everything the plot draws is an OBJECT with properties, because that
is what makes the Blender-style handling possible: a selection is a set of
objects, a transform writes a property, the outliner lists them, the F3
operators act on whichever ones are selected, and the undo stack records the
property that changed. A scan that is "just an array the plot happens to
hold" can be none of those things.

Three kinds exist so far:

* `Scan`   - one segment of one file. The unit of everything: a `.tri` holds
             a heating ramp, a cooling ramp and usually five more, and they
             are compared individually rather than as a file.
* `HeatFlowArrow` - the exo/endo arrow. An object rather than a decoration,
             so it can be dragged, hidden and right-clicked like anything
             else, and so the convention it states is stored in one place.
* `Sample` - not drawn. The FILE a scan came from: its mass, its molar mass,
             and the exotherm direction it was recorded under. Properties
             that belong to the substance live here and are inherited by its
             scans, because a molar mass typed once should not be typed again
             for the second heating of the same sample.

`Document` owns them, and owns the two choices that apply to everything at
once: what the x axis is, and what unit the y axis is in.
"""

import os
import re

import numpy as np

from . import style
from . import units

#: Trace colours, in the order scans are added. Chosen to stay apart on a dark
#: ground and to survive being printed in grey, like MoloM's PXRD palette.
PALETTE = ("#6ea8ff", "#ffb04e", "#7fd08a", "#e07b7b", "#c79bef",
           "#4fd0c8", "#d8d16a", "#f08ac0")

AXIS_TEMPERATURE = "Temperature"
AXIS_TIME = "Time"
AXES = (AXIS_TEMPERATURE, AXIS_TIME)

AXIS_LABEL = {
    AXIS_TEMPERATURE: "Temperature / °C",
    AXIS_TIME: "Time / min",
}

#: How a scan's own direction is decided: the net temperature change over the
#: segment, in kelvin. Below this the segment is called isothermal, which is
#: what an Equilibrate step is even though it still drifts a little.
ISOTHERMAL_K = 1.0

_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")


def number(value):
    """The number inside a TRIOS analysis field, or None.

    The reader hands analyses back as they are written in the file, so a
    cursor position arrives as `'58,4977 °C'` - a German decimal comma
    and a unit. Every consumer here wants a float, and every one of them
    getting this wrong in its own way is how a plot ends up with an onset at
    zero.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER.search(str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


class Obj(object):
    """Anything the window can select, hide, drag or right-click."""

    kind = "object"

    def __init__(self, oid, name=""):
        self.id = int(oid)
        self.name = str(name)
        #: Drawn or not. An undoable property, so hiding is a step.
        self.visible = True
        #: NOT undoable and NOT saved: a selection is where the hands are,
        #: not a decision about the figure.
        self.selected = False

    def __repr__(self):
        return "{}({!r})".format(type(self).__name__, self.name)


class Sample(object):
    """One TRIOS file: the substance, not a curve.

    `molar_mass` is None until somebody types it. That is the point - see
    `core/units.py`: there is no defensible default, so the program carries
    the absence around rather than inventing a number, and the window makes
    the absence visible.
    """

    def __init__(self, path, data, exo=units.EXO_DOWN, exo_source="assumed"):
        self.path = str(path)
        self.data = data
        head = (data or {}).get("head", {}) or {}
        self.sample_name = (head.get("samplename")
                            or head.get("Filename")
                            or os.path.splitext(os.path.basename(path))[0])
        self.instrument = head.get("instrumenttype", "")
        self.run_date = head.get("rundate", "")
        self.mass_g = _mass_g(head)
        #: Grams per mole, typed by the user. Inherited by this sample's scans
        #: unless one of them overrides it.
        self.molar_mass = None
        #: The exotherm direction the FILE was recorded under, and where that
        #: came from ("audit trail", "export header", "assumed"). The arrays
        #: are in this convention, so a display in the opposite one is a sign
        #: flip - and a file recorded the other way round is the one case
        #: where assuming would silently invert a figure.
        self.exo = exo
        self.exo_source = exo_source
        #: Anything the reader printed while reading this file.
        self.note = ""
        self.scans = []

    @property
    def name(self):
        return self.sample_name

    def segment_count(self):
        return len((self.data or {}).get("numdata", []))

    def analyses_for(self, seg):
        """Every stored analysis that belongs to segment `seg` (0-based).

        Two traps, both of which draw an analysis on the wrong scan while
        looking perfectly plausible:

        * **`segment` in the reader's output is ONE-BASED** (`trios_io` writes
          `j + 1`, to match the number TRIOS shows). Comparing it to a
          0-based index puts every onset on the next scan down - a cooling
          run, where it is not obviously wrong until somebody quotes it.
        * **A `.txt` export has no `segment` at all.** Its analyses are keyed
          by the step NAME, and three segments of a run routinely share one.
          So the key is matched against this segment's program string, and an
          ambiguous name is attributed to the first segment that carries it -
          the same "order-based guess" the reader itself falls back to, and
          it is marked so the readout can say it is a guess.
        """
        out = []
        blocks = (self.data or {}).get("analyses", {}) or {}
        numdata = (self.data or {}).get("numdata", [])
        if seg >= len(numdata):
            return out
        prog = str(numdata[seg].get("prog", ""))
        stem = prog.rsplit(" #", 1)[0]
        first_with_stem = None
        for index, step in enumerate(numdata):
            if str(step.get("prog", "")).rsplit(" #", 1)[0] == stem:
                first_with_stem = index
                break
        for key, models in blocks.items():
            for model_name, entries in models.items():
                for entry in entries:
                    number_ = entry.get("segment")
                    if number_ is not None:
                        if int(number_) - 1 != seg:
                            continue
                        item = dict(entry)
                    else:
                        if key not in (prog, stem) or first_with_stem != seg:
                            continue
                        item = dict(entry)
                        item["attribution"] = "by step name"
                    item.setdefault("Model", model_name)
                    out.append(item)
        return out


def _mass_g(head):
    """Sample mass in grams from the reader's header, or None.

    `samplesize` is in milligrams and may carry a German decimal comma; the
    reader also writes a formatted `Sample Mass`. Either will do, and neither
    is guaranteed.
    """
    for key in ("Sample Mass", "samplesize"):
        value = number(head.get(key))
        if value:
            return value / 1000.0
    return None


class Scan(Obj):
    """One segment of one file: a curve with a place in the stack."""

    kind = "scan"

    def __init__(self, oid, sample, seg, colour):
        Obj.__init__(self, oid, "")
        self.sample = sample
        self.seg = int(seg)
        self.colour = str(colour)
        #: Vertical placement, in the unit the y axis is currently showing.
        #: Continuous, dragged with the mouse or typed after G - never a slot
        #: in a stacking order. Christian: DSC scans sit where they are put.
        self.offset = 0.0
        #: None follows the house style (`core/style.py`); read it through
        #: `style.value`, never directly.
        self.line_width = None
        #: Which part of the segment is DRAWN, as fractions of its samples
        #: counted from the start: the DSC_Plotter template's `x_truncate`
        #: (`x0=0.01` hides the first 1 %), so the driver export repeats it
        #: exactly. By POSITION ALONG THE CURVE and never by temperature: a
        #: segment's temperature doubles back at its start and runs backwards
        #: when cooling, so a temperature window cuts every branch at once.
        #: The hidden ends are left out of the fit, the picking, arranging,
        #: exports and analyses, and drawn dashed only on hover.
        self.keep = (0.0, 1.0)
        #: None means "use the program string", which is what it says in
        #: TRIOS. A typed one wins.
        self.label = None
        #: The analyses drawn on this scan, as objects. Built from the file
        #: the first time they are asked for; see `analysis_objects`.
        self._analyses = None
        #: Grams per mole for THIS scan, overriding the sample's.
        self.molar_mass_override = None
        self._cache_key = None
        self._cache = None

    # ------------------------------------------------------------- identity
    @property
    def step(self):
        """The reader's record for this segment."""
        return self.sample.data["numdata"][self.seg]

    @property
    def program(self):
        """The TRIOS program string, with German decimal commas fixed."""
        return str(self.step.get("prog", "")).replace(",", ".")

    @property
    def molar_mass(self):
        """The molar mass in force: the scan's own, else the sample's."""
        return (self.molar_mass_override
                if self.molar_mass_override else self.sample.molar_mass)

    def display_name(self):
        """What the label beside the curve says."""
        if self.label:
            return str(self.label)
        return "{} {}".format(self.sample.name, self.short_program())

    def short_program(self):
        """"#3 heat 10 K/min" - the segment number, what it does, how fast.

        The program string says what was ASKED for ("Ramp 10.00 C/min to
        250.000 C"); the direction says what the sample actually did, which is
        not the same thing for the final segment of a run that started from a
        passive cool. The number is the segment index as TRIOS counts it, so
        it matches what the operator sees in TRIOS.
        """
        prog = self.program
        index = "#{}".format(self.seg + 1)
        rate = _rate(prog)
        if self.temperature() is None:
            # No temperature recorded for this segment, so what the sample
            # DID cannot be measured. Say what was ASKED for instead of
            # calling a 50 K/min ramp isothermal, which is what happens when
            # an unmeasurable direction defaults to "iso".
            verb = prog.split()[0].lower() if prog.split() else "segment"
            return ("{} {} {:g} K/min".format(index, verb, rate) if rate
                    else "{} {}".format(index, verb))
        move = self.direction()
        if move == "iso":
            target = number(prog.split("to")[-1]) if "to" in prog else None
            temp = self.temperature()
            value = target if target is not None else (
                float(np.mean(temp)) if temp is not None and len(temp) else None)
            return ("{} iso {:.0f} °C".format(index, value)
                    if value is not None else "{} iso".format(index))
        word = "heat" if move == "up" else "cool"
        if rate:
            return "{} {} {:g} K/min".format(index, word, rate)
        return "{} {}".format(index, word)

    def direction(self):
        """"up", "down" or "iso", from the temperature the sample reached."""
        temp = self.temperature()
        if temp is None or len(temp) < 2:
            return "iso"
        change = float(temp[-1]) - float(temp[0])
        if abs(change) < ISOTHERMAL_K:
            return "iso"
        return "up" if change > 0 else "down"

    # ----------------------------------------------------------------- data
    def _column(self, name):
        step = self.step
        dims = step.get("dims") or []
        if name not in dims:
            return None
        return step["nums"][:, dims.index(name)]

    def temperature(self):
        return self._column("Temperature")

    def time_min(self):
        return self._column("Time")

    def heat_flow(self):
        """`(values, base_unit)` for the heat flow as the FILE stored it.

        A `.tri` stores watts; a TRIOS `.txt` export stores only "Heat Flow
        (Normalized)" in W/g. Converting the export back to watts would need
        the mass, which the export does not always carry - and then a file
        that is already in the unit the axis wants could not be drawn in it.
        So the base travels with the values and `core/units.py` works out what
        is still needed.

        `(None, None)` when the segment records no heat flow at all. That
        happens: the ramp segment of a DSC25 calibration run stores only the
        raw sensors, and this file has no Heat Flow T1 to fill it from (see
        TRI-FORMAT.md section 8).
        """
        watts = self._column("Heat Flow")
        if watts is not None:
            return watts, units.BASE_UNIT
        normalised = self._column("Heat Flow (Normalized)")
        if normalised is not None:
            return normalised, units.UNIT_W_G
        return None, None

    def heat_flow_w(self):
        """Heat flow in WATTS, or None when that needs a mass there is not."""
        values, base = self.heat_flow()
        if values is None:
            return None
        if base == units.BASE_UNIT:
            return values
        return (values * float(self.sample.mass_g)
                if self.sample.mass_g else None)

    def x_values(self, axis):
        return (self.temperature() if axis == AXIS_TEMPERATURE
                else self.time_min())

    def missing_for(self, unit, axis=None):
        """What stops this scan being drawn, or None.

        Reports a missing SIGNAL as readily as a missing number, so a segment
        the instrument recorded without a heat flow is flagged in the plot the
        same way a scan waiting for its molar mass is - rather than quietly
        being absent, which is the one outcome that misleads.
        """
        values, base = self.heat_flow()
        if values is None:
            return "heat flow in this segment"
        if axis is not None and self.x_values(axis) is None:
            return "{} in this segment".format(axis.lower())
        return units.missing(unit, base, self.sample.mass_g, self.molar_mass)

    def factor(self, unit):
        _values, base = self.heat_flow()
        if base is None:
            return None
        return units.factor(unit, base, self.sample.mass_g,
                            self.molar_mass)[0]

    def curve(self, axis, unit, exo, x_unit=units.TEMP_C):
        """`(x, y)` ready to draw: converted, flipped, scaled, offset.

        Returns `(None, None)` when the scan cannot be drawn in this unit -
        no mass, no molar mass - rather than substituting anything. The window
        then draws the scan's ABSENCE (see `ui/plot.py`), which is the honest
        picture and the one Christian asked for: a scan that is waiting for a
        molar mass must be visible as such, not quietly plotted wrong.
        """
        key = (axis, unit, exo, self.offset, x_unit,
               self.sample.mass_g, self.molar_mass, self.sample.exo)
        if self._cache_key == key:
            return self._cache
        x = self.x_values(axis)
        if x is not None and axis == AXIS_TEMPERATURE:
            x = units.from_celsius(x, x_unit)
        values, base = self.heat_flow()
        scale = None
        if base is not None:
            scale = units.factor(unit, base, self.sample.mass_g,
                                 self.molar_mass)[0]
        if x is None or values is None or scale is None:
            self._cache_key, self._cache = key, (None, None)
            return self._cache
        # The arrays are in the FILE's convention, so a flip is needed only
        # when the figure is drawn in the other one.
        sign = 1.0 if exo == self.sample.exo else -1.0
        y = values * (scale * sign) + float(self.offset)
        self._cache_key, self._cache = key, (x, y)
        return self._cache

    def kept_range(self, count):
        """`(k0, k1)`: the slice of `count` samples that is drawn.

        The template's own arithmetic (`x_truncate` takes `x[k0:k1]` with
        `k = int(n * fraction)`), so the panel and the driver it exports hide
        the same samples; at least two are always kept.
        """
        start, end = self.keep
        k0, k1 = sorted([int(count * float(start)), int(count * float(end))])
        k0 = max(0, min(k0, count))
        k1 = max(min(count, k0 + 2), min(k1, count))
        return k0, k1

    def is_truncated(self):
        return tuple(self.keep) != (0.0, 1.0)

    def kept_curve(self, axis, unit, exo, x_unit=units.TEMP_C):
        """`curve` without the hidden ends: what is drawn, fitted, arranged
        and exported."""
        x, y = self.curve(axis, unit, exo, x_unit)
        if x is None:
            return x, y
        k0, k1 = self.kept_range(len(x))
        return x[k0:k1], y[k0:k1]

    def baseline_y(self, axis, unit, exo):
        """Where this scan's zero sits on screen: its offset, plus nothing.

        The offset arrow is drawn from here, and the number it shows is this
        number, so the two cannot disagree.
        """
        return float(self.offset)

    def analyses(self):
        """The raw analysis records the file holds for this segment."""
        return self.sample.analyses_for(self.seg)

    @property
    def analysis_objects(self):
        """`Analysis` objects for this scan, built once and then kept.

        Built lazily because a scan that is never shown never needs them, and
        kept because they carry state the user sets: which are visible, their
        colours, and any that were moved here from another scan.
        """
        if self._analyses is None:
            self._analyses = []
            for entry in self.analyses():
                attribution = entry.get("attribution") or "cached curve"
                self._analyses.append(Analysis(
                    id(entry) % 1000000, self, entry.get("Model", "analysis"),
                    entry, source="file", attribution=attribution))
        return self._analyses

    def visible_analyses(self):
        return [a for a in self.analysis_objects if a.visible]


def _rate(prog):
    """The heating rate in K/min out of a program string, or None."""
    match = re.search(r"([-+]?\d+(?:[.,]\d+)?)\s*°?C\s*/\s*min", prog)
    return number(match.group(1)) if match else None


#: The analysis models whose results this program understands well enough to
#: draw a number for. The rest are kept, listed and switchable, but they can
#: only be drawn at their cursor.
DECODED_MODELS = ("Onset point", "Endset point", "Peak Integration",
                  "Glass transition")

#: The models whose RESULT is a temperature on the curve, drawn with lines
#: from the interval's bounds to that point.
POINT_MODELS = ("Onset point", "Endset point", "Glass transition")


class Analysis(Obj):
    """One analysis, as an object that can be shown, hidden and edited.

    An analysis is NOT a property of a scan, it is a thing on the figure, and
    it has to be one here for two reasons.

    * **It is switched on and off individually.** They are off when a file
      opens (Christian's ask: a run carries a dozen and a figure wants one or
      two), and each is ticked on in the outliner or in the scan's settings.
    * **Its attribution is not always certain.** A `.tri` ties an analysis to
      the scan it was run on through the cached curve, which is exact. A
      `.txt` export only names the STEP, and three segments of a run share a
      name - so there the attachment is a guess and the user has to be able
      to move it. `source` and `attribution` say which case this is, and
      `reassign` is how it is corrected.

    Analyses computed IN the panel will be the same class with
    `source = "panel"`; nothing here assumes the numbers came from a file.
    """

    kind = "analysis"

    def __init__(self, oid, scan, model_name, fields, source="file",
                 attribution="cached curve"):
        Obj.__init__(self, oid, model_name)
        self.scan = scan
        self.model_name = str(model_name)
        self.fields = dict(fields or {})
        self.source = source
        self.attribution = attribution
        #: OFF when a file opens. A DSC run routinely carries a dozen stored
        #: analyses and a figure wants one or two of them.
        self.visible = False
        #: "auto" follows the scan's colour.
        self.colour = "auto"
        #: Text override for the marker, or None for the computed one.
        self.label = None
        #: The two SAMPLE INDICES (in the segment's own arrays) an analysis
        #: made by dragging along the curve was measured between, or None -
        #: a file's analyses, and cursors typed as temperatures. A
        #: temperature does not name a point on a curve that doubles back;
        #: an index does, so this is what the measurement is made on.
        self.span = None
        #: How far from the curve the label sits, in pixels, with the arrow
        #: drawn between the two. Dragging the analysis changes this and
        #: nothing else: the movement is locked vertically, so a label can
        #: never wander off the feature it labels.
        #:
        #: None means "whichever side the peak is not on", so a negative
        #: integral labels from below and its arrow does not cross the
        #: shading. A drag replaces it with a number, because that is a
        #: decision rather than a default.
        self.label_dy = None
        #: Shade the integrated area for a peak integration, as the template
        #: does. Meaningless for the other models, and ignored there.
        self.shade = True
        #: Dashed verticals at the two cursors, so the figure says which
        #: interval an analysis covers - the markers the template draws.
        self.show_interval = True
        #: Point size for the label, or None for the house style's (see
        #: `core/style.py`). Read it through `style.value`.
        self.label_size = None
        #: Which edge of the label sits on its leader arrow - the template's
        #: `flush`: "left", "center", "right", or None for the house style,
        #: whose own default follows the analysis kind.
        self.flush = None

    @property
    def decoded(self):
        """True when this model's result fields are understood."""
        return any(name in self.model_name for name in DECODED_MODELS)

    @property
    def marks_a_point(self):
        """True when the result IS a temperature on the curve.

        An onset, an endset, a glass transition's midpoint - as opposed to an
        area (integration) or a height. These are drawn as the template's
        construction: straight lines from each bound of the interval to the
        result point (Christian, round 10).
        """
        return any(name in self.model_name for name in POINT_MODELS)

    @property
    def certain(self):
        """True when there is no doubt which scan this belongs to.

        Either the file tied it to its scan through the cached curve, or it
        was measured HERE, on that scan, which is as certain as it gets. Only
        an analysis inherited from a source that names the step and not the
        segment - a `.txt` export - is a guess.
        """
        return (self.source == "panel"
                or self.attribution in ("cached curve", "moved by hand"))

    def value(self):
        """The temperature this analysis is drawn at, or None."""
        for key in ("Midpoint", "Onset x", "Endset x", "Peak temperature",
                    "Cursor x", "Onset cursor x", "Baseline cursor x"):
            found = number(self.fields.get(key))
            if found is not None:
                return found
        return None

    def summary(self):
        """A short label: what it is and what it says."""
        if self.label:
            return str(self.label)
        kind = self.model_name
        if "Glass" in kind:
            value = number(self.fields.get("Midpoint"))
            return "Tg {:.1f}".format(value) if value is not None else "Tg"
        if "Integration" in kind:
            enthalpy = number(self.fields.get("Enthalpy (normalized)"))
            if enthalpy is not None:
                return "{:.1f} J/g".format(enthalpy)
        if "Onset" in kind or "Endset" in kind:
            value = number(self.fields.get("Onset x")
                           or self.fields.get("Endset x"))
            word = "Endset" if "Endset" in kind else "Onset"
            if value is not None:
                return "{} {:.1f}".format(word, value)
        value = self.value()
        return ("{} {:.1f}".format(kind, value) if value is not None
                else kind)

    def cursors(self):
        """The two cursor temperatures this analysis was made from, in degC.

        What a double-click needs to put the gizmos back where they were.
        Empty when the model stores something else - the cursor NAMES differ
        per model, which is why this is a table rather than two lookups.
        """
        pairs = (("Onset cursor x", "Transition cursor x"),
                 ("Onset cursor x", "End cursor x"),
                 ("Baseline cursor x", "Baseline cursor x1"),
                 ("Cursor x", "Cursor x1"))
        for first, second in pairs:
            low = number(self.fields.get(first))
            high = number(self.fields.get(second))
            if low is not None and high is not None:
                return [low, high]
        return []

    def key(self):
        """A stable identity for the session file.

        The model plus its cursor positions: two analyses of the same kind on
        one scan differ in where their cursors are, and those are the numbers
        the file stores rather than anything this program invented.
        """
        cursors = []
        for name in ("Onset cursor x", "Transition cursor x", "End cursor x",
                     "Baseline cursor x", "Baseline cursor x1", "Cursor x",
                     "Cursor x1"):
            found = number(self.fields.get(name))
            if found is not None:
                cursors.append("{:.4f}".format(found))
        return "|".join([self.model_name] + cursors)

    def reassign(self, scan):
        """Draw this analysis on another scan, and remember that it was moved.

        Only sensible within one sample - an analysis belongs to a run - and
        the caller keeps it to that. `attribution` becomes "moved by hand",
        so nothing later claims the file said so.
        """
        if scan is self.scan:
            return self
        if self in self.scan.analysis_objects:
            self.scan.analysis_objects.remove(self)
        self.scan = scan
        scan.analysis_objects.append(self)
        self.attribution = "moved by hand"
        return self


#: Where an artist's position is measured in.
SPACE_RELATIVE = "relative"      # fractions of the plot, 0..1
SPACE_DATA = "data"              # the axes' own units

#: The nine points of an artist that can sit on its position.
ANCHORS = ("top left", "top", "top right",
           "left", "center", "right",
           "bottom left", "bottom", "bottom right")


class Artist(Obj):
    """Anything drawn on the figure that is not data.

    The arrow, a caption, and whatever joins them - a scale bar, a molecule
    image, a leader note. They have nothing in common with a scan and
    everything in common with each other, so the common part lives here:

    * a POSITION, in one of two spaces. `relative` is a fraction of the plot,
      which keeps an artist in the same corner whatever the view does;
      `data` pins it to a temperature and a heat flow, which is what a note
      about a peak wants. The settings offer both and convert between them,
      so switching does not move anything.
    * an ANCHOR: which of the artist's own nine points sits on that position.
      A caption anchored `left` grows to the right as its text changes; one
      anchored `center` grows both ways.
    * a COLOUR, "auto" meaning the theme's ink.

    What each KIND allows beyond that is a class flag rather than a property,
    because it is a fact about the artist and not a setting: an arrow has no
    meaningful rotation, a scale bar will want length, a molecule image will
    want scale. `can_rotate` and `can_scale` are the two that exist so far;
    the dialogs read them, so a new artist declares its capabilities and gets
    the right fields.
    """

    kind = "artist"
    can_rotate = False
    can_scale = False

    def __init__(self, oid, name="", x=0.5, y=0.5):
        Obj.__init__(self, oid, name)
        self.x = float(x)
        self.y = float(y)
        self.space = SPACE_RELATIVE
        self.anchor = "center"
        self.colour = "auto"

    def position(self):
        return (float(self.x), float(self.y))

    def set_position(self, x, y):
        self.x, self.y = float(x), float(y)
        return self

    def anchor_offsets(self):
        """`(fx, fy)` in 0..1: which point of the artist sits on the position.

        0 is left/top and 1 is right/bottom, so a box of width w and height h
        is drawn at `x - fx * w`, `y - fy * h`.
        """
        anchor = self.anchor if self.anchor in ANCHORS else "center"
        fx = 0.5
        fy = 0.5
        if "left" in anchor:
            fx = 0.0
        elif "right" in anchor:
            fx = 1.0
        if "top" in anchor:
            fy = 0.0
        elif "bottom" in anchor:
            fy = 1.0
        return fx, fy


class Axis(Obj):
    """An axis, as an object with its own settings.

    Double-clicking the numbers or the caption opens this rather than a
    global "plot settings" page, because an axis is a thing on the figure and
    everything else on the figure works that way.

    The defaults are the DSC_Plotter template's `style()`: ticks pointing IN,
    minor ticks between them, no grid at all. The panel used to draw a grid
    because the PXRD window does; a DSC figure does not.
    """

    kind = "axis"

    def __init__(self, oid, which):
        Obj.__init__(self, oid, "{} axis".format(which.upper()))
        self.which = which               # "x" or "y"
        #: None means "say what is on this axis", which follows the unit.
        self.label = None
        self.show_grid = False
        self.minor_ticks = True
        self.ticks_inward = True
        #: Both None until chosen: the house style decides (`core/style.py`).
        self.label_size = None
        self.tick_size = None
        #: Where the caption sits ALONG the axis, as a fraction, and how far
        #: from it in pixels. Both are clamped to the margin outside the plot
        #: (see `PlotWidget`), so a caption cannot be dragged over the data.
        self.label_along = 0.5
        #: Pixels between the axis's NUMBERS and its caption, or None for the
        #: house style's `caption_gap`. Dragging the caption sets it.
        self.label_gap = None

    def caption(self, doc):
        """What the caption says: the user's text, or the axis's own.

        `*` marks italic, so a default caption sets the QUANTITY SYMBOL
        cursive and leaves the unit upright. `T` is a variable and every
        convention worth following sets those in italic - it is also what the
        template's `$T \\quad / \\quad \\mathrm{degC}$` produces.
        """
        if self.label:
            return str(self.label)
        if self.which == "x":
            if doc.x_axis != AXIS_TEMPERATURE:
                return "*t*  /  min"
            return "*T*  /  {}".format(units.TEMPERATURE_LABEL.get(
                getattr(doc, "x_unit", units.TEMP_C), "°C"))
        return "Heat Flow  /  {}".format(doc.y_unit)


class TextLabel(Artist):
    """A caption the user put on the figure, and can move and retype.

    Distinct from the name that appears beside a hovered curve: that is a
    readout, it comes and goes with the cursor, and it is not part of the
    figure. This is part of the figure.

    Scalable - its point size IS its scale - and not rotatable: rotated text
    on a DSC figure is the y caption's job, and that belongs to the axis.
    """

    kind = "label"
    can_scale = True

    def __init__(self, oid, text="Label", x=0.5, y=0.5, scan=None):
        Artist.__init__(self, oid, "Label", x, y)
        self.text = str(text)
        #: None follows the house style (`core/style.py`).
        self.size = None
        self.bold = False
        #: The scan this label belongs to, or None for a free one. An owned
        #: label takes that scan's colour while its own is "auto", is listed
        #: under it in the outliner, and goes when the scan goes - which is
        #: what "a label per line" means. It is still positioned freely.
        self.scan = scan


class Legend(Artist):
    """Which colour is which scan, in a corner of the figure.

    The one thing Christian's matplotlib figures carry that the panel had no
    equivalent for: the names beside the curves are a READOUT, they come and
    go with the cursor, and a figure that leaves the program needs the key
    written into it.

    An artist like the rest, so it is dragged, anchored, coloured and hidden
    the same way. Off by default: a stack of three scans is often clearer
    without one, and turning it on is a tick.
    """

    kind = "legend"
    can_scale = True

    def __init__(self, oid):
        Artist.__init__(self, oid, "Legend", 0.02, 0.98)
        self.anchor = "bottom left"
        #: Off until asked for.
        self.visible = False
        #: None follows the house style (`core/style.py`).
        self.size = None
        #: A box behind it, so it stays readable over a curve.
        self.show_frame = True
        #: Length of the colour sample in front of each name, in pixels.
        self.sample = 22.0
        #: Space between rows, as a multiple of the line height.
        self.spacing = 1.25

    def entries(self, doc):
        """`[(scan, text), ...]` for the scans that are drawn.

        A scan's own label wins over its program name, which is what makes
        the legend say "second heating" when that is what the curve was
        renamed to.
        """
        return [(scan, scan.display_name()) for scan in doc.visible_scans()]


class HeatFlowArrow(Artist):
    """The exo (or endo) arrow, as a draggable object.

    It carries the CONVENTION, not just a picture of one: `word` and
    `direction` decide which way the data is drawn, through
    `units.orientation`. Relabelling it "endo up" leaves the curves alone
    because that means the same thing as "exo down"; relabelling it "exo up"
    flips them, and the y axis with them. That is Christian's rule, and it is
    the only way a figure's arrow cannot end up contradicting its data.
    """

    kind = "arrow"
    #: Its length is a setting rather than a transform, and an arrow that
    #: says "exo down" cannot be rotated without lying, so neither is offered.
    can_rotate = False
    can_scale = False

    def __init__(self, oid, word=units.WORD_EXO, direction=units.EXO_DOWN):
        Artist.__init__(self, oid, "Heat-flow arrow", 0.045, 0.5)
        self.word = word
        self.direction = direction
        #: Total length as a fraction of the plot height. The proportions
        #: inside it are the DSC_Plotter template's, so this is the only knob.
        self.length = 0.075

    @property
    def orientation(self):
        """Which way exotherms point, whatever the label says."""
        return units.orientation(self.word, self.direction)

    def text(self):
        return "{}\n{}".format(self.word.capitalize(),
                               self.direction.capitalize())


class Document(object):
    """The samples, the objects, and the two choices that apply to all of it."""

    def __init__(self):
        self.samples = []
        self.scans = []
        self.arrow = HeatFlowArrow(self._next_id())
        #: The key, off until it is asked for.
        self.legend = Legend(self._next_id())
        #: The two axes, as objects with their own settings.
        self.axes = {"x": Axis(self._next_id(), "x"),
                     "y": Axis(self._next_id(), "y")}
        #: Captions the user has added. Free objects, not tied to a scan.
        self.labels = []
        self.x_axis = AXIS_TEMPERATURE
        #: Which temperature scale the x axis is DRAWN in. The data stays in
        #: Celsius, which is all TRIOS stores; this is a display conversion
        #: (see `core/units.py`), applied to the curves and to every stored
        #: analysis cursor alike.
        self.x_unit = units.TEMP_C
        self.y_unit = units.UNIT_W_G
        #: Which palette the window draws in. A NAME rather than colours, so
        #: the model stays UI-free and `ui/plot.py` owns what the name means.
        #: "blender-default" is the dark screen theme; "light" is the one
        #: every export uses whatever this says.
        self.theme = "blender-default"
        #: This figure's own sizes and alignments, between an object's and
        #: the user's defaults. Saved with the session; see `core/style.py`.
        self.style = style.FigureStyle()
        self.path = ""              # the session file, once saved
        self._next = 100

    # ------------------------------------------------------------------ ids
    def _next_id(self):
        value = getattr(self, "_next", 100)
        self._next = value + 1
        return value

    # -------------------------------------------------------------- content
    def objects(self):
        """Everything selectable, in draw order (later is on top)."""
        return (list(self.scans) + self.analyses() + list(self.labels)
                + list(self.axes.values()) + [self.arrow, self.legend])

    def add_label(self, text="Label", x=0.5, y=0.5, scan=None):
        label = TextLabel(self._next_id(), text, x, y, scan)
        self.labels.append(label)
        return label

    def labels_for(self, scan):
        """The labels that belong to one scan."""
        return [label for label in self.labels if label.scan is scan]

    def labels_of_removed(self, scan):
        """Take a scan's labels off with it, and hand them back.

        Returned rather than dropped, so the command that removed the scan
        can put them back when it is undone.
        """
        owned = self.labels_for(scan)
        self.labels = [label for label in self.labels
                       if label.scan is not scan]
        return owned

    def remove_label(self, label):
        if label in self.labels:
            self.labels.remove(label)
        return label

    def analyses(self):
        """Every analysis object on every scan."""
        return [a for scan in self.scans for a in scan.analysis_objects]

    def visible_analyses(self):
        return [a for scan in self.scans if scan.visible
                for a in scan.visible_analyses()]

    def add_sample(self, sample, segments=None):
        """Add a file and make scans for the segments named (or the default).

        The default follows the rule the DSC_Plotter template already uses and
        Christian already expects: one file shows every segment, several files
        show the first heating scan of each. Applied by the caller, which is
        the only place that knows how many files are open - see
        `default_segments`.
        """
        self.samples.append(sample)
        chosen = (range(sample.segment_count()) if segments is None
                  else segments)
        made = []
        for seg in chosen:
            scan = Scan(self._next_id(), sample,
                        seg, PALETTE[len(self.scans) % len(PALETTE)])
            sample.scans.append(scan)
            self.scans.append(scan)
            made.append(scan)
        return made

    def detach_scan(self, scan):
        """Take a scan off the plot, KEEPING its sample.

        The sample stays even when its last scan goes, which is what makes
        removal undoable and what keeps the file's other segments reachable
        in the outliner: a file is open until it is closed, whether or not
        any of its segments is currently drawn.
        """
        if scan in self.scans:
            self.scans.remove(scan)
        if scan in scan.sample.scans:
            scan.sample.scans.remove(scan)

    def insert_scan(self, scan, index=None):
        """Put a scan back where it was (or at the end)."""
        if scan in self.scans:
            return scan
        if index is None or index > len(self.scans):
            index = len(self.scans)
        self.scans.insert(index, scan)
        if scan not in scan.sample.scans:
            scan.sample.scans.append(scan)
            scan.sample.scans.sort(key=lambda s: s.seg)
        if scan.sample not in self.samples:
            self.samples.append(scan.sample)
        return scan

    def remove_scan(self, scan):
        """Detach a scan and forget its sample if nothing else uses it."""
        self.detach_scan(scan)
        if not scan.sample.scans and scan.sample in self.samples:
            self.samples.remove(scan.sample)

    def close_sample(self, sample):
        """Forget a file entirely: its scans and the sample itself."""
        for scan in list(sample.scans):
            self.detach_scan(scan)
        if sample in self.samples:
            self.samples.remove(sample)

    def sample_for(self, path):
        for sample in self.samples:
            if os.path.normcase(sample.path) == os.path.normcase(str(path)):
                return sample
        return None

    # ------------------------------------------------------------ selection
    def selected(self):
        return [obj for obj in self.objects() if obj.selected]

    def selected_scans(self):
        return [s for s in self.scans if s.selected]

    def select_only(self, objs):
        wanted = set(id(o) for o in (objs or ()))
        for obj in self.objects():
            obj.selected = id(obj) in wanted

    def select_all(self, on=True):
        for obj in self.objects():
            obj.selected = bool(on)

    # ---------------------------------------------------------------- state
    @property
    def exo(self):
        """Which way exotherms point in this figure, from the arrow."""
        return self.arrow.orientation

    def visible_scans(self):
        return [s for s in self.scans if s.visible]

    def scans_missing(self, unit=None):
        """Scans that cannot be drawn in the current unit, and why.

        `[(scan, "molar mass"), ...]`. The window blinks these, the outliner
        marks them, and an export refuses to go out quietly with one in it.
        """
        unit = unit or self.y_unit
        out = []
        for scan in self.scans:
            if not scan.visible:
                continue
            missing = scan.missing_for(unit, self.x_axis)
            if missing:
                out.append((scan, missing))
        return out

    def set_unit(self, unit):
        """Change the y unit, carrying every offset across with it.

        Each scan's offset moves by ITS OWN conversion factor, so a stack
        keeps its shape in W/g to mW (one factor for everybody) and genuinely
        rearranges on a per-mole axis (a factor per sample). The second one
        looks like a bug and is not: two samples of different molar mass
        really are in a different relationship once the axis counts moles.
        """
        if unit == self.y_unit:
            return []
        changes = []
        for scan in self.scans:
            old = scan.factor(self.y_unit)
            new = scan.factor(unit)
            if old and new and scan.offset:
                changes.append((scan, "offset",
                                units.convert_offset(old, new, scan.offset)))
        self.y_unit = unit
        return changes


def default_segments(sample, file_count=1):
    """Which segments a newly opened file starts with: the first heating one.

    Always one scan, whether it is the first file or the fifth. The template
    shows every segment of a lone file, and that is right for a quick look at
    one run; this panel is for STACKED comparisons, where seven curves from
    the first file and one from each of the others is a mess to undo by hand.
    Christian, 2026-09-23: "only showing the first scan for the first file too
    should be the default".

    Everything else is one tick away in the outliner, which lists every
    segment of every open file.
    """
    return [first_upscan(sample)]


def first_upscan(sample):
    """The first segment whose temperature ends above where it started."""
    for seg, step in enumerate((sample.data or {}).get("numdata", [])):
        dims = step.get("dims") or []
        if "Temperature" not in dims:
            continue
        temp = step["nums"][:, dims.index("Temperature")]
        if len(temp) > 1 and float(temp[-1]) - float(temp[0]) > ISOTHERMAL_K:
            return seg
    return 0
