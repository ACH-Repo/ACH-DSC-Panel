"""What the y axis means, and what a scan needs before it can say so.

UI-free on purpose (the golden rule this project inherits from MoloM and ORCA
Workbench): everything here is arithmetic and naming, so it can be tested
without a window.

**A scan is never normalised to itself.** Christian's rule, and it is a
statement about DSC rather than a preference: a diffractogram or an IR
spectrum can defensibly be scaled to its own maximum, because the quantity of
interest is where the features are. A DSC trace carries a baseline that
depends on the sample mass, the pan, the heating rate and the sensor, and
scaling each trace by its own extremum would silently make those differences
disappear - which is exactly the comparison a stack of DSC scans is for. So
every conversion here is a PHYSICAL one: watts, watts per gram, watts per
mole. Nothing divides by a curve's own maximum anywhere in this program.

**Per mole is opt-in and cannot be guessed.** Heat flow is a power, so W/mol
is (W/g) x (g/mol) and needs the molar mass of the substance. There is no
sensible default for M: a wrong one gives a plot that looks perfectly
reasonable and is wrong by whatever factor. So a scan without M is not put on
a per-mole axis quietly - see `missing` below, and `ui/plot.py` for what the
window does about it.
"""

import re

from . import numbers

#: The base every conversion starts from: heat flow in WATTS, as stored in the
#: file. The reader also offers "Heat Flow (Normalized)" in W/g, which is the
#: same number divided by the mass it also stores; going through watts keeps
#: one path instead of two.
BASE_UNIT = "W"

UNIT_MW = "mW"
UNIT_W_G = "W/g"
UNIT_W_MOL = "W/mol"

#: In menu order. mW is the raw instrument signal, W/g is what almost every
#: DSC figure uses, W/mol is the opt-in per-mole axis.
UNITS = (UNIT_MW, UNIT_W_G, UNIT_W_MOL)

#: What each unit needs before a scan can be drawn in it.
NEEDS_MASS = (UNIT_W_G, UNIT_W_MOL)
NEEDS_MOLAR_MASS = (UNIT_W_MOL,)

AXIS_LABEL = {
    UNIT_MW: "Heat flow / mW",
    UNIT_W_G: "Heat flow / (W/g)",
    UNIT_W_MOL: "Heat flow / (W/mol)",
}

#: The enthalpy a peak integration reports, per unit choice. An integral over
#: time turns W into J, so the per-mole one is kJ/mol by convention rather
#: than J/mol, which is the unit thermochemistry is quoted in.
ENTHALPY_LABEL = {
    UNIT_MW: "mJ",
    UNIT_W_G: "J/g",
    UNIT_W_MOL: "kJ/mol",
}

#: Which exothermic direction the y axis points in.
EXO_DOWN = "down"
EXO_UP = "up"

#: The word on the heat-flow arrow. "exo down" and "endo up" describe the SAME
#: orientation and differ only in which direction the arrow names, which is
#: why the arrow carries both a word and a direction.
WORD_EXO = "exo"
WORD_ENDO = "endo"

ARROW_WORDS = (WORD_EXO, WORD_ENDO)
ARROW_DIRECTIONS = (EXO_DOWN, EXO_UP)


def orientation(word, direction):
    """The exothermic direction meant by an arrow labelled `word` `direction`.

    "Exo down" and "endo up" are the same picture; so are "exo up" and "endo
    down". Changing the arrow between two labels that mean the same thing
    must not flip the data, and changing it between labels that mean opposite
    things must - which is what this function is for.
    """
    same = (word == WORD_EXO) == (direction == EXO_DOWN)
    return EXO_DOWN if same else EXO_UP


def factor(unit, base=BASE_UNIT, mass_g=None, molar_mass=None):
    """`(factor, missing)` to multiply a scan's stored heat flow by.

    `base` is what the FILE stored: watts (a `.tri`) or watts per gram (a
    TRIOS `.txt` export, which writes "Heat Flow (Normalized)" and no raw
    signal). Which one it is decides what a conversion still needs, and
    getting that wrong is how a perfectly readable export ends up refusing to
    draw: from W/g, a per-mole axis needs only the molar mass, and it is the
    mW axis that needs the sample mass.

    `missing` is None when the conversion is possible, or the name of what it
    needs - "sample mass" or "molar mass". This function never substitutes a
    value of its own, because a substituted mass is a wrong plot that looks
    right.
    """
    if unit not in UNITS:
        raise ValueError("unknown unit: {!r}".format(unit))
    if base == UNIT_W_G:
        if unit == UNIT_W_G:
            return 1.0, None
        if unit == UNIT_MW:
            if not mass_g:
                return None, "sample mass"
            return 1000.0 * float(mass_g), None
        if not molar_mass:
            return None, "molar mass"
        return float(molar_mass), None
    if unit == UNIT_MW:
        return 1000.0, None
    if not mass_g:
        return None, "sample mass"
    if unit == UNIT_W_G:
        return 1.0 / float(mass_g), None
    if not molar_mass:
        return None, "molar mass"
    # W/g times g/mol: the mass cancels and a mole is left.
    return float(molar_mass) / float(mass_g), None


