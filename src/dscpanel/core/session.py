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
scans over one missing path would be the worst possible behaviour - and
what the session held of it is KEPT (`model.MissingSource`): saved again as
it was, and back on the figure once the file is found.

UI-free: `load` takes the reader as an argument, so this module never imports
the reader or a window and is testable with a stub.
"""

import base64
import difflib
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import zlib

from . import dtg
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
VERSION = 8


def view_to_state(view):
    """The framing as plain data (lists), or None."""
    if not view:
        return None
    return {"x": list(view["x"]) if view.get("x") else None,
            "y": list(view["y"]) if view.get("y") else None,
            "y2": list(view["y2"]) if view.get("y2") else None,
            # The weight range is a number of % or of mg: which, beside it
            # (the plot restores it only in that unit). A range saved
            # without it never came back.
            "y2_unit": view.get("y2_unit") if view.get("y2") else None,
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
                "y2": tuple(float(v) for v in saved["y2"])
                if saved.get("y2") else None,
                "y2_unit": (saved.get("y2_unit")
                            if saved.get("y2_unit") in model.WEIGHT_UNITS
                            else None),
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
             "shading": analysis.shading,
             "label_size": analysis.label_size, "flush": analysis.flush,
             "show_interval": analysis.show_interval,
             "mass_line": bool(analysis.mass_line),
             "mass_at": analysis.mass_at, "mass_dy": analysis.mass_dy,
             "interval_size": analysis.interval_size,
             "construction": analysis.construction,
             "show_peak": analysis.show_peak,
             "number_format": analysis.number_format,
             "unit": analysis.unit,
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
    shading = saved.get("shading")
    analysis.shading = shading if shading in style.SHADINGS else None
    peak = saved.get("show_peak")
    analysis.show_peak = peak if peak in style.PEAKS else None
    analysis.label_size = _chosen(saved.get("label_size"), "analysis_size",
                                  version)
    flush = saved.get("flush")
    analysis.flush = flush if flush in style.FLUSHES else None
    analysis.show_interval = bool(saved.get("show_interval", True))
    analysis.mass_line = bool(saved.get("mass_line", False))
    analysis.mass_at = _number_or_none(saved.get("mass_at"))
    analysis.mass_dy = _number_or_none(saved.get("mass_dy"))
    analysis.interval_size = style.BY_KEY["interval_tick"].clean(
        saved.get("interval_size"))
    if "construction" in saved:
        lines = saved.get("construction")
        analysis.construction = lines if lines in style.LINES else None
    else:
        # Saved before an onset's lines had a switch of their own:
        # "Show interval markers" was the dashes AND the lines, so one saved
        # with it off had no lines either, and opens that way. No version
        # bump: the missing key says it.
        analysis.construction = (None if analysis.show_interval
                                 else style.LINES_NONE)
    if analysis.attribution != model.CURVE_NOT_STATED:
        # What the FILE does not say stays unsaid, whatever a session
        # written before that was known recorded.
        analysis.attribution = saved.get("attribution", analysis.attribution)
    # With its unit, if it names one (`%.0f degF`): a unit-less read
    # dropped such a format on every reopen.
    analysis.number_format = labels.normalise_format(
        saved.get("number_format"))
    analysis.label_at = _number_or_none(saved.get("label_at"))
    analysis.z = _number_or_none(saved.get("z"))
    unit = labels.canonical_unit(saved.get("unit"))
    analysis.unit = (unit if unit in labels.units_of(analysis.quantity)
                     else None)
    if version < 5 and measure.is_legacy_label(analysis.label):
        # A panel analysis was once GIVEN a label with its number written
        # in ("*T*_{onset} = 61.1 degC"), and a file before version 5 can
        # still hold one whose number went stale. Nobody typed that shape,
        # so it goes back to the default template, whose number follows the
        # measurement; any other label stays the user's.
        analysis.label = None



# ------------------------------------------------- where a session's files are
# A session names its files by path. Moved, a file is looked for BESIDE THE
# SESSION (its folder and the folders under it, by name), and where the
# panel keeps copies (`profile.EMBED_SOURCES`) the copy inside the session is
# read when it is nowhere to be found - and the opening says which. A file
# found by none of these is KEPT (`model.MissingSource`) until the user
# finds it: by hand, or under a folder by a name like it (`similar_files`).

def _source_copy(sample):
    """The copy a session keeps of a sample's file - zlib, then base64 - or
    None. Made once per file read (`is_modified` saves often)."""
    data = getattr(sample, "source_bytes", None)
    if not data:
        return None
    cached = getattr(sample, "_source_copy", None)
    if cached is None or cached[0] is not data:
        cached = (data, base64.b64encode(zlib.compress(data, 9)).decode(
            "ascii"))
        sample._source_copy = cached
    return cached[1]


#: How many files the look beside a session reads the names of, at most.
LOOK_LIMIT = 20000


def _look_beside(session_path, wanted):
    """A file named as `wanted` is, in the session's folder or a folder
    under it, or None."""
    name = os.path.basename(str(wanted).replace("\\", "/")).lower()
    if not name or not session_path:
        return None
    folder = os.path.dirname(os.path.abspath(session_path))
    seen = 0
    for base, dirs, files in os.walk(folder):
        dirs.sort()
        for found in files:
            if found.lower() == name:
                return os.path.join(base, found)
        seen += len(files)
        if seen > LOOK_LIMIT:
            break
    return None


#: How alike a file's name must be to the one a session knows for a search
#: under a folder to offer it (`similar_files`): difflib's ratio of the two
#: names without their extensions, case ignored. "Run-A(1)" and "Run-A" are
#: 0.92 alike - and so are "Run-1" and "Run-2", which is why such a file is
#: only ever OFFERED, never taken by itself.
SIMILAR = 0.85
#: How many file names a search under a folder reads, at most.
FIND_LIMIT = 200000

#: What Windows and a browser add to a copy's name: "x (2)", "x(1)",
#: "x - Copy", "x - Kopie (3)".
_COPY_MARKS = re.compile(
    r"(\s*\(\d+\)|\s*-\s*(copy|kopie|copie|copia|kopia)(\s*\(\d+\))?)+$",
    re.IGNORECASE)


def _name_parts(path):
    stem, ext = os.path.splitext(os.path.basename(
        str(path).replace("\\", "/")))
    return stem.lower(), ext.lower()


def similar_files(folder, wanted, cutoff=SIMILAR, limit=FIND_LIMIT):
    """The files under `folder` named like the paths in `wanted`:
    `({path: [(score, found), ...]}, complete)`. A file must have the same
    extension, and its name without it be at least `cutoff` alike
    (`SIMILAR`; the same name scores 1) - or be the same name but for the
    marks of a copy ("x (1)", "x - Copy"). The likeliest come first: the
    same name, then a copy's, then a name with the same NUMBERS in it,
    then the rest by score - "Run-2" is as like "Run-1" as "Run-1(1)" is,
    and is another run. `complete` is False when the search stopped after
    `limit` names."""
    targets = []
    for path in wanted:
        stem, ext = _name_parts(path)
        targets.append((path, stem, ext, _COPY_MARKS.sub("", stem),
                        re.findall(r"\d+", stem)))
    hits = dict((path, []) for path in wanted)
    seen, complete = 0, True
    for base, dirs, files in os.walk(str(folder)):
        dirs.sort()
        for name in files:
            stem, ext = _name_parts(name)
            for path, want, want_ext, want_core, numbers in targets:
                if ext != want_ext:
                    continue
                match = difflib.SequenceMatcher(None, want, stem)
                if stem == want:
                    score, rank = 1.0, 3
                elif _COPY_MARKS.sub("", stem) == want_core:
                    score, rank = match.ratio(), 2
                else:
                    if (match.real_quick_ratio() < cutoff
                            or match.quick_ratio() < cutoff):
                        continue
                    score = match.ratio()
                    if score < cutoff:
                        continue
                    rank = 1 if re.findall(r"\d+", stem) == numbers else 0
                hits[path].append((rank, score, os.path.join(base, name)))
        seen += len(files)
        if seen > limit:
            complete = False
            break
    out = {}
    for path, found in hits.items():
        found.sort(key=lambda hit: (-hit[0], -hit[1], hit[2].lower()))
        out[path] = [(score, where) for _rank, score, where in found]
    return out, complete


def _size_text(size):
    for unit, step in (("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if size >= step:
            return "{:,} bytes ({:.1f} {})".format(size, size / step, unit)
    return "{:,} bytes".format(size)


def file_facts(path):
    """`[(what, value), ...]` of a file on disk for "Details...": where it
    is, how big, when it was made and changed, and a fingerprint of its
    contents - what tells two files of one name apart."""
    path = str(path)
    facts = [("File", os.path.basename(path)),
             ("Folder", os.path.dirname(os.path.abspath(path)))]
    try:
        info = os.stat(path)
    except OSError:
        facts.append(("On disk", "not there"))
        return facts

    def when(seconds):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(seconds))

    facts.append(("Size", _size_text(info.st_size)))
    if os.name == "nt":                 # st_ctime is the creation there
        facts.append(("Created", when(info.st_ctime)))
    facts.append(("Modified", when(info.st_mtime)))
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                digest.update(block)
        facts.append(("SHA-256", digest.hexdigest()))
    except OSError:
        pass
    return facts


def missing_facts(gone):
    """`[(what, value), ...]` of a file the session could not read
    (`model.MissingSource`), for "Details..."."""
    facts = [("File", gone.name), ("Saved as", gone.path),
             ("Why", gone.reason or "not found")]
    folder = os.path.dirname(gone.path)
    facts.append(("Its folder", "is there" if folder and os.path.isdir(
        folder) else "is not there either"))
    title = gone.entry.get("title")
    if title:
        facts.append(("Named", str(title)))
    facts.append(("Curves kept", str(len(gone.scans))))
    facts.append(("Analyses kept", str(gone.analysis_count())))
    facts.append(("Labels kept", str(len(gone.labels))))
    return facts


def _read_entry(entry, session_path, read_sample, notes, relocated,
                found=None):
    """One of a session's files: where the user found it (`found`, by the
    saved path's `normcase`); else where it was; else beside the session;
    else the copy inside it. Raises with the reader's reason when none of
    them is there. A file read from elsewhere keeps the path the session
    knew it by until the opening is done (everything is matched by it),
    then takes its new one (`relocated`)."""
    path = entry["path"]
    shown = os.path.basename(str(path).replace("\\", "/"))
    chosen = (found or {}).get(os.path.normcase(str(path)))
    if chosen:
        sample = read_sample(chosen)
        sample.path = path
        relocated.append((sample, chosen))
        return sample
    if os.path.isfile(path):
        return read_sample(path)
    beside = _look_beside(session_path, path)
    if beside is not None:
        sample = read_sample(beside)
        sample.path = path
        relocated.append((sample, beside))
        notes.append("{}: moved - found beside the session".format(shown))
        return sample
    copy = entry.get("copy")
    if copy:
        data = zlib.decompress(base64.b64decode(copy))
        folder = tempfile.mkdtemp(prefix="panel-copy-")
        try:
            temp = os.path.join(folder, shown)
            with open(temp, "wb") as fh:
                fh.write(data)
            sample = read_sample(temp)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        sample.path = path
        sample.source_bytes = data
        sample.from_copy = True
        notes.append("{}: not where it was - read from the copy inside "
                     "the session".format(shown))
        return sample
    return read_sample(path)


def _kept_missing(doc, gone_at, problems, entry, place, exc):
    """A file that could not be read, kept for the next save and for the
    finding (`model.MissingSource`); the opening says so."""
    gone = model.MissingSource(entry.get("path", "?"), entry, exc)
    gone.index = place
    if gone.found_nowhere:
        gone.reason = "not found"
    doc.missing.append(gone)
    gone_at[os.path.normcase(gone.path)] = gone
    problems.append("{}: {} - kept in the outliner (right-click it to look "
                    "for it)".format(gone.name, gone.reason))
    return gone


def _splice(state, key, extra):
    """`extra` - `[(place, entry), ...]` - back into the list `state[key]`
    at their places; returns where each entry already there went."""
    items = list(state.get(key) or [])
    slots = [(False, k) for k in range(len(items))]
    for place, entry in sorted(extra, key=lambda pair: pair[0]):
        slots.insert(min(place, len(slots)), (True, entry))
    moved, out = {}, []
    for new, (kept, what) in enumerate(slots):
        if kept:
            out.append(what)
        else:
            moved[what] = new
            out.append(items[what])
    state[key] = out
    return moved


def _keep_missing(doc, state):
    """What the session held of its missing files (`doc.missing`) put back
    into `state` where it was - their entries, their curves', the labels
    hanging from them - and the colour links of everything else moved to
    match. A link to or from a missing file's object is not kept (its
    colour is)."""
    gone = sorted(doc.missing, key=lambda item: item.index)
    if not gone:
        return state
    for item in gone:
        state["samples"].insert(min(item.index, len(state["samples"])),
                                dict(item.entry))
    before = [len(entry.get("analyses") or ()) for entry in state["scans"]]
    scan_moves = _splice(state, "scans",
                         [pair for item in gone for pair in item.scans])
    label_moves = _splice(state, "labels",
                          [pair for item in gone for pair in item.labels])
    starts, count = [], 0
    for entry in state["scans"]:
        starts.append(count)
        count += len(entry.get("analyses") or ())
    old = []
    for index, many in enumerate(before):
        old.extend((index, k) for k in range(many))

    def moved(ref):
        kind, index = ref
        if kind in ("scans", "markers"):
            return [kind, scan_moves[int(index)]]
        if kind == "labels":
            return [kind, label_moves[int(index)]]
        if kind == "analyses":
            index, k = old[int(index)]
            return [kind, starts[scan_moves[index]] + k]
        return ref

    links = []
    for pair in state.get("colour_links") or ():
        try:
            links.append([moved(pair[0]), moved(pair[1])])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
    state["colour_links"] = links
    # A span's ends name labels by their places; a region its curves by
    # their files', a missing one's kept aside (`kept_scans`).
    for span in state.get("spans") or ():
        span["ends"] = [label_moves.get(end) if isinstance(end, int) else end
                        for end in span.get("ends") or ()]
    still = set(os.path.normcase(item.path) for item in gone)
    for region, entry in zip(getattr(doc, "regions", None) or (),
                             state.get("regions") or ()):
        entry["scans"] = list(entry.get("scans") or ()) + [
            path for path in getattr(region, "kept_scans", ())
            if os.path.normcase(path) in still]
    return state


def _saved_target(doc, state, scan_at, label_at, made_at):
    """What a session's colour link - `[list, position]` - names among what
    was opened. Curves, their markers and analyses and the labels go by
    their places IN THE FILE (`scan_at`, `label_at`, `made_at`), which a
    missing file or an analysis not measured again would shift."""
    flat = [(place, k) for place, entry in enumerate(state.get("scans")
                                                     or ())
            for k in range(len(entry.get("analyses") or ()))]

    def target(ref):
        try:
            kind, index = ref
            if kind in ("scans", "markers"):
                scan = scan_at.get(int(index))
                if scan is None or kind == "scans":
                    return scan
                return getattr(scan, "marker", None)
            if kind == "labels":
                return label_at.get(int(index))
            if kind == "analyses":
                k = int(index)
                return made_at.get(flat[k]) if 0 <= k < len(flat) else None
        except (TypeError, ValueError):
            return None
        return model._colour_target(doc, ref)

    return target


def to_state(doc):
    """The document as plain data, ready for `json.dump`."""
    samples = []
    for sample in doc.samples:
        samples.append({
            "path": sample.path,
            "molar_mass": sample.molar_mass,
            "exo": sample.exo,
            "exo_source": sample.exo_source,
            "title": sample.title,
            "composition": sample.composition,
        })
    for entry, sample in zip(samples, doc.samples):
        copy = _source_copy(sample)
        if copy:
            entry["copy"] = copy
    scans = []
    for scan in doc.scans:
        scans.append({
            "path": scan.sample.path,
            "seg": scan.seg,
            "signal": scan.signal,
            "dtg_window": scan.dtg_window if scan.is_dtg else None,
            "colour": scan.colour,
            "offset": scan.offset,
            "line_width": scan.line_width,
            "keep": list(scan.keep),
            "label": scan.label,
            "visible": scan.visible,
            "analyses": [_analysis_state(a) for a in scan.analysis_objects],
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
                       "label_gap": axis.label_gap,
                       "lock": (list(axis.lock) if axis.lock else None),
                       "lock_context": (list(axis.lock_context)
                                        if axis.lock_context else None),
                       "hidden_numbers": [float(v) for v in
                                          axis.hidden_numbers or ()],
                       "hidden_context": (list(axis.hidden_context)
                                          if axis.hidden_numbers
                                          and axis.hidden_context else None)}
    labels = []
    for lb in doc.labels:
        labels.append({"text": lb.text, "x": lb.x, "y": lb.y,
                       "colour": lb.colour, "size": lb.size, "bold": lb.bold,
                       "visible": lb.visible, "space": lb.space,
                       "anchor": lb.anchor, "rotation": lb.rotation,
                       "z": lb.z,
                       "scan": (None if lb.scan is None
                                else [lb.scan.sample.path, lb.scan.seg]),
                       "parent_offset": lb.parent_offset,
                       "at": (list(lb.at) if lb.at else None),
                       "dx": lb.dx, "dy": lb.dy,
                       "leader": lb.leader,
                       "leader_from": lb.leader_from,
                       "leader_colour": lb.leader_colour,
                       "flush": lb.flush,
                       "vline": lb.vline, "line_dashed": lb.line_dashed})
    state = {
        "format": FORMAT,
        "version": VERSION,
        "axes": axes,
        "labels": labels,
        "structures": [{"smiles": m.smiles, "atoms": m.atoms,
                        "bonds": m.bonds, "x": m.x, "y": m.y,
                        "space": m.space, "anchor": m.anchor,
                        "rotation": m.rotation, "z": m.z,
                        "visible": m.visible, "colour": m.colour,
                        "bond_length": m.bond_length,
                        "bond_width": m.bond_width,
                        "label_size": m.label_size,
                        "upright_labels": m.upright_labels,
                        "label_font": m.label_font,
                        "colour_by_element": m.colour_by_element}
                       for m in doc.structures],
        "images": [{"png": im.png, "x": im.x, "y": im.y,
                    "space": im.space, "anchor": im.anchor,
                    "rotation": im.rotation, "width": im.width,
                    "z": im.z, "visible": im.visible,
                    "mirror_h": im.mirror_h, "mirror_v": im.mirror_v}
                   for im in doc.images],
        "x_axis": doc.x_axis,
        "x_unit": doc.x_unit,
        "y_unit": doc.y_unit,
        "weight_unit": doc.weight_unit,
        "dtg_unit": doc.dtg_unit,
        "theme": doc.theme,
        "background": doc.background,
        "follow_zoom": bool(doc.follow_zoom),
        "offset_markers": bool(doc.offset_markers),
        "view": view_to_state(doc.view),
        "style": doc.style.chosen(),
        "figure": doc.figure.to_state(),
        "figure_grown": dict(doc.figure.grown),
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
        "colour_links": model.colour_links(doc),
    }
    return _keep_missing(doc, state)


def save(doc, path):
    """Write the session. The document remembers where it went."""
    state = to_state(doc)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)
    doc.path = str(path)
    return path


def load(path, read_sample, found=None):
    """Rebuild a document from a session file.

    Returns `(document, problems)`. `problems` names every file that could not
    be read, so the window can say so in one line and still show everything
    else. `found`: see `from_state`.
    """
    with open(path, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    return from_state(state, path, read_sample, found)


def from_state(state, path, read_sample, found=None):
    """Rebuild a document from a session's `state`, saved at `path` (where
    a moved file is looked for). `found` maps a path the session names to
    where that file is now - a file the user found. A file that cannot be
    read is kept as it was (`doc.missing`). Returns `(document,
    problems)`."""
    if state.get("format") != FORMAT:
        raise ValueError("not a {} file".format(FORMAT))
    found = dict((os.path.normcase(str(saved)), str(now))
                 for saved, now in (found or {}).items() if now)
    doc = model.Document()
    version = int(state.get("version", 1) or 1)
    #: Which version it was read from: before 7, a decorator's place was a
    #: fraction of the VIEW, not of the home frame (`PlotWidget.rehome`).
    doc.loaded_version = version
    problems = []
    by_path = {}
    relocated = []
    gone_at = {}
    # Where each curve, analysis and label of the FILE went (a colour link
    # names them by their places there).
    scan_at, made_at, label_at = {}, {}, {}
    saved_style = dict(state.get("style") or {})
    if version < 6:
        # The fit margins were percent of the data's range until version 6.
        style.convert_old_fit(saved_style)
    for key, raw in saved_style.items():
        if key in style.BY_KEY and style.BY_KEY[key].figure:
            setattr(doc.style, key, style.BY_KEY[key].clean(raw))
    # A session keeps its OWN figure size; one saved before there was such
    # a thing follows the window, as it did then - not today's default.
    doc.figure = figure_module.FigureLayout().load_state(
        state.get("figure") or {"mode": figure_module.MODE_WINDOW})
    doc.figure.grown = figure_module.clean_grown(state.get("figure_grown"))
    for place, entry in enumerate(state.get("samples", [])):
        try:
            sample = _read_entry(entry, path, read_sample, problems,
                                 relocated, found)
        except Exception as exc:
            _kept_missing(doc, gone_at, problems, entry, place, exc)
            continue
        if entry.get("molar_mass"):
            sample.molar_mass = float(entry["molar_mass"])
        if entry.get("exo") in (units.EXO_DOWN, units.EXO_UP):
            sample.exo = entry["exo"]
            sample.exo_source = entry.get("exo_source", sample.exo_source)
        title = entry.get("title")
        sample.title = str(title) if title else None
        made_of = entry.get("composition")
        sample.composition = str(made_of) if made_of else None
        doc.samples.append(sample)
        by_path[os.path.normcase(sample.path)] = sample
    # An older session kept a scan's weight as a dashed extra on it; a
    # weight shown there opens as a mass scan of its own, AFTER the saved
    # scans (labels name their scan by its place in the list).
    legacy_mass = []
    for place, entry in enumerate(state.get("scans", [])):
        key = os.path.normcase(entry.get("path", ""))
        if key in gone_at:
            gone_at[key].scans.append((place, entry))
            continue
        sample = by_path.get(key)
        if sample is None:
            continue
        seg = int(entry.get("seg", 0))
        if seg >= sample.segment_count():
            problems.append("{}: segment {} is gone".format(sample.name,
                                                            seg + 1))
            continue
        signal = (entry.get("signal") if entry.get("signal") in model.SIGNALS
                  else model.SIGNAL_HEAT)
        scan = model.Scan(doc._next_id(), sample, seg,
                          entry.get("colour")
                          or model.PALETTE[len(doc.scans) % len(model.PALETTE)],
                          signal)
        scan.offset = float(entry.get("offset", 0.0))
        window = _number_or_none(entry.get("dtg_window"))
        if window is not None and window >= 0:
            scan.dtg_window = window
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
        weight = entry.get("weight")
        if (isinstance(weight, dict) and weight.get("visible", True)
                and signal == model.SIGNAL_HEAT and scan.has_weight()):
            legacy_mass.append((sample, seg, scan.colour))
        stored = entry.get("analyses") or []
        wanted = dict((item.get("key"), k) for k, item in enumerate(stored)
                      if item.get("source") != "panel")
        for analysis in scan.analysis_objects:
            k = wanted.get(analysis.key())
            if k is not None:
                _restore_analysis(analysis, stored[k], version)
                made_at[(place, k)] = analysis
        for k, saved in enumerate(stored):
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
            made_at[(place, k)] = made
        # A scan has no molar mass of its own: one an older session gave
        # a scan goes to its file, if the file had none.
        own = _number_or_none(entry.get("molar_mass_override"))
        if own and own > 0 and not sample.molar_mass:
            sample.molar_mass = float(own)
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
        scan_at[place] = scan
    for sample, seg, colour in legacy_mass:
        if any(s.sample is sample and s.seg == seg and s.is_mass
               for s in doc.scans):
            continue
        mass = model.Scan(doc._next_id(), sample, seg, colour,
                          model.SIGNAL_MASS)
        sample.scans.append(mass)
        doc.scans.append(mass)
    arrow = state.get("arrow") or {}
    doc.arrow.word = arrow.get("word", doc.arrow.word)
    doc.arrow.direction = arrow.get("direction", doc.arrow.direction)
    doc.arrow.x = float(arrow.get("x", doc.arrow.x))
    doc.arrow.y = float(arrow.get("y", doc.arrow.y))
    # Its dimensions are in points. An older session's `length`
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
        lock = saved.get("lock")
        try:
            lock = [float(lock[0]), float(lock[1])] if lock else None
        except (TypeError, ValueError, IndexError):
            lock = None
        axis.lock = lock if lock and lock[1] > lock[0] else None
        context = saved.get("lock_context")
        axis.lock_context = (list(context) if axis.lock and
                             isinstance(context, list) else None)
        hidden = []
        for value in saved.get("hidden_numbers") or ():
            value = _number_or_none(value)
            if value is not None and value == value and abs(value) != \
                    float("inf"):
                hidden.append(value)
        context = saved.get("hidden_context")
        axis.hidden_context = (list(context) if hidden
                               and isinstance(context, list) else None)
        axis.hidden_numbers = hidden if axis.hidden_context else []
    for place, saved in enumerate(state.get("labels") or []):
        owner = None
        owned = saved.get("scan")
        if (isinstance(owned, (list, tuple)) and owned
                and os.path.normcase(str(owned[0])) in gone_at):
            # Hanging from a missing file's curve: kept with the file.
            gone_at[os.path.normcase(str(owned[0]))].labels.append(
                (place, saved))
            continue
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
        # Where its scan stood when it was placed. A session from before
        # labels followed their scan has none: it stays where it was drawn.
        followed = _number_or_none(saved.get("parent_offset"))
        if owner is not None and followed is not None:
            label.parent_offset = followed
        # A note's arrow: the point it names, [degC, heat flow].
        leader = saved.get("leader")
        if (isinstance(leader, (list, tuple)) and len(leader) == 2
                and all(_number_or_none(v) is not None for v in leader)):
            label.leader = [float(leader[0]), float(leader[1])]
        start = saved.get("leader_from", "auto")
        label.leader_from = start if start in model.ANCHORS else "auto"
        label.leader_colour = saved.get("leader_colour") or "auto"
        flush = saved.get("flush")
        label.flush = flush if flush in ("left", "right", "center") else None
        label.vline = _number_or_none(saved.get("vline"))
        # Hanging from its curve; an older one is attached
        # where it is drawn once the session is on screen.
        at = saved.get("at")
        if (owner is not None and isinstance(at, (list, tuple))
                and len(at) == 2 and at[0] == "i"
                and _number_or_none(at[1]) is not None):
            label.at = ("i", int(at[1]))
            label.dx = float(_number_or_none(saved.get("dx")) or 0.0)
            label.dy = _number_or_none(saved.get("dy"))
        label.line_dashed = bool(saved.get("line_dashed", True))
        label_at[place] = label
    for saved in state.get("structures") or []:
        if not saved.get("atoms"):
            continue
        structure = model.MoleculeArtist(
            doc._next_id(), saved.get("smiles", ""),
            {"atoms": saved["atoms"], "bonds": saved.get("bonds", [])},
            float(saved.get("x", 0.5)), float(saved.get("y", 0.5)))
        for name in ("space", "anchor", "colour"):
            if saved.get(name) is not None:
                setattr(structure, name, saved[name])
        for name in ("rotation", "bond_length", "bond_width", "label_size"):
            value = _number_or_none(saved.get(name))
            if value is not None:
                setattr(structure, name, value)
        structure.z = _number_or_none(saved.get("z"))
        structure.visible = bool(saved.get("visible", True))
        structure.upright_labels = bool(saved.get("upright_labels", True))
        structure.label_font = saved.get("label_font") or None
        structure.colour_by_element = bool(saved.get("colour_by_element",
                                                     False))
        doc.structures.append(structure)
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
        image.mirror_h = bool(saved.get("mirror_h", False))
        image.mirror_v = bool(saved.get("mirror_v", False))
        doc.images.append(image)
    for name, value in (state.get("legend") or {}).items():
        if hasattr(doc.legend, name):
            setattr(doc.legend, name, value)
    doc.legend.rotation = float(
        _number_or_none((state.get("legend") or {}).get("rotation")) or 0.0)
    doc.legend.z = _number_or_none((state.get("legend") or {}).get("z"))
    if version < 5:
        # The frame was on by default before version 5, so an older file's
        # True was the default and not a choice; it follows the new one.
        doc.legend.show_frame = False
    doc.legend.size = _chosen((state.get("legend") or {}).get("size"),
                              "legend_size", version)
    doc.x_axis = state.get("x_axis", doc.x_axis)
    if state.get("x_unit") in units.TEMPERATURE_UNITS:
        doc.x_unit = state["x_unit"]
    doc.y_unit = state.get("y_unit", doc.y_unit)
    if state.get("weight_unit") in model.WEIGHT_UNITS:
        doc.weight_unit = state["weight_unit"]
    if state.get("dtg_unit") in dtg.UNITS:
        doc.dtg_unit = state["dtg_unit"]
    doc.theme = state.get("theme", doc.theme)
    background = state.get("background")
    # Version 7 placed decorators in the home frame (they followed the
    # zoom, the only way then); 8 says which. The window converts a
    # version-7 figure's places to the page's once it is on screen.
    doc.follow_zoom = bool(state.get("follow_zoom", False))
    doc.background = (str(background) if isinstance(background, str)
                      and background.startswith("#") else None)
    doc.offset_markers = bool(state.get("offset_markers", False))
    doc.view = _view_from(state.get("view"))
    if doc.view and doc.view.get("y2") and not doc.view.get("y2_unit"):
        # Written with the range and not its unit: it was the weight unit
        # saved with it (a change of unit fits the range
        # again, so a range is always in the unit in force).
        doc.view["y2_unit"] = doc.weight_unit
    model.restore_colour_links(
        doc, state.get("colour_links"),
        _saved_target(doc, state, scan_at, label_at, made_at))
    for sample, found in relocated:
        sample.path = found
    doc.path = str(path)
    return doc, problems
