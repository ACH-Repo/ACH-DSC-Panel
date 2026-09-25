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

from . import measure
from . import model
from . import style
from . import units

FORMAT = "dscpanel-session"
#: 2: sizes are None until chosen (the house style fills them in), the
#: figure carries its own `style`, and analyses have a `flush`.
#: 3: an axis's `label_gap` is measured from its NUMBERS (it was from the
#: axis line for x and from the window's edge for y), None until chosen.
VERSION = 3


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
                       "label_gap": axis.label_gap}
    labels = []
    for lb in doc.labels:
        labels.append({"text": lb.text, "x": lb.x, "y": lb.y,
                       "colour": lb.colour, "size": lb.size, "bold": lb.bold,
                       "visible": lb.visible, "space": lb.space,
                       "anchor": lb.anchor,
                       "scan": (None if lb.scan is None
                                else [lb.scan.sample.path, lb.scan.seg])})
    return {
        "format": FORMAT,
        "version": VERSION,
        "axes": axes,
        "labels": labels,
        "x_axis": doc.x_axis,
        "x_unit": doc.x_unit,
        "y_unit": doc.y_unit,
        "theme": doc.theme,
        "style": doc.style.chosen(),
        "legend": {"visible": doc.legend.visible, "size": doc.legend.size,
                   "show_frame": doc.legend.show_frame,
                   "sample": doc.legend.sample,
                   "spacing": doc.legend.spacing,
                   "colour": doc.legend.colour, "x": doc.legend.x,
                   "y": doc.legend.y, "space": doc.legend.space,
                   "anchor": doc.legend.anchor},
        "arrow": {"word": arrow.word, "direction": arrow.direction,
                  "x": arrow.x, "y": arrow.y, "length": arrow.length,
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
        sample.scans.append(scan)
        doc.scans.append(scan)
    arrow = state.get("arrow") or {}
    doc.arrow.word = arrow.get("word", doc.arrow.word)
    doc.arrow.direction = arrow.get("direction", doc.arrow.direction)
    doc.arrow.x = float(arrow.get("x", doc.arrow.x))
    doc.arrow.y = float(arrow.get("y", doc.arrow.y))
    doc.arrow.length = float(arrow.get("length", doc.arrow.length))
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
        axis.label_size = _chosen(saved.get("label_size"), "caption_size",
                                  version)
        # Before version 3 the gap was measured from somewhere else, so an
        # old number would put the caption in the wrong place: dropped.
        axis.label_gap = (style.BY_KEY["caption_gap"].clean(
            saved.get("label_gap")) if version >= 3 else None)
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
    for name, value in (state.get("legend") or {}).items():
        if hasattr(doc.legend, name):
            setattr(doc.legend, name, value)
    doc.legend.size = _chosen((state.get("legend") or {}).get("size"),
                              "legend_size", version)
    doc.x_axis = state.get("x_axis", doc.x_axis)
    if state.get("x_unit") in units.TEMPERATURE_UNITS:
        doc.x_unit = state["x_unit"]
    doc.y_unit = state.get("y_unit", doc.y_unit)
    doc.theme = state.get("theme", doc.theme)
    doc.path = str(path)
    return doc, problems
