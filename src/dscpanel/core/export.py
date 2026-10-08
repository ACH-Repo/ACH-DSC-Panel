"""Getting out: the curves as data, and the figure as a script.

Three exports, and each answers a different question.

* `curves_csv` - what is on screen, as numbers. For a colleague, a
  spreadsheet, or a plot in something else entirely.
* `driver_source` / `write_driver` - the arrangement as a
  `DSC_Plotter.py` driver. **This panel is not trying to become the figure
  engine.** The template already draws publication figures in matplotlib,
  with tangents, shaded integrals, molecule images and a run record; what it
  does not have is a way to arrange eight scans by hand. So the panel does
  the arranging and hands the result over: the paths, the segments, the
  colours and the offsets, written as the driver that reproduces them.
* `warnings_for` - what an export must not be allowed to hide. A figure drawn
  while a scan was waiting for its molar mass, or with a scan scaled by a
  factor, is a figure that misleads unless it says so. These lines are
  printed AND stamped into the image: the blinking label can be ignored in
  the window, so the export has to carry the notice with it.
"""

import math
import os
import re

import numpy as np

from .. import branding
from . import figure as figure_module
from . import model
from . import labels
from . import numbers
from . import style
from . import units


def warnings_for(doc, exo=True):
    """Everything an export has to admit to, as short lines.

    `exo=False` leaves out the assumed exotherm direction: an image is not
    stamped with it, the console and the driver are.
    """
    out = []
    for scan, missing in doc.scans_missing():
        out.append("NO {}: {} is not drawn".format(missing.upper(),
                                                   scan.display_name()))
    # A label that asks for a unit it cannot be given without a mass is a
    # missing value, exactly like a per-mole axis without M.
    for analysis, rendered in _rendered_labels(doc):
        for message in rendered.missing():
            out.append("{} ({} on {})".format(
                message, analysis.model_name, analysis.scan.display_name()))
    assumed = sorted({s.name for s in doc.samples
                      if s.exo_source == "assumed"})
    if assumed and exo:
        out.append("EXO DIRECTION ASSUMED (down) for: " + ", ".join(assumed))
    return out


def label_notes(doc):
    """What is odd about the analysis labels without being missing: a unit
    the value cannot be put in, a number typed by hand. Printed on export,
    not stamped: the figure itself draws the right thing."""
    out = []
    for analysis, rendered in _rendered_labels(doc):
        for kind, message in rendered.problems:
            if kind != "missing":
                out.append("{} on {}: {}".format(
                    analysis.model_name, analysis.scan.display_name(),
                    message))
    return out


def _rendered_labels(doc):
    return [(a, labels.render(a, doc)) for a in doc.visible_analyses()]


def curves_csv(doc, path):
    """Every visible scan, in the unit on screen, one column pair per scan.

    Column PAIRS rather than one shared x column, because two scans do not
    share a temperature axis: they were sampled at their own points, and a
    cooling scan runs the other way. Interpolating them onto a common grid
    would be inventing data.

    A mass scan (an SDT run's m%) is a pair like any other, its y named
    "Mass". A flagged sample (NaN) is an EMPTY cell, as in TRIOS's own
    export, never the text "nan".
    """
    # The KEPT part of each: a truncated end is not part of the figure, so
    # it is not part of its numbers either.
    blocks = []
    for scan in doc.visible_scans():
        x, y = scan.kept_curve(doc.x_axis, doc.unit_for(scan), doc.exo,
                               doc.x_unit)
        if x is None:
            continue
        blocks.append((scan, x, y, None))
    if not blocks:
        return None
    columns, headers = [], []
    x_label = ("Temperature/C" if doc.x_axis == model.AXIS_TEMPERATURE
               else "Time/min")
    for scan, x, y, _unused in blocks:
        name = scan.display_name().replace(",", " ")
        columns.append(x)
        headers.append("{} {}".format(name, x_label))
        if y is not None:
            columns.append(y)
            headers.append("{} {}/{}".format(
                name, "Mass" if scan.is_mass
                else "DTG" if scan.is_dtg else "HeatFlow",
                doc.unit_for(scan)))
    rows = max(len(c) for c in columns)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# {} export\n".format(branding.APP_NAME))
        for line in warnings_for(doc):
            fh.write("# {}\n".format(line))
        for scan, _x, _y, _weight in blocks:
            fh.write("# {}: {}, mass {}, M {}, exo {} ({})\n".format(
                scan.display_name(), scan.sample.path,
                scan.sample.mass_text() or "unknown",
                "{:g} g/mol".format(scan.molar_mass) if scan.molar_mass
                else "not given",
                scan.sample.exo, scan.sample.exo_source))
        fh.write(",".join(headers) + "\n")
        for i in range(rows):
            cells = []
            for column in columns:
                cells.append(_cell(column[i]) if i < len(column) else "")
            fh.write(",".join(cells) + "\n")
    return path


