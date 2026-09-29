"""How a number is WRITTEN: the format strings of the house style.

A format is Python's own percent format for ONE number - `%.2f`, `%+.1f`,
`%.0f` - because that is what Christian already writes, and a second
mini-language would be one more thing to learn. `{:.2f}` and a bare `.2f`
are taken too and mean the same.

Two decisions, both on the side of the number being honest:

* **A format is the number, and at most a UNIT.** `%.0f degF` asks for
  the value IN Fahrenheit: the unit is a conversion, done by
  `core/labels.py`, never a relabelling. Any other text is refused - words
  belong in the label - and so is a unit the program does not know.
* **`%.3g` means three SIGNIFICANT FIGURES, written out.** Python's `%g`
  drops trailing zeros (1.50 becomes "1.5", which claims less than was
  measured) and switches to exponent notation at 1000 ("1.23e+03" on a
  figure). Here `%.Ng` rounds to N significant figures and writes them all,
  in fixed notation: 13.2, 1.50, 0.0523, 141, 1230. That is what a default
  of "3 significant figures" for enthalpies needs: a small enthalpy keeps
  its digits instead of vanishing behind a fixed number of decimals.

UI-free: plain strings and floats.
"""

import math
import re

#: One conversion, and nothing else around it.
_SPEC = re.compile(r"^%([-+ 0#]*)(\d*)(?:\.(\d+))?([fFeEgGd])$")
#: The number part at the start of a format, in any of the three spellings,
#: and whatever follows it (a unit, or nothing).
_LEAD = re.compile(r"^(%[-+ 0#]*\d*(?:\.\d+)?[fFeEgGd]"
                   r"|\{:[-+ 0#]*\d*(?:\.\d+)?[fFeEgGd]\}"
                   r"|[-+ 0#]*\d*(?:\.\d+)?[fFeEgGd](?![A-Za-z]))(.*)$")

#: The built-in formats, by what the number is.
TEMPERATURE = "%.0f"        # an onset, an endset, a Tg: whole degrees
VALUE = "%.3g"              # an enthalpy, a step: three significant figures
OFFSET = "%+.1f"            # the template's add_yoffset_markers
MASS = "%.0f"               # a mass at a temperature: "99 %", as he writes it


def normalise(spec, unit_of=None):
    """`spec` as a canonical format - `%.2f`, or `%.2f K` with a unit - or
    None if it is not one.

    Accepts `%.2f`, `{:.2f}` and `.2f`. A unit after the number is kept only
    when `unit_of` (a function: text -> canonical unit, or None) knows it;
    without `unit_of`, a format may not carry one (an axis's numbers sit on
    its ticks, so their unit is the axis's). Anything else is refused.
    """
    if spec is None:
        return None
    text = str(spec).strip()
    match = _LEAD.match(text)
    if not match:
        return None
    number, rest = match.group(1), match.group(2).strip()
    if number.startswith("{:"):
        number = "%" + number[2:-1]
    elif not number.startswith("%"):
        number = "%" + number
    if not _SPEC.match(number):
        return None
    if not rest:
        return number
    unit = unit_of(rest) if unit_of is not None else None
    return "{} {}".format(number, unit) if unit else None


def _any_unit(text):
    return str(text).strip() or None


def split(spec):
    """`(number format, unit or None)` of a canonical format."""
    if not spec:
        return None, None
    parts = str(spec).split(" ", 1)
    return parts[0], (parts[1] if len(parts) > 1 else None)


def is_valid(spec, unit_of=None):
    return normalise(spec, unit_of) is not None


def write(value, spec, fallback=VALUE):
    """`value` written with `spec` (or `fallback` when `spec` is no format).

    Never raises: a paint call is the last place for an exception, and a
    format that does not parse falls back rather than blanking the figure.
    """
    if value is None:
        return "?"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "?"
    if value != value or abs(value) == float("inf"):
        return "?"
    # Only the NUMBER is written here; a unit in the format is the
    # caller's to convert to (`core/labels.py`).
    spec = (split(normalise(spec, _any_unit))[0]
            or split(normalise(fallback, _any_unit))[0] or VALUE)
    flags, width, precision, kind = _SPEC.match(spec).groups()
    if kind in "gG":
        digits = int(precision) if precision not in (None, "") else 6
        text = significant(value, max(1, digits))
        if "+" in flags and value >= 0:
            text = "+" + text
        elif " " in flags and value >= 0:
            text = " " + text
    elif kind == "d":
        text = ("%" + flags + width + "d") % int(round(value))
    else:
        text = spec % value
    return _no_negative_zero(text)


def significant(value, digits):
    """`value` rounded to `digits` significant figures, in fixed notation,
    with every one of those figures written (trailing zeros kept)."""
    if value == 0:
        return "0" if digits <= 1 else "0." + "0" * (digits - 1)
    exponent = int(math.floor(math.log10(abs(value))))
    rounded = round(value, digits - 1 - exponent)
    if rounded != 0:
        # 9.996 to three figures is 10.0: the rounding moved the exponent.
        exponent = int(math.floor(math.log10(abs(rounded))))
    decimals = max(0, digits - 1 - exponent)
    return "%.*f" % (decimals, rounded)


def _no_negative_zero(text):
    """"-0" and "-0.0" are zero: a sign on a rounded zero is noise."""
    stripped = text.strip()
    if stripped.startswith("-") and not any(c in "123456789"
                                            for c in stripped):
        return text.replace("-", "", 1)
    return text
