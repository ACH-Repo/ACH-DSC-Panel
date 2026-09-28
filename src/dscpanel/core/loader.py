"""Turning a path into a `Sample`: the reader, plus what it does not tell us.

UI-free. The threading that keeps a five-file drop from freezing the window
lives in `ui/loading.py`; everything here is a plain function, so it can be
tested against a real file without a window.

**The exotherm direction is read from the file, not assumed.** A DSC trace
means the opposite thing upside down, and TRIOS stores its own convention:

* a `.txt` export writes `Exotherm Direction   Down` in its header;
* a `.tri` carries TRIOS's audit trail, where changing the setting leaves the
  sentence `Sample - Exotherm changed to 'Exo Down' from '0'` (seen in
  SES-4-15092026.tri, TRIOS 6.0). The last such sentence is the setting that
  was in force.

Neither is guaranteed to be there - OJ-12 (TRIOS 5.1.1) has no audit sentence
at all - so the fallback is "down", which is the TA default and what every
file seen so far was recorded under. The fallback is REPORTED rather than
silent (`Sample.exo_source`), because a file recorded the other way round
would otherwise produce a figure that is upside down and says nothing about
it.

Open item, and the cheapest way to settle it: an indium calibration run. Its
melting peak is unambiguously endothermic, so which way it points in the
stored arrays proves what the convention in them is, once and for all.
"""

import io
import contextlib
import os
import re

from . import model
from . import trios_io
from . import units

#: What the open dialog and a drop will accept.
READABLE = (".tri", ".txt")

#: TRIOS's audit sentence, and the export header line.
_AUDIT = re.compile(rb"Exotherm changed to '(Exo|Endo) (Up|Down)'",
                    re.IGNORECASE)
_HEADER = re.compile(r"^Exotherm\s+Direction\s*[\t:]\s*(Up|Down)\s*$",
                     re.IGNORECASE | re.MULTILINE)

#: How much of a `.tri` is searched for the audit trail. It sits in the
#: document region at the END of the file, so the tail is where to look, and
#: a bounded read keeps this cheap on a 40 MB file.
_TAIL_BYTES = 4_000_000


class ReadError(Exception):
    """A file that cannot be read as a TRIOS measurement."""


def reader_origin():
    """Where the reader came from, for the About box.

    Read off the reader's own first comment, so it says what is actually
    installed rather than what somebody remembered to type. The reader has
    lived here since ACH-DSC-Plotter was retired (2026-09-28).
    """
    try:
        with open(trios_io.__file__, "r", encoding="utf-8") as fh:
            head = fh.read(400)
    except OSError:
        return "unknown"
    match = re.search(r"started in (\S+) \(([^)]+)\)", head)
    if not match:
        return "this program's own"
    return "this program's own, from {} {}".format(match.group(1),
                                                   match.group(2))


def looks_readable(path):
    """Could this path be a TRIOS file? Extension only, deliberately loose.

    The reader is the only thing that can really tell, so this exists to keep
    an obvious mis-drop out. Anything that gets past it and turns out not to
    be a measurement is refused by `read_sample` with a reason, which is a
    better answer than a drop that silently does nothing.
    """
    return (os.path.isfile(str(path))
            and os.path.splitext(str(path))[1].lower() in READABLE)


def detect_exotherm(path):
    """`(direction, source)` for the file: what the arrays are in.

    `source` is "export header", "audit trail" or "assumed", and the window
    shows it, because the difference between knowing and assuming is the
    difference between a figure and an upside-down figure.
    """
    path = str(path)
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".txt":
            with open(path, "r", encoding="latin-1", errors="replace") as fh:
                head = fh.read(200_000)
            match = _HEADER.search(head)
            if match:
                return match.group(1).lower(), "export header"
        else:
            size = os.path.getsize(path)
            with open(path, "rb") as fh:
                if size > _TAIL_BYTES:
                    fh.seek(size - _TAIL_BYTES)
                raw = fh.read()
            found = list(_AUDIT.finditer(raw))
            if found:
                word, direction = (found[-1].group(1).decode().lower(),
                                   found[-1].group(2).decode().lower())
                # The audit sentence names a LABEL ("Exo Down", "Endo Up"),
                # which is the same pair of words the arrow carries, so the
                # same function turns it into a direction.
                return units.orientation(word, direction), "audit trail"
    except OSError:
        pass
    return units.EXO_DOWN, "assumed"