def _cell(value):
    """A number as a CSV cell: `%.6g`, and empty for a flagged sample."""
    value = float(value)
    return "{:.6g}".format(value) if np.isfinite(value) else ""


def driver_source(doc):
    """The `DSC_Plotter.py` driver that reproduces what is on screen.

    A whole `def driver():` that the template runs as it stands: it reads the
    files, builds the figure - at EXACTLY the panel's size, with the axes box
    at the panel's margins, when the figure has a size - and draws the lines,
    their truncation and offsets, the x range, the arrow and the style with
    the panel's font sizes and axis sides.

    The template has no `start_plot()` or `finish_plot()`, and `datas` is
    defined here: a driver that called those or left `datas` undefined
    stopped at its second line.
    """
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
    lines.append("MANUAL = True")
    lines.append("")
    lines.append("")
    lines.append("def driver():")
    lines.append("    paths = [")
    for path in paths:
        lines.append("        r'{}',".format(path))
    lines.append("    ]")
    lines.append("    datas = {i: read_tri(HERE / p) "
                 "for i, p in enumerate(paths)}")
    lines.append("    print_infos(datas)")
    family = style.figure_value(doc, "font_family")
    if family:
        # Its own family first; any sans where the machine lacks it.
        lines.append("    plt.rcParams['font.family'] = [{!r}, "
                     "'sans-serif']".format(str(family)))
    lines.append("")
    layout = getattr(doc, "figure", None)
    if (layout is not None and layout.mode == figure_module.MODE_SIZE
            and layout.is_valid()):
        width_in, height_in = layout.inches()
        per_inch = figure_module.PER_INCH[layout.unit]
        left = layout.margin_left / per_inch
        right = layout.margin_right / per_inch
        top = layout.margin_top / per_inch
        bottom = layout.margin_bottom / per_inch
        lines.append("    # The panel's figure, exactly: {:g} x {:g} {}, the "
                     "axes box at its margins.".format(
                         layout.width, layout.height, layout.unit))
        lines.append("    fig = plt.figure(figsize=({:.6f}, {:.6f}))".format(
            width_in, height_in))
        lines.append("    ax = fig.add_axes(({:.6f}, {:.6f}, {:.6f}, "
                     "{:.6f}))".format(
                         left / width_in, bottom / height_in,
                         (width_in - left - right) / width_in,
                         (height_in - top - bottom) / height_in))
        lines.append("    settings['dpi'] = {:d}".format(int(layout.dpi)))
    else:
        lines.append("    fig, ax = plt.subplots(figsize=settings['figsize'], "
                     "layout='constrained')")
    x_axis, y_axis = doc.axes["x"], doc.axes["y"]
    lines.append("    settings['ticklabel_fontsize'] = {:g}".format(
        float(style.value(doc, x_axis, "tick_size"))))
    lines.append("    settings['xlabel_fontsize'] = {:g}".format(
        float(style.value(doc, x_axis, "label_size"))))
    lines.append("    settings['ylabel_fontsize'] = {:g}".format(
        float(style.value(doc, y_axis, "label_size"))))
    y_dim = {units.UNIT_MW: "'Q'", units.UNIT_W_G: "'Qn'",
             units.UNIT_W_MOL: "'Qn'"}.get(doc.y_unit, "'Qn'")
    x_dim = "'T'" if doc.x_axis == model.AXIS_TEMPERATURE else "'t'"
    heat = [s for s in doc.visible_scans() if s.is_heat]
    for scan in heat:
        i = index[os.path.normcase(scan.sample.path)]
        lines.append("    add_line(ax, datas, ({}, {}), color='{}', x={},"
                     " y={}, label={!r})".format(
                         i, scan.seg, scan.colour, x_dim, y_dim,
                         scan.display_name()))
    for scan in heat:
        if scan.is_truncated():
            # The template's own function, with the same fractions: it
            # slices x[int(n * x0):int(n * x1)] exactly as the panel does.
            i = index[os.path.normcase(scan.sample.path)]
            lines.append("    x_truncate(ax, datas, ({}, {}), x0={:.6g}, "
                         "x1={:.6g})".format(i, scan.seg, scan.keep[0],
                                             scan.keep[1]))
    for scan in heat:
        if scan.offset:
            i = index[os.path.normcase(scan.sample.path)]
            lines.append("    y_offset(ax, datas, ({}, {}), {:.6g})".format(
                i, scan.seg, scan.offset))
    if doc.y_unit == units.UNIT_W_MOL:
        lines.append("    # {} showed W/mol; the template's 'Qn' is"
                     .format(branding.APP_NAME))
        lines.append("    # W/g, so each line still needs x M to match.")
    lines.append("    ax.set_xlim({:.6g}, {:.6g})".format(*doc_view_x(doc)))
    view_y = getattr(doc, "view_y_hint", None)
    if view_y:
        lines.append("    ax.set_ylim({:.6g}, {:.6g})".format(*view_y))
    lines.extend(_weight_lines(doc, index, x_dim))
    lines.extend(_offset_marker_lines(doc, index))
    lines.extend(_arrow_lines(doc))
    lines.append("    style(ax)")
    lines.extend(_axis_lines(x_axis, "x"))
    lines.extend(_axis_lines(y_axis, "y"))
    lines.extend(_legend_lines(doc))
    lines.extend(_label_lines(doc))
    if getattr(doc, "images", None):
        lines.append("    # {} picture(s) on the panel's figure are not "
                     "written here.".format(len(doc.images)))
    if getattr(doc, "structures", None):
        lines.append("    # {} structure(s) on the panel's figure are not "
                     "written here: {}".format(
                         len(doc.structures),
                         ", ".join(m.smiles for m in doc.structures)))
    lines.append("    out = HERE / 'dsc.{}'.format(settings['extension'])")
    lines.append("    plt.savefig(out, dpi=settings['dpi'], "
                 "transparent=settings['transparent']) "
                 "if settings['silent'] else plt.show()")
    lines.append("")
    return "\n".join(lines) + "\n"


