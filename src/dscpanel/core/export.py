"""Getting out: the curves as data, and the figure as a script.

Three exports, and each answers a different question.

* `curves_csv` - what is on screen, as numbers. For a colleague, a
  spreadsheet, or a plot in something else entirely.
* `driver_source` / `write_driver` - the arrangement as a
  `DSC_Plotter.py` driver. **This panel is not trying to become the figure
  engine.** ACH-DSC-Plotter already draws publication figures in matplotlib,
  with tangents, shaded integrals, molecule images and a run record; what it
  does not have is a way to arrange eight scans by hand. So the panel does
  the arranging and hands the result over: the paths, the segments, the
  colours and the offsets, written as the driver that reproduces them.
* `warnings_for` - what an export must not be allowed to hide. A figure drawn
  while a scan was waiting for its molar mass, or with a scan scaled by a
  factor, is a figure that misleads unless it says so. These lines are
  printed AND stamped into the image, which is Christian's rule: the blinking
  label can be ignored in the window, so the export has to carry the notice
  with it.
"""

import os
import re

import numpy as np

from .. import branding
from . import model
from . import units


def warnings_for(doc):
    """Everything an export has to admit to, as short lines."""
    out = []
    for scan, missing in doc.scans_missing():
        out.append("NO {}: {} is not drawn".format(missing.upper(),
                                                   scan.display_name()))
    assumed = sorted({s.name for s in doc.samples
                      if s.exo_source == "assumed"})
    if assumed:
        out.append("EXO DIRECTION ASSUMED (down) for: " + ", ".join(assumed))
    return out


def curves_csv(doc, path):
    """Every visible scan, in the unit on screen, one column pair per scan.

    Column PAIRS rather than one shared x column, because two scans do not
    share a temperature axis: they were sampled at their own points, and a
    cooling scan runs the other way. Interpolating them onto a common grid
    would be inventing data.
    """
    # The KEPT part of each: a truncated end is not part of the figure, so
    # it is not part of its numbers either.
    scans = [s for s in doc.visible_scans()
             if s.kept_curve(doc.x_axis, doc.y_unit, doc.exo,
                             doc.x_unit)[0] is not None]
    if not scans:
        return None
    columns, headers = [], []
    x_label = ("Temperature/C" if doc.x_axis == model.AXIS_TEMPERATURE
               else "Time/min")
    for scan in scans:
        x, y = scan.kept_curve(doc.x_axis, doc.y_unit, doc.exo, doc.x_unit)
        columns.append(x)
        columns.append(y)
        name = scan.display_name().replace(",", " ")
        headers.append("{} {}".format(name, x_label))
        headers.append("{} HeatFlow/{}".format(name, doc.y_unit))
    rows = max(len(c) for c in columns)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# {} export\n".format(branding.APP_NAME))
        for line in warnings_for(doc):
            fh.write("# {}\n".format(line))
        for scan in scans:
            fh.write("# {}: {}, mass {}, M {}, exo {} ({})\n".format(
                scan.display_name(), scan.sample.path,
                "{:g} mg".format(scan.sample.mass_g * 1000.0)
                if scan.sample.mass_g else "unknown",
                "{:g} g/mol".format(scan.molar_mass) if scan.molar_mass
                else "not given",
                scan.sample.exo, scan.sample.exo_source))
        fh.write(",".join(headers) + "\n")
        for i in range(rows):
            cells = []
            for column in columns:
                cells.append("{:.6g}".format(column[i])
                             if i < len(column) else "")
            fh.write(",".join(cells) + "\n")
    return path


