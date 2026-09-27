"""Saving and reopening an arrangement.

A figure made of eight scans is half an hour of dragging, colouring and
typing molar masses, and it is worth nothing if it cannot be reopened. So the
arrangement is a file: which measurements, which segments of them, where each
one sits, what colour it is, what M it was given, where the arrow is.

**The measurements themselves are NOT copied in.** A session stores paths and
reads the files again, which keeps a session small and keeps one copy of the
data on disk - and means a re-run of the same sample, saved over the same
path, is picked up by reopening the session. A file that has moved is
reported by name instead of failing the whole load, because losing seven
scans over one missing path would be the worst possible behaviour.

UI-free: `load` takes the reader as an argument, so this module never imports
the reader or a window and is testable with a stub.
"""

import json
import os

from . import figure as figure_module
from . import labels
from . import measure
from . import model
from . import numbers
from . import style
from . import units

FORMAT = "dscpanel-session"
#: 2: sizes are None until chosen (the house style fills them in), the
#: figure carries its own `style`, and analyses have a `flush`.
#: 3: an axis's `label_gap` is measured from its NUMBERS (it was from the
#: axis line for x and from the window's edge for y), None until chosen.
VERSION = 5


def view_to_state(view):
    """The framing as plain data (lists), or None."""
    if not view:
        return None
    return {"x": list(view["x"]) if view.get("x") else None,
            "y": list(view["y"]) if view.get("y") else None,
            "context": list(view.get("context") or ())}


def _view_from(saved):
    """The framing back as the plot keeps it (tuples), or None."""
    if not isinstance(saved, dict):
        return None
    try:
        return {"x": tuple(float(v) for v in saved["x"]) if saved.get("x")
                else None,
                "y": tuple(float(v) for v in saved["y"]) if saved.get("y")
                else None,
                "context": tuple(saved.get("context") or ())}
    except (TypeError, ValueError, KeyError):
        return None


def _marker_at(value):
    """A stored marker place: None, ("i", sample) or ("T", celsius)."""
    try:
        kind, number = value
        if kind == "i":
            return ("i", int(number))
        if kind == "T":
            return ("T", float(number))
    except (TypeError, ValueError):
        pass
    return None


def _number_or_none(value):
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _chosen(value, key, version):
    """A stored size, or None where the file did not really choose it.

    A version-1 file wrote EVERY size, chosen or not, because there was no
    house style to fall back on. Read literally, each of those would pin the
    object and the user's defaults would never reach a figure saved before
    they existed. So in a version-1 file a value equal to the built-in one is
    read as "not chosen" - it is what the object carried when nobody had
    touched it. Later files store None themselves.
    """
    setting = style.BY_KEY[key]
    value = setting.clean(value)
    if (value is not None and version < 2
            and value == _VERSION_1_DEFAULTS.get(key)):
        return None
    return value


#: What every object carried in a version-1 file when nobody had touched it:
#: the built-ins of THAT time, not today's, which have since moved.
_VERSION_1_DEFAULTS = {"analysis_size": 9.0, "caption_size": 10.0,
                       "tick_size": 8.0, "legend_size": 9.0,
                       "label_size": 10.0, "line_width": 1.0}


def _analysis_state(analysis):
    """One analysis: how it is drawn, and - if it was made HERE - how to
    make it again.

    A file's own analyses come back with the file, so only their styling is
    stored, matched up again by `key`. One measured in the panel exists
    nowhere else, so its model and its two cursors are stored too, and it is
    RECOMPUTED from the re-read file on load - the same rule as the curves:
    a session keeps the arrangement, never a copy of the numbers.
    """
    state = {"key": analysis.key(), "visible": analysis.visible,
             "colour": analysis.colour, "label": analysis.label,
             "label_dy": analysis.label_dy, "shade": analysis.shade,
             "label_size": analysis.label_size, "flush": analysis.flush,
             "show_interval": analysis.show_interval,
             "number_format": analysis.number_format,
             "label_at": analysis.label_at, "z": analysis.z,
             "attribution": analysis.attribution,
             "source": analysis.source}
    if analysis.source == "panel":
        state["model"] = analysis.model_name
        state["cursors"] = analysis.cursors()
        state["span"] = list(analysis.span) if analysis.span else None
    return state