def read_sample(path):
    """Read one file into a `Sample`, keeping what the reader said.

    The reader prints its warnings (a partial segment identified by shape, an
    analysis that could not be attributed). Under a windowed entry point
    there is no console for those to reach, and they are exactly the lines
    somebody needs to see, so they are captured onto the sample and shown in
    the note line instead of being thrown away.
    """
    path = str(path)
    if not os.path.isfile(path):
        raise ReadError("no such file: {}".format(os.path.basename(path)))
    chatter = io.StringIO()
    try:
        with contextlib.redirect_stdout(chatter):
            data = trios_io.read_tri(path)
    except ReadError:
        raise
    except Exception as exc:                 # the reader raises many kinds
        raise ReadError("{}: {}".format(type(exc).__name__, exc))
    if not (data or {}).get("numdata"):
        raise ReadError("no measured segments in {}".format(
            os.path.basename(path)))
    exo, source = detect_exotherm(path)
    sample = model.Sample(path, data, exo=exo, exo_source=source)
    sample.note = "\n".join(
        line for line in chatter.getvalue().splitlines() if line.strip())
    return sample


def sibling_export(path):
    """A TRIOS `.txt` export of the same run, beside the `.tri`, or None.

    Worth finding when a `.tri` segment records no heat flow: the export of
    the same run is the other place a heat flow can come from, and
    reconstructing one from the raw sensors is not an option (on the indium
    calibration run it was 7 % out in heat flow and 0.29 K out in
    temperature, worse than the calibration is judged by). That indium ramp
    was the case this was written for, and it turned out to be RECORDED, in
    arrays with a flags list the reader did not read before 2026-09-28
    (TRI-FORMAT.md section 3); no segment on the development machine lacks
    a heat flow now, but the mechanism stays for one that does.
    """
    folder = os.path.dirname(os.path.abspath(str(path)))
    stem = os.path.splitext(os.path.basename(str(path)))[0].lower()
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for name in names:
        base, ext = os.path.splitext(name)
        if ext.lower() == ".txt" and base.lower() == stem:
            return os.path.join(folder, name)
    return None


def segments_without_heat_flow(sample):
    """Segment numbers (as TRIOS counts them) that record no heat flow."""
    out = []
    for index, step in enumerate((sample.data or {}).get("numdata", [])):
        dims = step.get("dims") or []
        if "Heat Flow" not in dims and "Heat Flow (Normalized)" not in dims:
            out.append(index + 1)
    return out


def summary(sample):
    """One line about a file that was just opened, for the note line."""
    bits = ["{}: {} segments".format(sample.name, sample.segment_count())]
    if sample.mass_g:
        # An SDT run has no sample-size field: the reader derives the mass
        # from Weight / Weight Change, and an inference says so.
        head = (sample.data or {}).get("head", {}) or {}
        derived = head.get("mass_source") == "derived from the weight"
        bits.append("{:g} mg{}".format(
            sample.mass_g * 1000.0,
            " (derived from the weight)" if derived else ""))
    else:
        bits.append("NO SAMPLE MASS")
    count = sum(len(sample.analyses_for(seg))
                for seg in range(sample.segment_count()))
    if count:
        bits.append("{} stored analyses".format(count))
    if sample.exo_source == "assumed":
        bits.append("exo direction assumed to be down")
    else:
        bits.append("exo {} ({})".format(sample.exo, sample.exo_source))
    gaps = segments_without_heat_flow(sample)
    if gaps:
        bits.append("segment {} records no heat flow".format(
            ", ".join(str(g) for g in gaps)))
        export = sibling_export(sample.path)
        if export:
            bits.append("open {} instead, TRIOS derives it there".format(
                os.path.basename(export)))
    return ", ".join(bits)