def _weight_lines(doc, index, x_dim):
    """The weight curves of SDT/TGA runs on a second y axis, `ax2`, as the
    panel draws them: the template's own `add_line` with the
    reader's "Weight Change" (%) or "Weight" (mg), dashed, truncated like
    their scan, at the panel's range and on its side."""
    scans = [s for s in doc.visible_scans() if s.is_mass]
    if not scans:
        return []
    dim = ("'Weight Change'" if doc.weight_unit == model.WEIGHT_PCT
           else "'Weight'")
    axis = doc.axes["y2"]
    out = ["    # The weight on a second axis. An SDT .tri reads right only",
           "    # with a reader from 2026-09-28 or later (flagged arrays).",
           "    ax2 = ax.twinx()"]
    for scan in scans:
        i = index[os.path.normcase(scan.sample.path)]
        out.append("    add_line(ax2, datas, ({}, {}), color='{}', ls={!r}, "
                   "x={}, y={}, label={!r})".format(
                       i, scan.seg, scan.colour,
                       "-", x_dim, dim, scan.display_name()))
        if scan.is_truncated():
            out.append("    x_truncate(ax2, datas, ({}, {}), x0={:.6g}, "
                       "x1={:.6g})".format(i, scan.seg, scan.keep[0],
                                           scan.keep[1]))
    view = getattr(doc, "view_y2_hint", None)
    if view:
        out.append("    ax2.set_ylim({:.6g}, {:.6g})".format(*view))
    out.append("    ax2.set_ylabel({!r}, fontsize={:g})".format(
        mathtext(axis.caption(doc)), float(style.value(doc, axis,
                                                       "label_size"))))
    out.append("    ax2.tick_params(labelsize={:g})".format(
        float(style.value(doc, axis, "tick_size"))))
    side = "right" if doc.axes["y"].side != "right" else "left"
    if side == "left":
        out.append("    ax2.yaxis.set_ticks_position('left')")
        out.append("    ax2.yaxis.set_label_position('left')")
    return out