def _restore_analysis(analysis, saved, version):
    analysis.visible = bool(saved.get("visible", False))
    analysis.colour = saved.get("colour", "auto")
    analysis.label = saved.get("label")
    stored_dy = saved.get("label_dy", analysis.label_dy)
    analysis.label_dy = None if stored_dy is None else float(stored_dy)
    analysis.shade = bool(saved.get("shade", True))
    analysis.label_size = _chosen(saved.get("label_size"), "analysis_size",
                                  version)
    flush = saved.get("flush")
    analysis.flush = flush if flush in style.FLUSHES else None
    analysis.show_interval = bool(saved.get("show_interval", True))
    analysis.attribution = saved.get("attribution", analysis.attribution)
    # With its unit, if it names one (`%.0f degF`): a unit-less read
    # dropped such a format on every reopen.
    analysis.number_format = labels.normalise_format(
        saved.get("number_format"))
    analysis.label_at = _number_or_none(saved.get("label_at"))
    analysis.z = _number_or_none(saved.get("z"))
    if version < 5 and measure.is_legacy_label(analysis.label):
        # Before round 15 a panel analysis was GIVEN a label with its
        # number written in ("*T*_{onset} = 61.1 degC"), and a version-4
        # file can still hold one whose number went stale. Nobody typed
        # that shape, so it goes back to the default template, whose number
        # follows the measurement; any other label stays the user's.
        analysis.label = None


def to_state(doc):
    """The document as plain data, ready for `json.dump`."""
    samples = []
    for sample in doc.samples:
        samples.append({
            "path": sample.path,
            "molar_mass": sample.molar_mass,
            "exo": sample.exo,
            "exo_source": sample.exo_source,
        })
    scans = []
    for scan in doc.scans:
        scans.append({
            "path": scan.sample.path,
            "seg": scan.seg,
            "colour": scan.colour,
            "offset": scan.offset,
            "line_width": scan.line_width,
            "keep": list(scan.keep),
            "label": scan.label,
            "visible": scan.visible,
            "analyses": [_analysis_state(a) for a in scan.analysis_objects],
            "molar_mass_override": scan.molar_mass_override,
            "z": scan.z,
            "marker": {"z": scan.marker.z,"at": (list(scan.marker.at) if scan.marker.at
                              else None),
                       "dy": scan.marker.dy,
                       "number_format": scan.marker.number_format,
                       "size": scan.marker.size,
                       "colour": scan.marker.colour,
                       "visible": scan.marker.visible},
        })
    arrow = doc.arrow
    axes = {}
    for which, axis in doc.axes.items():
        axes[which] = {"label": axis.label, "show_grid": axis.show_grid,
                       "minor_ticks": axis.minor_ticks,
                       "ticks_inward": axis.ticks_inward,
                       "label_size": axis.label_size,
                       "tick_size": axis.tick_size,
                       "label_along": axis.label_along,
                       "number_format": axis.number_format,
                       "mirror": axis.mirror,
                       "mirror_ticks": axis.mirror_ticks,
                       "major_step": axis.major_step,
                       "minor_count": axis.minor_count,
                       "tick_length": axis.tick_length,
                       "minor_length": axis.minor_length,
                       "side": axis.side,
                       "show_numbers": axis.show_numbers,
                       "visible": axis.visible,
                       "label_gap": axis.label_gap}
    labels = []
    for lb in doc.labels:
        labels.append({"text": lb.text, "x": lb.x, "y": lb.y,
                       "colour": lb.colour, "size": lb.size, "bold": lb.bold,
                       "visible": lb.visible, "space": lb.space,
                       "anchor": lb.anchor, "rotation": lb.rotation,
                       "z": lb.z,
                       "scan": (None if lb.scan is None
                                else [lb.scan.sample.path, lb.scan.seg])})
    return {
        "format": FORMAT,
        "version": VERSION,
        "axes": axes,
        "labels": labels,
        "images": [{"png": im.png, "x": im.x, "y": im.y,
                    "space": im.space, "anchor": im.anchor,
                    "rotation": im.rotation, "width": im.width,
                    "z": im.z, "visible": im.visible}
                   for im in doc.images],
        "x_axis": doc.x_axis,
        "x_unit": doc.x_unit,
        "y_unit": doc.y_unit,
        "theme": doc.theme,
        "offset_markers": bool(doc.offset_markers),
        "view": view_to_state(doc.view),
        "style": doc.style.chosen(),
        "figure": doc.figure.to_state(),
        "legend": {"visible": doc.legend.visible, "size": doc.legend.size,
                   "show_frame": doc.legend.show_frame,
                   "sample": doc.legend.sample,
                   "spacing": doc.legend.spacing,
                   "colour": doc.legend.colour, "x": doc.legend.x,
                   "rotation": doc.legend.rotation, "z": doc.legend.z,
                   "line_width": doc.legend.line_width,
                   "y": doc.legend.y, "space": doc.legend.space,
                   "anchor": doc.legend.anchor},
        "arrow": {"word": arrow.word, "direction": arrow.direction,
                  "x": arrow.x, "y": arrow.y,
                  "head_length": arrow.head_length,
                  "head_width": arrow.head_width,
                  "tail_width": arrow.tail_width,
                  "tail_length": arrow.tail_length,
                  "lock": arrow.lock, "size": arrow.size, "z": arrow.z,
                  "colour": arrow.colour, "visible": arrow.visible,
                  "space": arrow.space, "anchor": arrow.anchor},
        "samples": samples,
        "scans": scans,
    }


