"""What an analysis label SAYS: the words are the user's, the number is not.

A label is a TEMPLATE. `{}` is the measured value, filled in by the program
every time the label is drawn; everything else is the user's text, with the
figure markup (`*T*` italic, `_{on}` subscript, `\\Delta`). The default
templates are `*T*_{on} = {}`, `*T*_{end} = {}`, `*T*_{g} = {}` and
`\\Delta*H* = {}`.

The rules, and why each one is where the program takes control away:

1. **The number is never typed.** It reaches a label only through `{}`, so
   re-measuring, switching the axis to Kelvin, or giving the sample its
   molar mass can never leave a stale number on the figure. (Before this,
   a label stored its number as text and had to be rewritten on every
   change - and a typed one never was.)
2. **A unit is a CONVERSION, not a relabelling** - after `{}`, or in the
   number format (`%.0f degF`). `{} degF` on an onset shows the onset in
   Fahrenheit; `{} kJ/mol` on an enthalpy multiplies by the molar mass. The
   label then says a different unit from the axes but the same thing: it
   still stands at the right place on the curve. With no unit the value
   follows the axes: temperatures in the x axis's unit, an enthalpy per
   mole when the y axis is per mole. Units are read in any case, and
   `F`, `C`, `degF` mean degrees.
3. **A unit the quantity cannot be converted into is refused**: `{} J/g` on
   a temperature is drawn in the temperature's own unit, and the settings
   say why. A number is never drawn beside a unit it is not in.
4. **A conversion that needs what is missing shows `?`**: `{} kJ/mol`
   without a molar mass is `? kJ/mol`, and every export says NO MOLAR MASS -
   the same rule as a per-mole axis. Nothing is assumed.
5. **The digits are the user's** (`core/numbers.py`): rounding changes how
   exact a number looks, never what it is, and the right precision depends
   on the instrument and the claim - which the program does not know.
6. **Free text is free.** A number typed by hand ("lit. 148 degC") is
   allowed, because it may be a reference value; but one next to a unit of
   the analysed quantity is flagged in the settings as not the measurement.

UI-free, like the rest of `core/`.
"""

import re

from . import numbers
from . import units

TEMPERATURE = "temperature"
ENTHALPY = "enthalpy"
HEAT_FLOW = "heat flow"

#: The template an analysis carries until somebody writes their own, by
#: model. Checked in order: a glass transition's fields also carry an
#: "Onset x".
DEFAULTS = (
    ("Glass", "*T*_{g} = {}"),
    ("Endset", "*T*_{end} = {}"),
    ("Onset", "*T*_{on} = {}"),
    ("Integration", "\\Delta*H* = {}"),
    ("Peak height", "*q*_{peak} = {}"),
    ("Signal change", "\\Delta*q* = {}"),
)

_DEG = "°"

#: Every unit a label may ask for, per quantity, as a factor from the base
#: unit (degC, J/g, W/g) and what that factor needs.
#: `(factor, needs)`: needs is None, "mass" (grams) or "molar" (g/mol).
_ENTHALPY_UNITS = {
    "J/g": (1.0, None), "mJ/mg": (1.0, None), "kJ/g": (1e-3, None),
    "J/mol": (1.0, "molar"), "kJ/mol": (1e-3, "molar"),
    "J": (1.0, "mass"), "mJ": (1e3, "mass"), "kJ": (1e-3, "mass"),
}
_HEAT_FLOW_UNITS = {
    "W/g": (1.0, None), "mW/mg": (1.0, None),
    "W": (1.0, "mass"), "mW": (1e3, "mass"),
    "W/mol": (1.0, "molar"), "mW/mol": (1e3, "molar"),
}
_TEMPERATURE_UNITS = {
    _DEG + "C": units.TEMP_C, "degC": units.TEMP_C,
    _DEG + "F": units.TEMP_F, "degF": units.TEMP_F,
    "K": units.TEMP_K,
}
_BY_QUANTITY = {TEMPERATURE: _TEMPERATURE_UNITS, ENTHALPY: _ENTHALPY_UNITS,
                HEAT_FLOW: _HEAT_FLOW_UNITS}

_ALL_UNITS = sorted(set(_ENTHALPY_UNITS) | set(_HEAT_FLOW_UNITS)
                    | set(_TEMPERATURE_UNITS), key=len, reverse=True)
#: Other spellings of the temperature units, lower case.
_ALIASES = {"c": _DEG + "C", "f": _DEG + "F", "k": "K",
            _DEG + "k": "K", "degk": "K"}
_UNIT = "(?:{})(?![A-Za-z/])".format(
    "|".join(re.escape(u) for u in _ALL_UNITS))
#: In a label, after `{}`: the known units in any case, and C / F.
_LABEL_UNIT = "(?i:{}|[cf])(?![A-Za-z/])".format(
    "|".join(re.escape(u) for u in _ALL_UNITS))