def _arrow_lines(doc):
    """The template's `add_exo_arrow` with the panel's dimensions, in the
    points it takes them in; its total length `l` is an axes fraction, so it
    is worked out from the axes' height in the driver itself."""
    arrow = doc.arrow
    if not arrow.visible:
        return []
    total = float(arrow.head_length) + float(arrow.tail_length)
    return [
        "    add_exo_arrow(ax, width={:g}, headwidth={:g}, headlength={:g},"
        .format(arrow.tail_width, arrow.head_width, arrow.head_length),
        "                  l={:g} / (ax.get_position().height"
        " * ax.figure.get_figheight() * 72.0))".format(total),
        "    ax.texts[-1].set_fontsize({:g})".format(
            float(style.value(doc, arrow, "size"))),
    ]


def _offset_marker_lines(doc, index):
    """Each y-offset marker, as the template's `mark_spot` - the function
    its `add_yoffset_markers` calls - with the panel's text, so the number
    is written in the same format, at the temperature the panel points at
    (`doc.marker_hint`, from the window)."""
    if not doc.offset_markers or doc.x_axis != model.AXIS_TEMPERATURE:
        return []
    hint = getattr(doc, "marker_hint", None) or {}
    out = []
    for scan in doc.visible_scans():
        marker = scan.marker
        if not marker.visible:
            continue
        typed = (marker.at[1] if marker.at and marker.at[0] == "T"
                 else None)
        celsius, yoff = hint.get(id(marker), (typed, None))
        if celsius is None:
            continue
        i = index[os.path.normcase(scan.sample.path)]
        text = numbers.write(float(scan.offset),
                             style.value(doc, marker, "number_format"),
                             numbers.OFFSET)
        out.append("    mark_spot(ax, datas, ({}, {}), {:.6g}, {!r}, "
                   "yoff_label={:.4g}, flush='left',".format(
                       i, scan.seg, celsius, text,
                       -0.03 if yoff is None else yoff))
        out.append("              color=(.1, .1, .1), fs={:g}, "
                   "arrowcolor=(.1, .1, .1))".format(
                       float(style.value(doc, marker, "size"))))
    return out


#: The panel's anchors as matplotlib's `loc`.
_LOC = {"top left": "upper left", "top": "upper center",
        "top right": "upper right", "left": "center left",
        "center": "center", "right": "center right",
        "bottom left": "lower left", "bottom": "lower center",
        "bottom right": "lower right"}


def mathtext(text):
    r"""The panel's markup as matplotlib mathtext: `*T*` -> `$\mathit{T}$`,
    `_{g}` -> `$_{\mathrm{g}}$`, `^{2}`, `\Delta` -> `$\Delta$`; what is
    already between dollars is mathtext and stays as it is."""
    import re
    out = []
    parts = re.split(r"(?<!\\)(\$[^$]*(?<!\\)\$)", str(text))
    for part in parts:
        if part.startswith("$") and part.endswith("$") and len(part) > 1:
            out.append(part)
            continue
        # Symbols FIRST: the italics and scripts below write backslash
        # commands of their own, which this must not turn over again.
        part = re.sub(r"\\([A-Za-z]+)", lambda m: "$\\" + m.group(1) + "$",
                      part)
        part = re.sub(r"\*([^*]+)\*",
                      lambda m: "$\\mathit{" + m.group(1).replace(" ", "\\ ")
                      + "}$", part)
        part = re.sub(r"([_^])\{([^}]*)\}",
                      lambda m: "$" + m.group(1) + "{\\mathrm{"
                      + m.group(2).replace(" ", "\\ ") + "}}$", part)
        out.append(part)
    return "".join(out).replace("$$", "")


def _ha_va(anchor):
    anchor = str(anchor or "center")
    ha = "left" if "left" in anchor else ("right" if "right" in anchor
                                          else "center")
    va = "top" if "top" in anchor else ("bottom" if "bottom" in anchor
                                        else "center")
    return ha, va