def save(doc, path):
    """Write the session. The document remembers where it went."""
    state = to_state(doc)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)
    doc.path = str(path)
    return path


def load(path, read_sample):
    """Rebuild a document from a session file.

    Returns `(document, problems)`. `problems` names every file that could not
    be read, so the window can say so in one line and still show everything
    else.
    """
    with open(path, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    if state.get("format") != FORMAT:
        raise ValueError("not a {} file".format(FORMAT))
    doc = model.Document()
    version = int(state.get("version", 1) or 1)
    problems = []
    by_path = {}
    for key, raw in (state.get("style") or {}).items():
        if key in style.BY_KEY and style.BY_KEY[key].figure:
            setattr(doc.style, key, style.BY_KEY[key].clean(raw))
    # A session keeps its OWN figure size; one saved before there was such
    # a thing follows the window, as it did then - not today's default.
    doc.figure = figure_module.FigureLayout().load_state(
        state.get("figure") or {"mode": figure_module.MODE_WINDOW})
    for entry in state.get("samples", []):
        try:
            sample = read_sample(entry["path"])
        except Exception as exc:
            problems.append("{}: {}".format(
                os.path.basename(entry.get("path", "?")), exc))
            continue
        if entry.get("molar_mass"):
            sample.molar_mass = float(entry["molar_mass"])
        if entry.get("exo") in (units.EXO_DOWN, units.EXO_UP):
            sample.exo = entry["exo"]
            sample.exo_source = entry.get("exo_source", sample.exo_source)
        doc.samples.append(sample)
        by_path[os.path.normcase(sample.path)] = sample
    for entry in state.get("scans", []):
        sample = by_path.get(os.path.normcase(entry.get("path", "")))
        if sample is None:
            continue
        seg = int(entry.get("seg", 0))
        if seg >= sample.segment_count():
            problems.append("{}: segment {} is gone".format(sample.name,
                                                            seg + 1))
            continue
        scan = model.Scan(doc._next_id(), sample, seg,
                          entry.get("colour")
                          or model.PALETTE[len(doc.scans) % len(model.PALETTE)])
        scan.offset = float(entry.get("offset", 0.0))
        scan.line_width = _chosen(entry.get("line_width"), "line_width",
                                  version)
        keep = entry.get("keep") or (0.0, 1.0)
        try:
            start, end = float(keep[0]), float(keep[1])
        except (TypeError, ValueError, IndexError):
            start, end = 0.0, 1.0
        if 0.0 <= start < end <= 1.0:
            scan.keep = (start, end)
        scan.label = entry.get("label")
        scan.visible = bool(entry.get("visible", True))
        stored = entry.get("analyses") or []
        wanted = {item.get("key"): item for item in stored
                  if item.get("source") != "panel"}
        for analysis in scan.analysis_objects:
            saved = wanted.get(analysis.key())
            if saved:
                _restore_analysis(analysis, saved, version)
        for saved in stored:
            if saved.get("source") != "panel":
                continue
            cursors = saved.get("cursors") or []
            made = None
            if len(cursors) == 2:
                made = measure.run(saved.get("model", ""), scan,
                                   float(cursors[0]), float(cursors[1]),
                                   span=saved.get("span"))
            if made is None:
                problems.append("{}: {} could not be measured again".format(
                    scan.display_name(), saved.get("model", "an analysis")))
                continue
            _restore_analysis(made, saved, version)
        scan.molar_mass_override = entry.get("molar_mass_override")
        scan.z = _number_or_none(entry.get("z"))
        marker = entry.get("marker") or {}
        scan.marker.at = _marker_at(marker.get("at"))
        scan.marker.number_format = labels.normalise_format(
            marker.get("number_format"))
        scan.marker.dy = _number_or_none(marker.get("dy"))
        scan.marker.size = _chosen(marker.get("size"), "offset_marker_size",
                                   version)
        scan.marker.colour = marker.get("colour", "auto")
        scan.marker.visible = bool(marker.get("visible", True))
        scan.marker.z = _number_or_none(marker.get("z"))
        sample.scans.append(scan)
        doc.scans.append(scan)
    arrow = state.get("arrow") or {}
    doc.arrow.word = arrow.get("word", doc.arrow.word)
    doc.arrow.direction = arrow.get("direction", doc.arrow.direction)
    doc.arrow.x = float(arrow.get("x", doc.arrow.x))
    doc.arrow.y = float(arrow.get("y", doc.arrow.y))
    # Its dimensions in points since round 14. An older session's `length`
    # (a fraction of the plot height) has no honest conversion, so the
    # template's proportions are what it opens with.
    for name in ("head_length", "head_width", "tail_width", "tail_length"):
        value = _number_or_none(arrow.get(name))
        if value is not None and value > 0:
            setattr(doc.arrow, name, value)
    if arrow.get("lock") in model.ARROW_LOCKS:
        doc.arrow.lock = arrow["lock"]
    doc.arrow.size = _chosen(arrow.get("size"), "arrow_size", version)
    doc.arrow.z = _number_or_none(arrow.get("z"))
    doc.arrow.colour = arrow.get("colour", doc.arrow.colour)
    doc.arrow.visible = bool(arrow.get("visible", True))
    doc.arrow.space = arrow.get("space", doc.arrow.space)
    doc.arrow.anchor = arrow.get("anchor", doc.arrow.anchor)
    for which, saved in (state.get("axes") or {}).items():
        axis = doc.axes.get(which)
        if axis is None:
            continue
        for name, value in saved.items():
            if hasattr(axis, name):
                setattr(axis, name, value)
        axis.number_format = numbers.normalise(saved.get("number_format"))
        step = _number_or_none(saved.get("major_step"))
        axis.major_step = step if step and step > 0 else None
        try:
            axis.minor_count = max(1, int(saved.get("minor_count", 5)))
        except (TypeError, ValueError):
            axis.minor_count = 5
        for name, default in (("tick_length", 7.0), ("minor_length", 3.0)):
            value = _number_or_none(saved.get(name))
            setattr(axis, name, value if value is not None and value >= 0
                    else default)
        axis.mirror = bool(saved.get("mirror", True))
        axis.mirror_ticks = bool(saved.get("mirror_ticks", True))
        axis.label_size = _chosen(saved.get("label_size"), "caption_size",
                                  version)
        # Before version 3 the gap was measured from somewhere else, so an
        # old number would put the caption in the wrong place: dropped.
        axis.label_gap = (style.BY_KEY["caption_gap"].clean(
            saved.get("label_gap")) if version >= 3 else None)
        if saved.get("side") not in (("bottom", "top") if which == "x"
                                     else ("left", "right")):
            axis.side = "bottom" if which == "x" else "left"
        axis.tick_size = _chosen(saved.get("tick_size"), "tick_size", version)
    for saved in state.get("labels") or []:
        owner = None
        owned = saved.get("scan")
        if owned:
            for scan in doc.scans:
                if (os.path.normcase(scan.sample.path)
                        == os.path.normcase(owned[0])
                        and scan.seg == owned[1]):
                    owner = scan
                    break
        label = doc.add_label(saved.get("text", "Label"),
                              float(saved.get("x", 0.5)),
                              float(saved.get("y", 0.5)), owner)
        label.colour = saved.get("colour", "auto")
        label.size = _chosen(saved.get("size"), "label_size", version)
        label.bold = bool(saved.get("bold", False))
        label.visible = bool(saved.get("visible", True))
        label.space = saved.get("space", label.space)
        label.anchor = saved.get("anchor", label.anchor)
        label.rotation = float(_number_or_none(saved.get("rotation")) or 0.0)
        label.z = _number_or_none(saved.get("z"))
    for saved in state.get("images") or []:
        if not saved.get("png"):
            continue
        image = model.ImageArtist(doc._next_id(), saved["png"],
                                  float(saved.get("x", 0.5)),
                                  float(saved.get("y", 0.5)),
                                  float(saved.get("width", 160.0)))
        image.space = saved.get("space", image.space)
        image.anchor = saved.get("anchor", image.anchor)
        image.rotation = float(_number_or_none(saved.get("rotation")) or 0.0)
        image.z = _number_or_none(saved.get("z"))
        image.visible = bool(saved.get("visible", True))
        doc.images.append(image)
    for name, value in (state.get("legend") or {}).items():
        if hasattr(doc.legend, name):
            setattr(doc.legend, name, value)
    doc.legend.rotation = float(
        _number_or_none((state.get("legend") or {}).get("rotation")) or 0.0)
    doc.legend.z = _number_or_none((state.get("legend") or {}).get("z"))
    if version < 5:
        # The frame was on by default until round 17, so an older file's
        # True was the default and not a choice; it follows the new one.
        doc.legend.show_frame = False
    doc.legend.size = _chosen((state.get("legend") or {}).get("size"),
                              "legend_size", version)
    doc.x_axis = state.get("x_axis", doc.x_axis)
    if state.get("x_unit") in units.TEMPERATURE_UNITS:
        doc.x_unit = state["x_unit"]
    doc.y_unit = state.get("y_unit", doc.y_unit)
    doc.theme = state.get("theme", doc.theme)
    doc.offset_markers = bool(state.get("offset_markers", False))
    doc.view = _view_from(state.get("view"))
    doc.path = str(path)
    return doc, problems
