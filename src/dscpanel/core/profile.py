"""What is particular to THIS plotter's data: DSC and SDT/TGA.

This program is the first of a family of stacked-trace plotters on one
handling. The handling is shared; what a kind of data wants differently -
how F frames it, which analyses exist, which decorators a figure starts
with - is gathered here, so a sibling changes this module rather than the
handling code.

UI-free: plain values.
"""

#: F frames everything at once: a two-step F - x first, then y - is of
#: no use for DSC. A spectra plotter, where the x range is the question,
#: sets True.
FIT_STAGED = False


#: Where a curve IS, for the swipe that makes every curve taller in its
#: place (`PlotWidget.scale_intensity`). A heat flow goes both ways from its
#: baseline (exo and endo), so its middle height - the median - is where it
#: is; a spectra plotter takes the baseline its bands hang from instead.
def baseline(values, _doc):
    """The baseline of a curve's `values` as drawn (no offset), in the
    axis's unit."""
    import numpy as np
    return float(np.median(values))


#: A session keeps only the PATHS of its files: a .tri is far too big to
#: copy into every session. A moved file is still looked for beside the
#: session. (A spectra plotter sets True and keeps copies.)
EMBED_SOURCES = False


def name_label_corner(_doc=None):
    """Where a label naming a curve sits (Ctrl+T on selected curves,
    `MainWindow.name_labels`): above the curve's right end. A heat flow's
    start is where a run settles, its end where the figure has room."""
    return "upper right"


#: What "Details..." says of a file besides where it is and how big
#: (`session.file_facts`): what the run itself records - a .txt export's
#: header line, else a .tri's metadata string.
DETAILS = (
    ("Sample name", ("Sample name", "samplename")),
    ("Run date", ("rundate",)),
    ("Instrument", ("Instrument name", "instrumentname", "instrumenttype")),
    ("Operator", ("Operator", "operator")),
    ("Procedure", ("proceduresegments",)),
)


def details(sample):
    """`[(what, value), ...]`: what `sample`'s run records of itself, for
    "Details..." - the facts that tell two files of one name apart."""
    head = (sample.data or {}).get("head", {}) or {}
    rows = []
    for title, keys in DETAILS:
        value = next((str(head[k]) for k in keys if head.get(k)), "")
        if value:
            rows.append((title, value))
    rows.append(("Segments", str(sample.segment_count())))
    rows.append(("Sample mass", sample.mass_text() or "none recorded"))
    return rows