def _placed(doc, artist):
    """`(x, y, transform)` of an artist for matplotlib: axes fractions
    (the panel's y runs from the TOP), or data - in degC, as the template
    plots."""
    # A label with a parent stands as far up as its scan has moved since
    # it was placed (`TextLabel.follow`); in axes fractions that is the
    # distance over the y range the figure is framed at.
    follow = artist.follow() if hasattr(artist, "follow") else 0.0
    # A label hanging from its curve is placed where the panel draws it,
    # in data units (`MainWindow` hands the places over as a hint).
    hung = (getattr(doc, "label_hints", None) or {}).get(id(artist))
    if hung is not None:
        x = float(hung[0])
        if doc.x_axis == model.AXIS_TEMPERATURE:
            x = float(units.to_celsius(x, doc.x_unit))
        return x, float(hung[1]), "ax.transData"
    if getattr(artist, "space", "relative") == model.SPACE_DATA:
        x = float(artist.x)
        if doc.x_axis == model.AXIS_TEMPERATURE:
            x = float(units.to_celsius(x, doc.x_unit))
        return x, float(artist.y) + follow, "ax.transData"
    view_y = getattr(doc, "view_y_hint", None)
    lift = (follow / (view_y[1] - view_y[0])
            if follow and view_y and view_y[1] > view_y[0] else 0.0)
    return float(artist.x), 1.0 - float(artist.y) + lift, "ax.transAxes"


def _legend_lines(doc):
    """The panel's legend as `ax.legend`, at its place, with its size,
    frame, sample length, spacing and line width. matplotlib turns no
    legend, so a rotation is noted and left out."""
    legend = doc.legend
    if not legend.visible or not legend.entries(doc):
        return []
    x, y, transform = _placed(doc, legend)
    size = float(style.value(doc, legend, "size"))
    out = []
    handles = ""
    if any(entry.is_mass for entry, _text in legend.entries(doc)):
        # The weight lines are on ax2: one legend for both axes.
        out.append("    handles = (ax.get_legend_handles_labels()[0]"
                   " + ax2.get_legend_handles_labels()[0])")
        handles = "handles=handles, "
    out += ["    leg = ax.legend({}loc={!r}, bbox_to_anchor=({:.4f}, {:.4f}),"
            .format(handles, _LOC.get(legend.anchor, "center"), x, y),
           "                    bbox_transform={}, frameon={}, fontsize={:g},"
           .format(transform, bool(legend.show_frame), size),
           "                    handlelength={:.3g}, labelspacing={:.3g})"
           .format(float(legend.sample) * 0.75 / size,
                   max(0.0, float(legend.spacing) - 1.0) * 1.5)]
    if legend.line_width:
        out.append("    for line in leg.get_lines(): line.set_linewidth("
                   "{:g})".format(float(legend.line_width) * 0.75))
    if legend.colour not in (None, "", "auto"):
        out.append("    for text in leg.get_texts(): text.set_color({!r})"
                   .format(legend.colour))
    if legend.rotation:
        out.append("    # the panel's legend is turned {:g} degrees; "
                   "matplotlib does not turn legends".format(legend.rotation))
    return out


def _flush_ha(label):
    """matplotlib's `ha` for a label's flush (the panel's `_flush_of`)."""
    chosen = getattr(label, "flush", None)
    if chosen in ("left", "right", "center"):
        return chosen
    anchor = str(getattr(label, "anchor", "center"))
    return ("left" if "left" in anchor else
            "right" if "right" in anchor else "center")