def canonical_unit(text):
    """A unit as the program writes it ("degF" -> the degree-F sign,
    "kj/mol" -> "kJ/mol"), or None for anything it does not know."""
    token = str(text or "").strip().replace(" ", "")
    lowered = token.lower()
    if lowered in _ALIASES:
        return _ALIASES[lowered]
    for unit in _ALL_UNITS:
        if unit.lower() == lowered:
            return (_TEMPERATURE_UNITS.get(unit) and
                    units.TEMPERATURE_LABEL[_TEMPERATURE_UNITS[unit]]) or unit
    return None


def normalise_format(spec):
    """A number format that may carry a unit (`%.0f degF`), canonical."""
    return numbers.normalise(spec, canonical_unit)
#: `{}`, and the unit right after it if one was written. Not `_{}` or
#: `^{}`, which are markup (an empty subscript).
_PLACEHOLDER = re.compile(r"(?<![_^])\{\}(?:(\s*)(" + _LABEL_UNIT + "))?")
_TYPED = re.compile(r"(?<![\w.])[-+]?\d+(?:[.,]\d+)?\s*(" + _UNIT + ")")


class Rendered(object):
    """A label as drawn: its text and what is wrong with it.

    `problems` is `[(kind, message), ...]`: "missing" (a value that cannot
    be given without a molar or sample mass - exports say so), "unit" (a
    unit the quantity cannot be put in) and "typed" (a number written by
    hand beside a unit of the quantity: not the measurement).
    """

    def __init__(self, text, problems=(), value_text=""):
        self.text = text
        self.problems = list(problems)
        self.value_text = value_text

    def missing(self):
        return [m for kind, m in self.problems if kind == "missing"]


def quantity_of(model_name):
    """What an analysis of this model reports: a temperature, an enthalpy
    or a heat flow."""
    name = str(model_name)
    if "Integration" in name:
        return ENTHALPY
    lowered = name.lower()
    if "height" in lowered or "change" in lowered:
        return HEAT_FLOW
    return TEMPERATURE


def default_template(analysis):
    for word, template in DEFAULTS:
        if word in analysis.model_name:
            return template
    return "%s = {}" % analysis.model_name


def template_of(analysis):
    return (analysis.label if analysis.label is not None
            else default_template(analysis))


def result(analysis):
    """`(value, quantity)` in the base unit (degC, J/g, W/g), value None
    when the analysis carries no decoded number."""
    from .model import number
    name = analysis.model_name
    fields = analysis.fields
    quantity = quantity_of(name)
    if quantity == ENTHALPY:
        return number(fields.get("Enthalpy (normalized)")), quantity
    if quantity == HEAT_FLOW:
        for key, text in fields.items():
            if key in ("Model", "Cursor x", "Cursor x1", "segment", "prog",
                       "attribution"):
                continue
            value = number(text)
            if value is None:
                continue
            if "mW" in str(text) and "/" not in str(text):
                mass = _mass(analysis)
                return ((value / 1000.0 / mass) if mass else None), quantity
            return value, quantity
        return None, quantity
    if "Glass" in name:
        return number(fields.get("Midpoint")), quantity
    if "Endset" in name:
        return number(fields.get("Endset x")), quantity
    if "Onset" in name:
        return number(fields.get("Onset x")), quantity
    return analysis.value(), quantity


def natural_unit(quantity, doc):
    """The unit a value takes when the label names none: the axes'."""
    if quantity == TEMPERATURE:
        unit = getattr(doc, "x_unit", units.TEMP_C) if doc else units.TEMP_C
        return units.TEMPERATURE_LABEL.get(unit, _DEG + "C")
    y_unit = getattr(doc, "y_unit", units.UNIT_W_G) if doc else units.UNIT_W_G
    if quantity == ENTHALPY:
        return "kJ/mol" if y_unit == units.UNIT_W_MOL else "J/g"
    return y_unit


def number_format(analysis, doc):
    from . import style
    return style.value(doc, analysis, "number_format")