def missing(unit, base=BASE_UNIT, mass_g=None, molar_mass=None):
    """What stops this scan being drawn in `unit`, or None."""
    return factor(unit, base, mass_g, molar_mass)[1]


def convert_offset(old_factor, new_factor, offset):
    """An offset in display units, carried across a change of unit.

    An offset is stored in the unit it was dragged in, so that the number the
    offset arrow shows is the number the axis speaks. Changing the unit would
    otherwise leave a stack collapsed on top of itself (W/g to mW is a factor
    of 1000). Each scan carries its OWN factor across, because the factor
    depends on its mass and molar mass - so a per-mole axis genuinely
    rearranges a stack, which is a true statement about the data and not a
    bug.
    """
    if not old_factor or not new_factor:
        return offset
    return float(offset) * (float(new_factor) / float(old_factor))


def enthalpy_factor(unit, base=BASE_UNIT, mass_g=None, molar_mass=None):
    """`(factor, missing)` from an integral to `ENTHALPY_LABEL`.

    The integral is of the stored heat flow over time in seconds, so it
    arrives in joules from a watts base and in J/g from a per-gram one.
    """
    scale, want = factor(unit, base, mass_g, molar_mass)
    if scale is None:
        return None, want
    # Per mole is quoted in kJ/mol rather than J/mol, which is the only place
    # the enthalpy scaling differs from the axis scaling.
    return (scale / 1000.0 if unit == UNIT_W_MOL else scale), None

# --------------------------------------------------------------------- x axis
#: The temperature scales the x axis can be drawn in. The FILE is always in
#: degrees Celsius - TRIOS stores nothing else - so these are display
#: conversions applied on the way out, and every stored analysis cursor goes
#: through the same two functions.
TEMP_C = "degC"
TEMP_K = "K"
TEMP_F = "degF"
TEMPERATURE_UNITS = (TEMP_C, TEMP_K, TEMP_F)

TEMPERATURE_LABEL = {TEMP_C: "\u00b0C", TEMP_K: "K", TEMP_F: "\u00b0F"}

#: Absolute zero, and the two numbers that make Fahrenheit what it is.
KELVIN_OFFSET = 273.15
F_SCALE = 9.0 / 5.0
F_OFFSET = 32.0


def from_celsius(values, unit):
    """Celsius (what the file holds) to whatever the axis is showing."""
    if unit == TEMP_K:
        return values + KELVIN_OFFSET
    if unit == TEMP_F:
        return values * F_SCALE + F_OFFSET
    return values


def to_celsius(values, unit):
    """The inverse: what the user typed, back to the file's own scale."""
    if unit == TEMP_K:
        return values - KELVIN_OFFSET
    if unit == TEMP_F:
        return (values - F_OFFSET) / F_SCALE
    return values


#: A typed temperature: a number, and optionally its unit - C, F or K, with
#: or without a degree sign or "deg", in any case. "98" is in `unit`. The
#: number may be a sum: "98+5 K" (`numbers.evaluate`).
_TYPED_TEMPERATURE = re.compile(
    r"^\s*([-+0-9.,*/() \t]*?[0-9.)])\s*"
    r"((?:\u00b0|deg)?\s*[cfk])?\s*$", re.I)


def parse_temperature(text, unit=TEMP_C):
    """A typed temperature in degrees CELSIUS, or None if it is not one.

    `98` is 98 of `unit` (the axis's); `98 F`, `98degf`, `371 K`, `98 \u00b0c`
    say their own unit and are converted. A comma is a decimal point.
    """
    match = _TYPED_TEMPERATURE.match(str(text or ""))
    if not match:
        return None
    value = numbers.evaluate(match.group(1))
    if value is None:
        return None
    token = (match.group(2) or "").lower()
    for noise in ("\u00b0", "deg", " "):
        token = token.replace(noise, "")
    typed = {"c": TEMP_C, "f": TEMP_F, "k": TEMP_K}.get(token, unit)
    return float(to_celsius(value, typed))