def _label_lines(doc):
    """Each label the user added, as `ax.text`: text (markup as mathtext),
    place, anchor, size, weight, colour and rotation."""
    out = []
    for label in doc.labels:
        if not label.visible:
            continue
        x, y, transform = _placed(doc, label)
        ha, va = _ha_va(label.anchor)
        hung = (getattr(doc, "label_hints", None) or {}).get(id(label))
        tip = None
        if hung is not None and len(hung) == 4:
            # a note hanging from its curve: its flush edge over the point
            tip = (hung[2], hung[3])
            ha = _flush_ha(label)
            va = "center"
        colour = label.colour
        if colour in (None, "", "auto"):
            colour = label.scan.colour if label.scan is not None else "#1a1a1a"
        if (getattr(label, "leader", None)
                and doc.x_axis == model.AXIS_TEMPERATURE):
            # A note: matplotlib's annotate, the arrow from the text to the
            # point it names (in degC, as the template plots, and as far up
            # as its scan has moved).
            out.append("    ax.annotate({!r}, xy=({:.6g}, {:.6g}), "
                       "xycoords='data',".format(
                           mathtext(label.text),
                           float(tip[0] if tip else label.leader[0]),
                           float(tip[1] if tip else
                                 label.leader[1] + label.follow())))
            out.append("                xytext=({:.4f}, {:.4f}), "
                       "textcoords={!r},".format(
                           x, y, "axes fraction"
                           if transform == "ax.transAxes" else "data"))
            out.append("                ha={!r}, va={!r}, fontsize={:g}, "
                       "color={!r},".format(
                           ha, va, float(style.value(doc, label, "size")),
                           colour))
            out.append("                fontweight={!r}, rotation={:g},"
                       .format("bold" if label.bold else "normal",
                               float(label.rotation or 0.0)))
            out.append("                arrowprops=dict(arrowstyle='-|>', "
                       "color={!r}, lw=0.8, shrinkA=2, shrinkB=0, "
                       "mutation_scale=8))".format(colour))
            continue
        out.append("    ax.text({:.4f}, {:.4f}, {!r}, transform={},".format(
            x, y, mathtext(label.text), transform))
        out.append("            ha={!r}, va={!r}, fontsize={:g}, color={!r},"
                   .format(ha, va, float(style.value(doc, label, "size")),
                           colour))
        out.append("            fontweight={!r}, rotation={:g}, "
                   "rotation_mode='anchor')".format(
                       "bold" if label.bold else "normal",
                       float(label.rotation or 0.0)))
    return out


def _axis_lines(axis, which):
    """matplotlib for an axis on its other side, without numbers or
    without a caption - as the panel draws it."""
    out = []
    letter = which
    far = "top" if which == "x" else "right"
    near = "bottom" if which == "x" else "left"
    if getattr(axis, "side", near) != near:
        far = near
    # The frame and the ticks as the panel draws them: the opposite spine,
    # its ticks (no numbers), the steps and the lengths, in points.
    if not getattr(axis, "mirror", True):
        out.append("    ax.spines['{}'].set_visible(False)".format(far))
    mirrored = getattr(axis, "mirror", True) and getattr(axis, "mirror_ticks",
                                                          True)
    out.append("    ax.tick_params(axis='{}', which='both', {}={}, "
               "direction='{}')".format(letter, far, mirrored,
                                        "in" if axis.ticks_inward else "out"))
    out.append("    ax.tick_params(axis='{}', which='major', length={:g})"
               .format(letter, float(axis.tick_length) * 0.75))
    out.append("    ax.tick_params(axis='{}', which='minor', length={:g})"
               .format(letter, float(axis.minor_length) * 0.75))
    if getattr(axis, "major_step", None):
        out.append("    from matplotlib.ticker import MultipleLocator")
        out.append("    ax.{}axis.set_major_locator(MultipleLocator({:g}))"
                   .format(letter, float(axis.major_step)))
    if not axis.minor_ticks or int(axis.minor_count) < 2:
        out.append("    from matplotlib.ticker import NullLocator")
        out.append("    ax.{}axis.set_minor_locator(NullLocator())"
                   .format(letter))
    else:
        out.append("    ax.{}axis.set_minor_locator(AutoMinorLocator({:d}))"
                   .format(letter, int(axis.minor_count)))
    spec = getattr(axis, "number_format", None)
    if spec:
        out.append("    from matplotlib.ticker import FormatStrFormatter")
        out.append("    ax.{}axis.set_major_formatter(FormatStrFormatter("
                   "{!r}))".format(which, spec))
    side = getattr(axis, "side", "bottom" if which == "x" else "left")
    if which == "x" and side == "top":
        out.append("    ax.xaxis.tick_top()")
        out.append("    ax.xaxis.set_label_position('top')")
    if which == "y" and side == "right":
        out.append("    ax.yaxis.tick_right()")
        out.append("    ax.yaxis.set_label_position('right')")
    if not getattr(axis, "show_numbers", True):
        names = (("labelbottom", "labeltop") if which == "x"
                 else ("labelleft", "labelright"))
        out.append("    ax.tick_params(axis='{}', {}=False, {}=False)".format(
            which, names[0], names[1]))
    if not axis.visible:
        out.append("    ax.set_{}label('')".format(which))
    return out