def render(analysis, doc=None):
    """The label's text, with every `{}` filled in, and its problems."""
    template = template_of(analysis)
    value, quantity = result(analysis)
    spec = number_format(analysis, doc)
    problems = []
    wanted = _BY_QUANTITY[quantity]
    natural = natural_unit(quantity, doc)
    # The format's unit, if it names one this quantity can be in. The
    # house style's formats cover several quantities (an enthalpy and a
    # peak height share one), so a unit that does not fit is simply not
    # for this one; a format chosen for THIS analysis is held to it.
    format_unit = numbers.split(spec)[1]
    if format_unit is not None and canonical_unit(format_unit) not in wanted:
        if analysis.number_format is not None:
            problems.append(("unit", "'{}' is not a unit of {}: shown in {}"
                                     .format(format_unit, quantity, natural)))
        format_unit = None
    default = format_unit or natural
    shown = []

    def fill(match):
        typed = canonical_unit(match.group(2)) if match.group(2) else None
        unit = typed or default
        if typed and typed not in wanted:
            problems.append(("unit", "'{}' is not a unit of {}: shown in {}"
                                     .format(match.group(2), quantity,
                                             default)))
            unit = default
        text = _in_unit(analysis, value, quantity, unit, spec, problems)
        shown.append(text)
        return text

    text = _PLACEHOLDER.sub(fill, template)
    if analysis.label is not None:
        for match in _TYPED.finditer(_PLACEHOLDER.sub("", template)):
            if canonical_unit(match.group(1)) in wanted:
                problems.append(("typed", "'{}' is typed by hand, not the "
                                          "measurement; {{}} shows the "
                                          "measured value".format(
                                              match.group(0).strip())))
    return Rendered(text, problems, shown[0] if shown else "")


def _in_unit(analysis, value, quantity, unit, spec, problems):
    """`value` (base unit) converted to `unit` and written, with the unit."""
    if value is None:
        return "? " + unit
    if quantity == TEMPERATURE:
        target = _TEMPERATURE_UNITS.get(unit, units.TEMP_C)
        converted = float(units.from_celsius(value, target))
        return "{} {}".format(numbers.write(converted, spec,
                                            numbers.TEMPERATURE),
                              units.TEMPERATURE_LABEL.get(target, unit))
    table = _BY_QUANTITY[quantity]
    factor, needs = table.get(unit, (1.0, None))
    if needs == "molar":
        molar = getattr(getattr(analysis, "scan", None), "molar_mass", None)
        if not molar:
            problems.append(("missing", "NO MOLAR MASS: {} cannot be given "
                                        "in {}".format(quantity, unit)))
            return "? " + unit
        factor *= float(molar)
    elif needs == "mass":
        mass = _mass(analysis)
        if not mass:
            problems.append(("missing", "NO SAMPLE MASS: {} cannot be given "
                                        "in {}".format(quantity, unit)))
            return "? " + unit
        factor *= float(mass)
    return "{} {}".format(numbers.write(value * factor, spec, numbers.VALUE),
                          unit)


def _mass(analysis):
    scan = getattr(analysis, "scan", None)
    sample = getattr(scan, "sample", None)
    return getattr(sample, "mass_g", None)


def convert_heat_flow(value, from_unit, to_unit, scan):
    """A heat flow (an offset, a peak height) from one unit to another, or
    None when the conversion needs a mass the scan does not have."""
    table = _HEAT_FLOW_UNITS
    source, target = canonical_unit(from_unit), canonical_unit(to_unit)
    if source not in table or target not in table:
        return None
    factors = []
    for unit in (source, target):
        factor, needs = table[unit]
        if needs == "molar":
            molar = getattr(scan, "molar_mass", None)
            if not molar:
                return None
            factor *= float(molar)
        elif needs == "mass":
            mass = getattr(getattr(scan, "sample", None), "mass_g", None)
            if not mass:
                return None
            factor *= float(mass)
        factors.append(factor)
    return float(value) / factors[0] * factors[1]


_PLAIN_NAMES = {"Enthalpy (normalized)": "Enthalpy"}


def results(analysis, doc=None):
    """`[(name, text), ...]`: every result an analysis carries beyond its
    cursors, named plainly and written in the figure's units and formats -
    what the settings show under "Results"."""
    from .model import number
    from . import style
    out = []
    skip = ("Model", "segment", "prog", "attribution")
    for key, text in analysis.fields.items():
        if key in skip or "cursor" in key.lower():
            continue
        value = number(text)
        if value is None:
            continue
        # Plain names, not TRIOS's field names ("Onset x", "Enthalpy
        # (normalized)"), which mean nothing without the file format.
        name = key[:-2] if key.endswith(" x") else key
        name = _PLAIN_NAMES.get(name, name)
        raw = str(text)
        if _DEG + "C" in raw or "degC" in raw or key.endswith(" x") \
                or key in ("Midpoint", "Peak temperature"):
            unit = getattr(doc, "x_unit", units.TEMP_C) if doc else units.TEMP_C
            shown = numbers.write(units.from_celsius(value, unit),
                                  style.figure_value(doc,
                                                     "temperature_format"),
                                  numbers.TEMPERATURE)
            out.append((name, "{} {}".format(
                shown, units.TEMPERATURE_LABEL.get(unit, unit))))
            continue
        found = re.search(r"[A-Za-z%/]+(?:/[A-Za-z]+)?\s*$", raw)
        unit = found.group(0).strip() if found else ""
        shown = numbers.write(value, style.figure_value(doc, "value_format"),
                              numbers.VALUE)
        out.append((name, "{} {}".format(shown, unit).strip()))
    return out