def driver_source(doc):
    """The `DSC_Plotter.py` driver that reproduces what is on screen."""
    paths, index = [], {}
    for scan in doc.visible_scans():
        key = os.path.normcase(scan.sample.path)
        if key not in index:
            index[key] = len(paths)
            paths.append(scan.sample.path)
    lines = []
    lines.append("# Written by {}. Paste this over the DRIVER section"
                 .format(branding.APP_NAME))
    lines.append("# of a DSC_Plotter.py made by `dsc -c .`, or run this file")
    lines.append("# next to one.")
    for warning in warnings_for(doc):
        lines.append("# WARNING: {}".format(warning))
    lines.append("")
    lines.append("paths = [")
    for path in paths:
        lines.append("    r'{}',".format(path))
    lines.append("]")
    lines.append("")
    lines.append("MANUAL = True")
    lines.append("")
    lines.append("")
    lines.append("def driver():")
    lines.append("    fig, ax = start_plot()")
    y_dim = {units.UNIT_MW: "'Q'", units.UNIT_W_G: "'Qn'",
             units.UNIT_W_MOL: "'Qn'"}.get(doc.y_unit, "'Qn'")
    x_dim = "'T'" if doc.x_axis == model.AXIS_TEMPERATURE else "'t'"
    for scan in doc.visible_scans():
        i = index[os.path.normcase(scan.sample.path)]
        lines.append("    add_line(ax, datas, ({}, {}), color='{}', x={},"
                     " y={}, label={!r})".format(
                         i, scan.seg, scan.colour, x_dim, y_dim,
                         scan.display_name()))
    for scan in doc.visible_scans():
        if scan.is_truncated():
            # The template's own function, with the same fractions: it
            # slices x[int(n * x0):int(n * x1)] exactly as the panel does.
            i = index[os.path.normcase(scan.sample.path)]
            lines.append("    x_truncate(ax, datas, ({}, {}), x0={:.6g}, "
                         "x1={:.6g})".format(i, scan.seg, scan.keep[0],
                                             scan.keep[1]))
    for scan in doc.visible_scans():
        if scan.offset:
            i = index[os.path.normcase(scan.sample.path)]
            lines.append("    y_offset(ax, datas, ({}, {}), {:.6g})".format(
                i, scan.seg, scan.offset))
    if doc.y_unit == units.UNIT_W_MOL:
        lines.append("    # {} showed W/mol; the template's 'Qn' is"
                     .format(branding.APP_NAME))
        lines.append("    # W/g, so each line still needs x M to match.")
    lines.append("    ax.set_xlim({:.6g}, {:.6g})".format(*doc_view_x(doc)))
    lines.append("    add_exo_arrow(ax)")
    lines.append("    finish_plot(fig, ax)")
    lines.append("")
    return "\n".join(lines) + "\n"


def doc_view_x(doc):
    """The x range the panel is showing, or the data range."""
    view = getattr(doc, "view_x_hint", None)
    if view:
        return view
    lo, hi = None, None
    for scan in doc.visible_scans():
        x, _y = scan.kept_curve(doc.x_axis, doc.y_unit, doc.exo,
                                doc.x_unit)
        if x is None or not len(x):
            continue
        lo = float(np.nanmin(x)) if lo is None else min(lo, float(np.nanmin(x)))
        hi = float(np.nanmax(x)) if hi is None else max(hi, float(np.nanmax(x)))
    return (lo if lo is not None else 0.0, hi if hi is not None else 1.0)


_DRIVER = re.compile(r"^def driver\(\):.*?(?=^[^\s#])", re.S | re.M)
_MANUAL = re.compile(r"^MANUAL\s*=\s*(True|False)\s*$", re.M)
_PATHS = re.compile(r"^paths\s*=\s*\[.*?^\]\s*$", re.S | re.M)


def write_driver(doc, path):
    """Write the driver, as a whole template when one can be built.

    With `achdsc` importable (the plotter package installed), this writes a
    COMPLETE `DSC_Plotter.py`: the template, with the panel's paths, driver
    and `MANUAL = True` spliced in, which runs as it stands. Without it, the
    driver snippet is written on its own with a header saying where to paste
    it. Either way nothing here imports matplotlib.
    """
    source = driver_source(doc)
    try:
        from achdsc import cli as achdsc_cli
    except Exception:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(source)
        return path, "snippet"
    try:
        template = achdsc_cli.render_template([], os.path.dirname(path) or ".")
        body = source.split("MANUAL = True", 1)[1]
        # `re.sub` with a STRING replacement processes backslash escapes, and
        # every one of these replacements carries Windows paths: `\U` in
        # `C:\Users\...` raises "bad escape". A function replacement is
        # substituted literally, which is what is wanted here.
        template = _PATHS.sub(lambda _m: _paths_block(doc), template, count=1)
        template = _MANUAL.sub(lambda _m: "MANUAL = True", template, count=1)
        template = _DRIVER.sub(lambda _m: body.strip("\n") + "\n\n\n",
                               template, count=1)
    except Exception:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(source)
        return path, "snippet"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(template)
    return path, "template"


def _paths_block(doc):
    paths = []
    for scan in doc.visible_scans():
        if scan.sample.path not in paths:
            paths.append(scan.sample.path)
    lines = ["paths = ["]
    for path in paths:
        lines.append("    r'{}',".format(path))
    lines.append("]")
    return "\n".join(lines)