def doc_view_x(doc):
    """The x range the panel is showing, or the data range."""
    view = getattr(doc, "view_x_hint", None)
    if view:
        return view
    lo, hi = None, None
    for scan in doc.visible_scans():
        x, _y = scan.kept_curve(doc.x_axis, doc.unit_for(scan), doc.exo,
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


# ------------------------------------------------ TRIOS's Excel export
#: TRIOS's Details sheet, row by row: what it says, and where the reader
#: keeps it - a .txt export's own header line, else a .tri's metadata
#: string. "Filename" is the export's own name (`trios_name`).
TRIOS_DETAILS = (
    ("Filename", ()),
    ("Instrument name", ("Instrument name", "instrumentname")),
    ("Operator", ("Operator", "operator")),
    ("rundate", ("rundate",)),
    ("Sample name", ("Sample name", "samplename")),
    ("proceduresegments", ("proceduresegments",)),
)

#: Characters an Excel sheet name may not hold.
_SHEET_FORBIDDEN = re.compile(r"[/\\?*\[\]:]")


def trios_name(sample):
    """The name TRIOS gives an export of `sample`'s file: the file's name
    without its extension, in lower case."""
    return os.path.splitext(os.path.basename(str(sample.path)))[0].lower()


def trios_step_name(prog):
    """A step's name as TRIOS writes it in an export: without the ` #n`
    the reader numbers the segments with."""
    return re.sub(r"\s+#\d+\s*$", "", str(prog or "")).strip()


def trios_sheet_names(steps):
    """Excel sheet names for step names, as TRIOS makes them: the name
    without the characters a sheet name may not hold, `-2`, `-3`... after
    a repeat, and its LAST 31 characters when longer (Excel's limit:
    "Ramp 10.00 degC/min to 250.0000 degC-2" becomes "mp 10.00 ...-2")."""
    counts, used, out = {}, set(), []
    for step in steps:
        base = _SHEET_FORBIDDEN.sub("", str(step)) or "Step"
        counts[base] = counts.get(base, 0) + 1
        name = base if counts[base] == 1 else "{}-{}".format(base,
                                                              counts[base])
        name = name[-31:]
        extra = 1
        while name.lower() in used:           # Excel's names ignore case
            extra += 1
            name = "{}-{}".format(base, counts[base] + extra)[-31:]
        used.add(name.lower())
        out.append(name)
    return out


def trios_step_columns(sample, seg):
    """`(names, units, columns)` of one step as TRIOS's Excel export
    writes it: Time and Temperature, the heat flow normalised to the
    sample mass (W/g; in mW where the run has no mass), and an SDT run's
    weight in % - which TRIOS calls "Weight" there, the reader "Weight
    Change". Every sample of the step, in the reader's units - the
    flagged tail the plot leaves off as well (`Sample` keeps it as
    `tail`), where TRIOS writes the time and an empty cell."""
    step = sample.data["numdata"][seg]
    dims, step_units, nums = step["dims"], step["units"], step["nums"]
    tail = step.get("tail")
    if tail is not None and len(tail):
        nums = np.vstack([nums, tail])

    def take(name):
        if name not in dims:
            return None
        k = dims.index(name)
        return step_units[k], np.asarray(nums[:, k], dtype=float)

    names, unit_row, columns = [], [], []
    for name in ("Time", "Temperature"):
        found = take(name)
        if found is not None:
            names.append(name)
            unit_row.append(found[0])
            columns.append(found[1])
    flow = take("Heat Flow (Normalized)")
    if flow is not None:
        names.append("Heat Flow (Normalized)")
        unit_row.append(flow[0])
        columns.append(flow[1])
    else:
        flow = take("Heat Flow")
        if flow is not None:
            watts = flow[0] == "W"
            names.append("Heat Flow")
            unit_row.append("mW" if watts else flow[0])
            columns.append(flow[1] * 1000.0 if watts else flow[1])
    weight = take("Weight Change")
    if weight is not None:
        names.append("Weight")
        unit_row.append(weight[0])
        columns.append(weight[1])
    return names, unit_row, columns


def trios_details(sample, name):
    """The Details sheet's rows for `sample`, its export called `name`."""
    head = sample.data.get("head") or {}
    rows = []
    for title, keys in TRIOS_DETAILS:
        if not keys:
            rows.append((title, name))
            continue
        value = next((head[k] for k in keys if head.get(k)), "")
        rows.append((title, str(value)))
    return rows


def trios_excel_groups(doc):
    """`[(sample, [segment, ...]), ...]`: what TRIOS-style workbooks hold -
    one per file, with every segment of it that has a curve on the figure
    (the selected curves' only, when any is selected), in the run's
    order."""
    shown = [s for s in doc.scans if s.visible]
    chosen = [s for s in shown if s.selected] or shown
    groups = []
    for sample in doc.samples:
        segs = sorted({s.seg for s in chosen if s.sample is sample})
        if segs:
            groups.append((sample, segs))
    return groups


def write_trios_excel(sample, segments, path):
    """`sample`'s `segments` as TRIOS's Excel export lays them out: a
    Details sheet (Filename - this workbook's name - instrument name,
    operator, run date, sample name, the procedure), then one sheet per
    step - its name, the column names, the units, then the samples. Plain
    cells and numbers, as TRIOS writes them; an empty sample is an empty
    cell. Written as .xlsx. Returns the path."""
    from openpyxl import Workbook
    name = os.path.splitext(os.path.basename(path))[0]
    book = Workbook(write_only=True)
    details = book.create_sheet("Details")
    for row in trios_details(sample, name):
        details.append(list(row))
    numdata = sample.data["numdata"]
    steps = [trios_step_name(numdata[seg].get("prog")) for seg in segments]
    for seg, step, title in zip(segments, steps, trios_sheet_names(steps)):
        sheet = book.create_sheet(title)
        names, unit_row, columns = trios_step_columns(sample, seg)
        sheet.append([step] + [None] * (len(names) - 1))
        sheet.append(names)
        sheet.append(unit_row)
        if not columns:
            continue
        table = np.column_stack(columns)
        for values in table.tolist():
            sheet.append([v if v == v and abs(v) != float("inf") else None
                          for v in values])
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        os.makedirs(folder)
    book.save(path)
    return path


# ---------------------------------------------- the measured data as text
def _data_head(sample):
    """The lines at the top of a data export: the file, then what the run
    records, as "Details..." shows it, and its exotherm direction."""
    from . import profile
    lines = ["{}, exported by {}".format(os.path.basename(str(sample.path)),
                                         branding.APP_NAME),
             "File: {}".format(sample.path)]
    for title, value in profile.details(sample):
        lines.append("{}: {}".format(title, value))
    lines.append("Exotherm: {} ({})".format(sample.exo, sample.exo_source))
    return [" ".join(str(line).split()) for line in lines]


def _number(value):
    """A sample as text: 8 significant figures (all an instrument's float
    holds), "." the decimal point; empty for an empty one."""
    return "%.8g" % value if math.isfinite(value) else ""


def data_text_name(sample):
    """The name a data export of `sample` takes: its file's, as .csv."""
    return os.path.splitext(os.path.basename(str(sample.path)))[0] + ".csv"


def write_data_text(sample, segments, path):
    """`sample`'s `segments` as tab-separated text, our own format: what the
    run records on lines commented out with "#" (each segment's step name
    last), a header row - "Segment", then each column's name and unit, as
    "Temperature (degC)" - then every sample of each segment, its number
    first. The columns of the Excel export (`trios_step_columns`): a
    segment without one has empty cells there, as has an empty sample.
    UTF-8. Returns the path."""
    numdata = sample.data["numdata"]
    heads, tables = [], []
    for seg in segments:
        names, unit_row, columns = trios_step_columns(sample, seg)
        named = []
        for name, unit, column in zip(names, unit_row, columns):
            head = "{} ({})".format(name, unit) if unit else name
            if head not in heads:
                heads.append(head)
            named.append((head, column))
        tables.append((seg, dict(named)))
    lines = ["# " + line for line in _data_head(sample)]
    for seg in segments:
        lines.append("# Segment {}: {}".format(
            seg + 1, trios_step_name(numdata[seg].get("prog"))))
    lines.append("\t".join(["Segment"] + heads))
    for seg, named in tables:
        count = max([len(c) for c in named.values()] or [0])
        empty = np.full(count, np.nan)
        columns = [np.asarray(named.get(head, empty), dtype=float).tolist()
                   for head in heads]
        number = str(seg + 1)
        for row in zip(*columns):
            lines.append("\t".join([number] + [_number(v) for v in row]))
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return path
